import streamlit as st
import pandas as pd
import requests
import json
import time
import os
import urllib.request
import math
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

# ==========================================
# 1. 화면 기본 설정
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (움직이는 비디오 + 자동 자막)")
st.markdown("대본(Groq), **동영상(fal 비디오)**, 음성 생성부터 **MP4 자동 자막 영상 병합**까지 지원합니다.")

# ==========================================
# 2. API 연동 함수 정의
# ==========================================
def call_groq(prompt, api_key):
    if not api_key: return "Groq 에러: API 키가 없습니다."
    api_key = api_key.strip()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",  
        "messages": [
            {"role": "system", "content": "당신은 한국어 유튜브 전문 작가입니다. 대본 본문만 작성해 주세요."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200: return res.json()['choices'][0]['message']['content']
        else: return f"Groq 거부 ({res.status_code}): {res.text[:150]}"
    except Exception as e: return f"Groq 통신 에러: {str(e)[:150]}"

def call_fal_video(prompt, ref_url, aspect_ratio, api_key):
    """fal.ai를 사용하여 고화질 움직이는 비디오를 생성합니다."""
    if not api_key: return None
    api_key = api_key.strip()
    url = "https://queue.fal.run/fal-ai/luma-dream-machine"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    
    payload = {
        "prompt": prompt,
        "aspect_ratio": "9:16" if aspect_ratio == "9:16" else "16:9"
    }
    if pd.notna(ref_url) and str(ref_url).strip() and str(ref_url).strip() != 'nan':
        payload["image_url"] = str(ref_url).strip()
        
    try:
        create_res = requests.post(url, headers=headers, json=payload)
        if create_res.status_code != 200: return None
        response_url = create_res.json().get('response_url')
        
        for _ in range(30): # 비디오 생성은 오래 걸리므로 대기 시간 증가
            time.sleep(5)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                result_data = poll_res.json()
                video_url = result_data.get('video', {}).get('url')
                if video_url: return video_url
        return None
    except Exception:
        return None

def call_fal_tts(script, api_key):
    if not api_key: return "fal 에러: API 키가 없습니다."
    api_key = api_key.strip()
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {"text": script[:500] if len(script) > 500 else script}
    
    try:
        create_res = requests.post(url, headers=headers, json=payload)
        if create_res.status_code != 200: return f"fal 서버 거부 ({create_res.status_code})"
        response_url = create_res.json().get('response_url')
        for _ in range(10):
            time.sleep(3)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                audio_url = poll_res.json().get('audio', {}).get('url')
                if audio_url: return audio_url
        return "fal 응답 시간 초과"
    except Exception as e: return f"fal 통신 에러: {str(e)[:50]}"

def download_file(url, save_path):
    """다운로드 차단을 방지하는 우회 함수"""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
        out_file.write(response.read())

# ==========================================
# 3. 사이드바 (API 키 설정)
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    FAL_KEY = st.text_input("fal.ai API Key (비디오/음성용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭
# ==========================================
tab1, tab2 = st.tabs(["🚀 자동화 파이프라인 (대본/비디오/음성 생성)", "📑 영상 병합 (자동 자막 비디오)"])

# ----------------- TAB 1 -----------------
with tab1:
    st.subheader("대량 영상 재료(대본/동영상/음성) 자동 생성")
    col1, col2 = st.columns([1, 2])
    with col1:
        video_type = st.radio("영상 포맷", ["쇼츠 (9:16)", "롱폼 (16:9)"])
        aspect_ratio = "9:16" if "쇼츠" in video_type else "16:9"
    with col2:
        file1 = st.file_uploader("기획안 업로드 (엑셀/CSV)", type=['csv', 'xlsx'], key="f1")
    
    if file1:
        df1 = pd.read_excel(file1) if file1.name.endswith('.xlsx') else pd.read_csv(file1)
        st.success(f"✅ 총 {len(df1)}개의 작업 감지")
        
        if st.button("🔥 생성 시작 (비디오 포함)", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []
            
            for index, row in df1.iterrows():
                status_text.markdown(f"**작업 {index+1}/{len(df1)} 진행 중...** (비디오 생성 중이므로 시간이 걸립니다 ⏳)")
                topic_col = next((c for c in df1.columns if '주제' in c), None)
                ref_col = next((c for c in df1.columns if '레퍼런스' in c), None)
                topic = str(row[topic_col]) if topic_col and pd.notna(row[topic_col]) else "랜덤 주제"
                ref_image = str(row[ref_col]) if ref_col and pd.notna(row[ref_col]) else ""
                
                # 1. 대본 생성
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 대본 작성)", GROQ_KEY)
                
                # 2. 비디오 생성 (fal.ai Luma Dream Machine)
                vid_prompt = f"High quality, cinematic video about {topic}"
                visual_url = call_fal_video(vid_prompt, ref_image, aspect_ratio, FAL_KEY)
                
                if not visual_url or "http" not in visual_url:
                    visual_url = "비디오 생성 에러: API 키 또는 크레딧 확인"
                
                # 3. 음성 생성
                aud_url = call_fal_tts(ai_script, FAL_KEY)
                
                results.append({
                    "주제": topic, 
                    "대본": ai_script, 
                    "비디오": visual_url, 
                    "음성": aud_url
                })
                progress_bar.progress((index + 1) / len(df1))
                
            status_text.success("🎉 작업 완료! 아래 엑셀 파일을 다운로드하여 2번 탭에 넣어주세요.")
            result_df = pd.DataFrame(results)
            st.dataframe(result_df)
            csv = result_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(label="💾 완성된 엑셀 다운로드", data=csv, file_name='video_materials.csv', mime='text/csv')

# ----------------- TAB 2 (자막 자동 추가 병합기) -----------------
with tab2:
    st.subheader("📑 최종 영상(MP4) 자동 병합 (자동 자막 추가)")
    st.markdown("1번 탭에서 받은 엑셀을 업로드하면 **비디오 + 음성 + 예쁜 자막**이 합쳐진 완제품을 만듭니다!")
    
    file2 = st.file_uploader("완료된 엑셀(CSV) 업로드", type=['csv'], key="f2")
    
    if file2:
        df2 = pd.read_csv(file2)
        st.dataframe(df2.head(3))
        
        if st.button("🎬 자막 포함 동영상 렌더링 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            if not os.path.exists("output_videos"):
                os.makedirs("output_videos")
                
            for index, row in df2.iterrows():
                topic = str(row.get('주제', f'video_{index}'))
                script_text = str(row.get('대본', ''))
                vis_url = str(row.get('비디오', ''))
                audio_url = str(row.get('음성', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df2)}] '{topic}' 자막 영상 렌더링 중... ⏳**")
                
                if "http" not in vis_url or "http" not in audio_url:
                    st.warning(f"⚠️ '{topic}'은(는) 정상적인 비디오나 음성 링크가 없어 건너뜁니다.")
                    continue
                    
                try:
                    # 파일 다운로드
                    temp_vis_path = f"temp_vid_{index}.mp4"
                    audio_path = f"temp_audio_{index}.mp3"
                    output_path = f"output_videos/result_with_subs_{index}.mp4"
                    
                    download_file(vis_url, temp_vis_path)
                    download_file(audio_url, audio_path)
                    
                    # 비디오와 오디오 불러오기
                    video_clip = VideoFileClip(temp_vis_path)
                    audio_clip = AudioFileClip(audio_path)
                    
                    # 1. 비디오 길이를 오디오에 맞게 반복 (Loop)
                    if video_clip.duration < audio_clip.duration:
                        num_loops = math.ceil(audio_clip.duration / video_clip.duration)
                        video_clip = concatenate_videoclips([video_clip] * num_loops)
                    video_clip = video_clip.subclip(0, audio_clip.duration)
                    video_clip = video_clip.set_audio(audio_clip)
                    
                    # 2. 💡 자동 자막 추가 기능
                    # 대본이 길면 20글자 단위로 잘라서 화면에 뿌려줍니다.
                    # 스트림릿 서버에 한글 폰트가 없을 수 있으므로 기본 폰트(Arial 등)를 사용하되 에러를 방지합니다.
                    try:
                        txt_clip = TextClip(
                            script_text[:50] + "...", # 임시로 첫 50글자만 표시 (전체 표시는 타이밍 조절 필요)
                            fontsize=40, 
                            color='white', 
                            bg_color='black',
                            method='caption',
                            size=(video_clip.w * 0.8, None)
                        )
                        txt_clip = txt_clip.set_position('center', 'bottom').set_duration(video_clip.duration)
                        
                        # 비디오 위에 자막을 덧씌웁니다.
                        final_clip = CompositeVideoClip([video_clip, txt_clip])
                    except Exception as font_err:
                        # 폰트 에러 시 자막 없이 비디오만 생성
                        st.warning(f"자막 생성 오류 (기본 영상으로 대체됨): {font_err}")
                        final_clip = video_clip
                    
                    # 3. MP4 파일로 최종 저장
                    final_clip.write_videofile(
                        output_path, 
                        fps=24, 
                        codec="libx264", 
                        audio_codec="aac",
                        logger=None
                    )
                    
                    st.success(f"🎉 '{topic}' 자막 포함 MP4 동영상 완성!")
                    st.video(output_path)
                    
                    with open(output_path, "rb") as v_file:
                        st.download_button(
                            label=f"💾 '{topic}' 자막 동영상 다운로드",
                            data=v_file,
                            file_name=f"{topic}_subtitle.mp4",
                            mime="video/mp4",
                            key=f"dl_{index}"
                        )
                        
                except Exception as e:
                    st.error(f"'{topic}' 합성 중 에러 발생: {e}")
                
                progress_bar.progress((index + 1) / len(df2))
                
            status_text.success("✅ 모든 자막 비디오 생성이 완료되었습니다!")
