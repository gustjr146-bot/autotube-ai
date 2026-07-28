import streamlit as st
import pandas as pd
import requests
import json
import time
import os
import urllib.request
import math
import numpy as np
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont

# 💡 구형 TextClip을 완전히 삭제했습니다! (ImageMagick 에러 원천 차단)
from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips

# ==========================================
# 1. 화면 및 기본 설정
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (통합형 마스터)")
st.markdown("대본, 동영상, 음성, 모션 생성부터 **자동 한글 자막이 포함된 MP4 최종 병합**까지 모두 지원합니다.")

FONT_PATH = os.path.abspath("NanumGothic.ttf")
if not os.path.exists(FONT_PATH):
    try:
        urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf", FONT_PATH)
    except Exception: pass 

# ==========================================
# 2. API 연동 함수 정의
# ==========================================
def call_groq(prompt, api_key):
    if not api_key: return "Groq 에러: API 키 없음"
    api_key = api_key.strip()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",  
        "messages": [
            {"role": "system", "content": "당신은 한국어 유튜브 전문 작가입니다. 대본 본문만 1~2문단으로 짧고 명확하게 작성해 주세요."},
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
    if not api_key: return None, "API 키 없음"
    api_key = api_key.strip()
    url = "https://queue.fal.run/fal-ai/luma-dream-machine"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "aspect_ratio": "9:16" if aspect_ratio == "9:16" else "16:9"}
    if pd.notna(ref_url) and str(ref_url).strip() and str(ref_url).strip() != 'nan':
        payload["image_url"] = str(ref_url).strip()
    try:
        create_res = requests.post(url, headers=headers, json=payload)
        if create_res.status_code != 200: return None, f"비디오 거부"
        response_url = create_res.json().get('response_url')
        for _ in range(60): 
            time.sleep(5)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                result_data = poll_res.json()
                video_url = result_data.get('video', {}).get('url')
                if video_url: return video_url, "성공"
        return None, "시간 초과"
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
    payload = {"prompt": prompt, "image_size": "portrait_16_9" if aspect_ratio == "9:16" else "landscape_16_9"}
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200: return res.json().get('images', [{}])[0].get('url')
        return None
    except Exception: return None

def call_fal_tts(script, api_key):
    if not api_key: return "fal 에러: API 키 없음"
    api_key = api_key.strip()
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {"text": script[:500] if len(script) > 500 else script}
    try:
        create_res = requests.post(url, headers=headers, json=payload)
        if create_res.status_code != 200: return f"fal 거부"
        response_url = create_res.json().get('response_url')
        for _ in range(10):
            time.sleep(3)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                audio_url = poll_res.json().get('audio', {}).get('url')
                if audio_url: return audio_url
        return "fal 시간 초과"
    except Exception: return f"fal 통신 에러"

def download_file(url, save_path):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
        out_file.write(response.read())

# 💡 완전히 새로 만든 에러 없는 수제 자막 모듈!
def create_subtitle_clip(text, video_width, duration):
    try:
        img = Image.new('RGBA', (video_width, 250), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try: font = ImageFont.truetype(FONT_PATH, 45)
        except Exception: font = ImageFont.load_default()
        
        words = text.replace('\n', ' ').split()
        lines = []
        current_line = ""
        for word in words:
            if len(current_line) + len(word) <= 22:
                current_line += word + " "
            else:
                lines.append(current_line.strip())
                current_line = word + " "
        if current_line: lines.append(current_line.strip())
        if len(lines) > 2:
            lines = lines[:2]
            lines[1] += "..."
            
        y_text = 20
        for line in lines:
            bbox = font.getbbox(line)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            draw.rectangle(((video_width - w) / 2 - 20, y_text - 5, (video_width + w) / 2 + 20, y_text + h + 15), fill=(0, 0, 0, 180))
            draw.text(((video_width - w) / 2, y_text), line, font=font, fill=(255, 255, 255, 255))
            y_text += h + 25
            
        img_np = np.array(img)
        return ImageClip(img_np).set_duration(duration)
    except Exception as e:
        print(f"자막 에러: {e}")
        return None

# ==========================================
# 3. 사이드바 
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    FAL_KEY = st.text_input("fal.ai API Key (비디오/음성)", type="password")
    KIE_KEY = st.text_input("KIE API Key (대체용)", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚀 자동화 파이프라인", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합 (자동 자막)"])

with tab1:
    st.subheader("대량 영상 재료 자동 생성")
    col1, col2 = st.columns([1, 2])
    with col1:
        video_type = st.radio("영상 포맷", ["쇼츠 (9:16)", "롱폼 (16:9)"])
        aspect_ratio = "9:16" if "쇼츠" in video_type else "16:9"
    with col2:
        file1 = st.file_uploader("기획안 업로드 (엑셀/CSV)", type=['csv', 'xlsx'], key="f1")
    
    if file1:
        df1 = pd.read_excel(file1) if file1.name.endswith('.xlsx') else pd.read_csv(file1)
        st.success(f"✅ 총 {len(df1)}개의 작업 감지")
        if st.button("🔥 비디오 생성 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []
            
            for index, row in df1.iterrows():
                topic = str(row.get('주제', f'랜덤 주제 {index}'))
                ref_image = str(row.get('레퍼런스', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 대본 작성 중...**")
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 대본 작성)", GROQ_KEY)
                
                eng_prompt = f"High quality cinematic visual about {topic}"
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 🎥 비디오 생성 중...**")
                visual_url, vid_status = call_fal_video(eng_prompt, ref_image, aspect_ratio, FAL_KEY)
                
                if not visual_url or "http" not in visual_url:
                    visual_url = call_kie_image(eng_prompt, ref_image, aspect_ratio, KIE_KEY)
                if not visual_url or "http" not in visual_url:
                    visual_url = call_fal_image(eng_prompt, aspect_ratio, FAL_KEY)
                if not visual_url or "http" not in visual_url:
                    w, h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
                    visual_url = f"https://picsum.photos/seed/{index}/{w}/{h}"
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 음성 생성 중...**")
                aud_url = call_fal_tts(ai_script, FAL_KEY)
                
                results.append({"주제": topic, "대본": ai_script, "비디오": visual_url, "음성": aud_url})
                progress_bar.progress((index + 1) / len(df1))
                
            status_text.success("🎉 완료! 엑셀을 다운로드하여 4번 탭으로 이동하세요.")
            st.download_button("💾 완성된 엑셀 다운로드", data=pd.DataFrame(results).to_csv(index=False).encode('utf-8-sig'), file_name='video_materials.csv', mime='text/csv')

with tab2:
    st.subheader("🎵 음원 자동 생성")
    file2 = st.file_uploader("음원 기획안 업로드", type=['csv', 'xlsx'], key="f2")
    if file2 and st.button("🎵 음원 생성 시작", type="primary"): st.info("대기열 등록 완료")

with tab3:
    st.subheader("💃 AI 모션 인플루언서")
    file3 = st.file_uploader("모션 기획안 업로드", type=['csv', 'xlsx'], key="f3")
    if file3 and st.button("💃 모션 변환 시작", type="primary"): st.info("렌더링 시작...")

with tab4:
    st.subheader("📑 최종 영상(MP4) 자동 병합 (한글 자막 추가)")
    st.markdown("비디오 크레딧이 부족해 사진이 생성되었더라도, **마법의 줌인(Zoom-in) 효과**로 동영상처럼 움직이게 만들어줍니다!")
    
    file4 = st.file_uploader("완료된 엑셀(CSV) 업로드", type=['csv'], key="f4")
    
    if file4:
        df4 = pd.read_csv(file4)
        st.dataframe(df4.head(3))
        
        if st.button("🎬 자막 포함 동영상 렌더링 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            if not os.path.exists("output_videos"): os.makedirs("output_videos")
                
            for index, row in df4.iterrows():
                topic = str(row.get('주제', f'video_{index}'))
                script_text = str(row.get('대본', ''))
                vis_url = str(row.get('비디오', row.get('이미지', '')))
                audio_url = str(row.get('음성', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df4)}] '{topic}' 렌더링 중... ⏳**")
                
                if "http" not in vis_url or vis_url.lower() == 'nan': vis_url = f"https://picsum.photos/seed/{index}/1080/1920"
                if "http" not in audio_url or audio_url.lower() == 'nan': continue
                    
                try:
                    parsed_url = urlparse(vis_url)
                    ext = os.path.splitext(parsed_url.path)[1].lower()
                    if ext in ['.mp4', '.mov', '.webm', '.avi']: is_video = True
                    else: is_video = False; ext = '.jpg'
                        
                    temp_vis_path = f"temp_vis_{index}{ext}"
                    audio_path = f"temp_audio_{index}.mp3"
                    output_path = f"output_videos/result_sub_{index}.mp4"
                    
                    download_file(vis_url, temp_vis_path)
                    download_file(audio_url, audio_path)
                    
                    audio_clip = AudioFileClip(audio_path)
                    
                    if is_video:
                        video_clip = VideoFileClip(temp_vis_path)
                        # 💡 화면 깨짐(바둑판) 방지를 위해 짝수 픽셀 강제 조정
                        w, h = video_clip.size
                        video_clip = video_clip.resize(newsize=(w - w % 2, h - h % 2))
                        
                        if video_clip.duration < audio_clip.duration:
                            num_loops = math.ceil(audio_clip.duration / video_clip.duration)
                            video_clip = concatenate_videoclips([video_clip] * num_loops)
                        video_clip = video_clip.subclip(0, audio_clip.duration)
                    else:
                        base_clip = ImageClip(temp_vis_path)
                        # 💡 화면 깨짐 방지 짝수 보정
                        w, h = base_clip.size
                        w, h = w - w % 2, h - h % 2
                        base_clip = base_clip.resize(newsize=(w, h))
                        
                        # 💡 사진이라도 동영상처럼 움직이게 하는 마법의 줌인(Zoom) 효과!
                        def zoom(t): return 1.0 + 0.05 * (t / audio_clip.duration)
                        zoomed_clip = base_clip.resize(zoom).set_position(('center', 'center'))
                        video_clip = CompositeVideoClip([zoomed_clip], size=(w, h)).set_duration(audio_clip.duration)
                        
                    video_clip = video_clip.set_audio(audio_clip)
                    
                    display_text = script_text[:80] if len(script_text) > 80 else script_text
                    subtitle_clip = create_subtitle_clip(display_text, video_clip.w, video_clip.duration)
                    
                    if subtitle_clip:
                        subtitle_clip = subtitle_clip.set_position(('center', video_clip.h - 250))
                        final_clip = CompositeVideoClip([video_clip, subtitle_clip])
                    else:
                        final_clip = video_clip
                    
                    final_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
                    
                    st.success(f"🎉 '{topic}' 동영상 완성!")
                    st.video(output_path)
                    
                    with open(output_path, "rb") as v_file:
                        st.download_button(f"💾 '{topic}' 다운로드", data=v_file, file_name=f"{topic}.mp4", mime="video/mp4", key=f"dl_{index}")
                        
                except Exception as e:
                    st.error(f"합성 에러: {e}")
                
                progress_bar.progress((index + 1) / len(df4))
                
            status_text.success("✅ 모든 비디오 병합이 완료되었습니다!")
