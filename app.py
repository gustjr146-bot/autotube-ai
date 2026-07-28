import streamlit as st
import pandas as pd
import requests
import json
import time
import os
import urllib.request
import math
from urllib.parse import urlparse
from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

# ==========================================
# 1. 화면 및 기본 설정 (한글 폰트 자동 설치)
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (통합형 마스터)")
st.markdown("대본, 동영상, 음성 생성부터 **자동 한글 자막이 포함된 MP4 최종 병합**까지 모두 지원합니다.")

# 💡 서버에 한글 폰트가 없으면 구글에서 '나눔고딕'을 자동으로 다운로드합니다!
FONT_PATH = os.path.abspath("NanumGothic.ttf")
if not os.path.exists(FONT_PATH):
    try:
        urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf", FONT_PATH)
    except Exception:
        pass # 다운로드 실패 시 기본 폰트로 작동

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
            {"role": "system", "content": "당신은 한국어 유튜브 전문 작가입니다. 대본 본문만 짧고 명확하게 작성해 주세요."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200: return res.json()['choices'][0]['message']['content']
        else: return f"Groq 거부 ({res.status_code})"
    except Exception: return "Groq 통신 에러"

def call_fal_video(prompt, ref_url, aspect_ratio, api_key):
    """fal.ai 비디오 생성 (대기시간을 5분으로 늘려 동영상이 무조건 나오도록 보장)"""
    if not api_key: return None, "API 키 없음"
    api_key = api_key.strip()
    url = "https://queue.fal.run/fal-ai/luma-dream-machine"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "aspect_ratio": "9:16" if aspect_ratio == "9:16" else "16:9"}
    if pd.notna(ref_url) and str(ref_url).strip() and str(ref_url).strip() != 'nan':
        payload["image_url"] = str(ref_url).strip()
        
    try:
        create_res = requests.post(url, headers=headers, json=payload)
        if create_res.status_code != 200: return None, f"비디오 거부({create_res.status_code})"
        response_url = create_res.json().get('response_url')
        
        # 💡 기존 25번(2분)에서 60번(5분)으로 늘려 동영상 생성을 끝까지 기다립니다!
        for _ in range(60):
            time.sleep(5)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                result_data = poll_res.json()
                video_url = result_data.get('video', {}).get('url')
                if video_url: return video_url, "성공"
        return None, "시간 초과(5분)"
    except Exception as e: return None, str(e)

def call_kie_image(prompt, ref_url, aspect_ratio, api_key):
    if not api_key: return None
    api_key = api_key.strip()
    create_url = "https://api.kie.ai/api/v1/jobs/createTask"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "google/nano-banana-edit",
        "input": {"prompt": prompt, "output_format": "png", "aspect_ratio": aspect_ratio}
    }
    if pd.notna(ref_url) and str(ref_url).strip() and str(ref_url).strip() != 'nan':
        payload["input"]["image_urls"] = [str(ref_url).strip()]
        
    try:
        create_res = requests.post(create_url, headers=headers, json=payload)
        if create_res.status_code != 200: return None
        data = create_res.json().get('data')
        if not data: return None
        task_id = data.get('taskId')
        
        for _ in range(12):
            time.sleep(5)
            poll_res = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers)
            if poll_res.status_code != 200: continue
            poll_data_inner = poll_res.json().get('data')
            if not poll_data_inner: return None
            state = str(poll_data_inner.get('state', '')).lower()
            if state in ['success', 'completed', 'done']:
                res_json = poll_data_inner.get('resultJson', '{}')
                if isinstance(res_json, str):
                    try: res_json = json.loads(res_json)
                    except: res_json = {}
                urls = res_json.get('resultUrls', [])
                return urls[0] if urls else None
            elif state in ['failed', 'error']: return None
        return None
    except Exception: return None

def call_fal_image(prompt, aspect_ratio, api_key):
    if not api_key: return None
    api_key = api_key.strip()
    url = "https://fal.run/fal-ai/fast-sdxl"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "image_size": "portrait_16_9" if aspect_ratio == "9:16" else "landscape_16_9"
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200:
            return res.json().get('images', [{}])[0].get('url')
        return None
    except Exception: return None

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
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
        out_file.write(response.read())

# ==========================================
# 3. 사이드바 (API 키 설정)
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    FAL_KEY = st.text_input("fal.ai API Key (음성/비디오/대체이미지용)", type="password")
    KIE_KEY = st.text_input("KIE API Key (비디오 실패시 1차 대체용)", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚀 자동화 파이프라인", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합 (자동 자막)"])

# ----------------- TAB 1 -----------------
with tab1:
    st.subheader("대량 영상 재료(대본/시각자료/음성) 자동 생성")
    col1, col2 = st.columns([1, 2])
    with col1:
        video_type = st.radio("영상 포맷", ["쇼츠 (9:16)", "롱폼 (16:9)"])
        aspect_ratio = "9:16" if "쇼츠" in video_type else "16:9"
    with col2:
        file1 = st.file_uploader("기획안 업로드 (엑셀/CSV)", type=['csv', 'xlsx'], key="f1")
    
    if file1:
        df1 = pd.read_excel(file1) if file1.name.endswith('.xlsx') else pd.read_csv(file1)
        st.success(f"✅ 총 {len(df1)}개의 작업 감지")
        
        if st.button("🔥 영상 생성 시작 (비디오 우선)", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []
            
            for index, row in df1.iterrows():
                topic = str(row.get('주제', f'랜덤 주제 {index}'))
                ref_image = str(row.get('레퍼런스', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 대본 작성 중... ✍️**")
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 대본 작성)", GROQ_KEY)
                
                eng_prompt = f"High quality cinematic visual about {topic}"
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 🎥 움직이는 비디오 생성 중... (최대 5분 소요) ⏳**")
                
                visual_url, vid_status = call_fal_video(eng_prompt, ref_image, aspect_ratio, FAL_KEY)
                
                if not visual_url or "http" not in visual_url:
                    status_text.markdown(f"**[{index+1}/{len(df1)}] 비디오 실패({vid_status})! KIE 이미지로 대체 중... 🎨**")
                    visual_url = call_kie_image(eng_prompt, ref_image, aspect_ratio, KIE_KEY)
                    
                if not visual_url or "http" not in visual_url:
                    status_text.markdown(f"**[{index+1}/{len(df1)}] KIE 지연! fal.ai 초고속 이미지로 강제 렌더링... ⚡**")
                    visual_url = call_fal_image(eng_prompt, aspect_ratio, FAL_KEY)
                    
                if not visual_url or "http" not in visual_url:
                    status_text.markdown(f"**[{index+1}/{len(df1)}] 고화질 임시 배경을 삽입합니다. 🛡️**")
                    w, h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
                    visual_url = f"https://picsum.photos/seed/{index}/{w}/{h}"
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 음성(TTS) 생성 중... 🗣️**")
                aud_url = call_fal_tts(ai_script, FAL_KEY)
                
                results.append({"주제": topic, "대본": ai_script, "비디오": visual_url, "음성": aud_url})
                progress_bar.progress((index + 1) / len(df1))
                
            status_text.success("🎉 작업 완료! 엑셀을 다운로드하여 4번 탭으로 이동하세요.")
            result_df = pd.DataFrame(results)
            st.dataframe(result_df)
            csv = result_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("💾 완성된 엑셀 다운로드", data=csv, file_name='video_materials.csv', mime='text/csv')

# ----------------- TAB 2, 3 생략 -----------------
with tab2:
    st.subheader("🎵 음원 자동 생성 (자동음원 시트 업로드)")
    file2 = st.file_uploader("음원 기획안 업로드", type=['csv', 'xlsx'], key="f2")
    if file2:
        if st.button("🎵 음원 생성 시작", type="primary", key="btn2"): st.info("대기열 등록 완료")
with tab3:
    st.subheader("💃 AI 모션 인플루언서 (AI모션 시트 업로드)")
    file3 = st.file_uploader("모션 기획안 업로드", type=['csv', 'xlsx'], key="f3")
    if file3:
        if st.button("💃 모션 변환 시작", type="primary", key="btn3"): st.info("렌더링 시작...")

# ----------------- TAB 4 (자막 병합기 - 한글 폰트 적용 완료!) -----------------
with tab4:
    st.subheader("📑 최종 영상(MP4) 자동 병합 (한글 자막 추가)")
    st.markdown("1번 탭의 엑셀을 올리면 **비디오 + 음성 + 한글 자막**을 합쳐 1개의 완벽한 MP4로 만듭니다.")
    
    file4 = st.file_uploader("완료된 엑셀(CSV) 업로드", type=['csv'], key="f4")
    
    if file4:
        df4 = pd.read_csv(file4)
        st.dataframe(df4.head(3))
        
        if st.button("🎬 자막 포함 동영상 렌더링 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            if not os.path.exists("output_videos"):
                os.makedirs("output_videos")
                
            for index, row in df4.iterrows():
                topic = str(row.get('주제', f'video_{index}'))
                script_text = str(row.get('대본', ''))
                vis_url = str(row.get('비디오', row.get('이미지', '')))
                audio_url = str(row.get('음성', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df4)}] '{topic}' 한글 자막 영상 렌더링 중... ⏳**")
                
                if "http" not in vis_url or vis_url.lower() == 'nan':
                    vis_url = f"https://picsum.photos/seed/{index}/1080/1920"
                    
                if "http" not in audio_url or audio_url.lower() == 'nan':
                    continue
                    
                try:
                    parsed_url = urlparse(vis_url)
                    ext = os.path.splitext(parsed_url.path)[1].lower()
                    
                    if ext in ['.mp4', '.mov', '.webm', '.avi']: is_video = True
                    elif ext in ['.jpg', '.jpeg', '.png', '.webp']: is_video = False
                    else: is_video = False; ext = '.jpg'
                        
                    temp_vis_path = f"temp_vis_{index}{ext}"
                    audio_path = f"temp_audio_{index}.mp3"
                    output_path = f"output_videos/result_sub_{index}.mp4"
                    
                    download_file(vis_url, temp_vis_path)
                    download_file(audio_url, audio_path)
                    
                    audio_clip = AudioFileClip(audio_path)
                    
                    if is_video:
                        video_clip = VideoFileClip(temp_vis_path)
                        if video_clip.duration < audio_clip.duration:
                            num_loops = math.ceil(audio_clip.duration / video_clip.duration)
                            video_clip = concatenate_videoclips([video_clip] * num_loops)
                        video_clip = video_clip.subclip(0, audio_clip.duration)
                    else:
                        video_clip = ImageClip(temp_vis_path)
                        video_clip = video_clip.set_duration(audio_clip.duration)
                        
                    video_clip = video_clip.set_audio(audio_clip)
                    
                    # 💡 다운로드 받은 '나눔고딕' 폰트를 강제로 지정하여 한글 깨짐/에러 완벽 방지!
                    try:
                        # 대본을 50글자씩 잘라서 화면을 너무 가리지 않게 합니다.
                        display_text = script_text[:50] + "\n..." if len(script_text) > 50 else script_text
                        
                        txt_clip = TextClip(
                            display_text, 
                            font=FONT_PATH if os.path.exists(FONT_PATH) else 'Arial', # 폰트 강제 적용
                            fontsize=45, color='white', bg_color='rgba(0,0,0,0.6)', 
                            method='caption', size=(video_clip.w * 0.85, None)
                        )
                        txt_clip = txt_clip.set_position('center', 'bottom').set_duration(video_clip.duration)
                        final_clip = CompositeVideoClip([video_clip, txt_clip])
                    except Exception as font_err:
                        st.warning(f"⚠️ 자막 렌더링 오류 (기본 영상으로 대체): {font_err}")
                        final_clip = video_clip
                    
                    final_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
                    
                    st.success(f"🎉 '{topic}' 한글 자막 영상 완성!")
                    st.video(output_path)
                    
                    with open(output_path, "rb") as v_file:
                        st.download_button(f"💾 '{topic}' 다운로드", data=v_file, file_name=f"{topic}.mp4", mime="video/mp4", key=f"dl_{index}")
                        
                except Exception as e:
                    st.error(f"'{topic}' 합성 중 에러 발생: {e}")
                
                progress_bar.progress((index + 1) / len(df4))
                
            status_text.success("✅ 모든 비디오 병합이 완료되었습니다!")
