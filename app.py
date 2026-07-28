import streamlit as st
import pandas as pd
import requests
import json
import time
import os
import urllib.request
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

# ==========================================
# 1. 화면 기본 설정
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (통합형 마스터)")
st.markdown("대본(Groq), **동영상(fal 비디오)**, 음성 생성부터 **MP4 동영상 최종 병합**까지 지원합니다.")

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
            {"role": "system", "content": "당신은 한국어 유튜브 전문 작가입니다. 대본만 제공하세요."},
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
    """fal.ai를 이용해 프롬프트(또는 이미지) 기반으로 짧은 비디오를 생성합니다."""
    if not api_key: return "비디오 에러: API 키가 없습니다."
    api_key = api_key.strip()
    
    # 💡 Luma Dream Machine 모델 사용 (텍스트 to 비디오 또는 이미지 to 비디오)
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
        if create_res.status_code != 200: return f"비디오 서버 거부 ({create_res.status_code}): {create_res.text[:100]}"
        response_url = create_res.json().get('response_url')
        
        # 비디오 생성은 1~2분 정도 걸릴 수 있으므로 넉넉히 대기합니다 (20번 반복, 5초 대기 = 최대 100초)
        for _ in range(25):
            time.sleep(5)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                result_data = poll_res.json()
                video_url = result_data.get('video', {}).get('url')
                if video_url: return video_url
        return "비디오 생성 응답 시간 초과"
    except Exception as e: return f"비디오 통신 에러: {str(e)[:50]}"

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

# ==========================================
# 다운로드 권한 뚫기 (User-Agent 위조 함수)
# ==========================================
def download_file(url, save_path):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
        out_file.write(response.read())

# ==========================================
# 3. 사이드바 (API 키 설정)
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    # KIE 키는 제거하고, FAL 키로 비디오와 음성을 모두 처리합니다.
    FAL_KEY = st.text_input("fal.ai API Key (음성/비디오용)", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚀 자동화 파이프라인 (쇼츠/롱폼)", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합 (최종 MP4)"])

# ----------------- TAB 1 (쇼츠/롱폼) -----------------
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
                status_text.markdown(f"**작업 {index+1}/{len(df1)} 진행 중...** (비디오 생성으로 인해 시간이 더 소요됩니다)")
                topic_col = next((c for c in df1.columns if '주제' in c), None)
                ref_col = next((c for c in df1.columns if '레퍼런스' in c), None)
                topic = str(row[topic_col]) if topic_col and pd.notna(row[topic_col]) else "랜덤 주제"
                ref_image = str(row[ref_col]) if ref_col and pd.notna(row[ref_col]) else ""
                
                # 대본 작성
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 대본 작성)", GROQ_KEY)
                
                # 💡 이제 KIE(정지 이미지) 대신 fal.ai(동영상)를 호출합니다!
                vid_prompt = f"High quality cinematic video about {topic}"
                video_url = call_fal_video(vid_prompt, ref_image, aspect_ratio, FAL_KEY)
                
                # 음성 생성
                aud_url = call_fal_tts(ai_script, FAL_KEY)
                
                results.append({"주제": topic, "대본": ai_script[:150], "비디오": video_url, "음성": aud_url})
                progress_bar.progress((index + 1) / len(df1))
                
            status_text.success("🎉 작업 완료! 아래 엑셀 파일을 다운로드하여 4번 탭(영상 병합)에 넣어주세요.")
            result_df = pd.DataFrame(results)
            st.dataframe(result_df)
            csv = result_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(label="💾 완성된 엑셀 다운로드", data=csv, file_name='video_materials.csv', mime='text/csv')

# ----------------- TAB 2, 3 생략 -----------------
with tab2: st.info("음원 생성 API 연동 자리")
with tab3: st.info("AI 모션 API 연동 자리")

# ----------------- TAB 4 (통합 MP4 병합기) -----------------
with tab4:
    st.subheader("📑 최종 영상(MP4) 자동 병합")
    st.markdown("1번 탭에서 다운로드한 엑셀(비디오+음성 링크 포함)을 올려주세요.")
    
    file4 = st.file_uploader("완료된 엑셀(CSV) 업로드", type=['csv'], key="f4")
    
    if file4:
        df4 = pd.read_csv(file4)
        st.dataframe(df4.head(3))
        
        if st.button("🎬 MP4 동영상 렌더링 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            if not os.path.exists("output_videos"):
                os.makedirs("output_videos")
                
            for index, row in df4.iterrows():
                topic = str(row.get('주제', f'video_{index}'))
                # 이제 컬럼명이 '이미지'가 아니라 '비디오'입니다
                vid_url = str(row.get('비디오', ''))
                audio_url = str(row.get('음성', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df4)}] '{topic}' 영상을 굽고 있습니다... ⏳**")
                
                if "http" not in vid_url or "http" not in audio_url:
                    st.warning(f"⚠️ '{topic}'은(는) 정상적인 비디오나 음성 링크가 없어 건너뜁니다.")
                    continue
                    
                try:
                    # 1. 파일 다운로드 (이제 mp4 파일을 다운로드합니다)
                    vid_path = f"temp_vid_{index}.mp4"
                    audio_path = f"temp_audio_{index}.mp3"
                    output_path = f"output_videos/result_{index}.mp4"
                    
                    download_file(vid_url, vid_path)
                    download_file(audio_url, audio_path)
                    
                    # 2. 영상과 음성 합치기
                    video_clip = VideoFileClip(vid_path)
                    audio_clip = AudioFileClip(audio_path)
                    
                    # 음성 길이에 맞춰서 동영상을 반복(루프) 재생시킵니다!
                    if video_clip.duration < audio_clip.duration:
                        # 영상이 너무 짧으면 음성 길이에 맞게 영상 클립을 여러 번 이어 붙임
                        import math
                        num_loops = math.ceil(audio_clip.duration / video_clip.duration)
                        video_clip = concatenate_videoclips([video_clip] * num_loops)
                    
                    # 최종 음성 길이만큼만 영상 자르기
                    video_clip = video_clip.subclip(0, audio_clip.duration)
                    video_clip = video_clip.set_audio(audio_clip)
                    
                    # 3. MP4 파일로 최종 저장
                    video_clip.write_videofile(
                        output_path, 
                        fps=24, 
                        codec="libx264", 
                        audio_codec="aac",
                        logger=None
                    )
                    
                    st.success(f"🎉 '{topic}' 움직이는 영상 완성! (아래에서 재생 및 다운로드 가능)")
                    st.video(output_path)
                    
                    with open(output_path, "rb") as v_file:
                        st.download_button(
                            label=f"💾 '{topic}' 움직이는 MP4 다운로드",
                            data=v_file,
                            file_name=f"{topic}.mp4",
                            mime="video/mp4",
                            key=f"dl_{index}"
                        )
                        
                except Exception as e:
                    st.error(f"에러 발생: {e}")
                
                progress_bar.progress((index + 1) / len(df4))
                
            status_text.success("✅ 모든 비디오 변환이 완료되었습니다!")
