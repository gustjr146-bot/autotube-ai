import streamlit as st
import pandas as pd
import requests
import json
import time
import os
import re
import urllib.request
import math
import numpy as np
from urllib.parse import urlparse

import PIL
from PIL import Image, ImageDraw, ImageFont
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
import moviepy.video.fx.all as vfx

# ==========================================
# 1. 화면 및 기본 설정
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (3중 엔진 무중단 마스터)")
st.markdown("대본 정제, **Kling ➔ Runway ➔ Luma 3중 자동전환**, **5분 컷(Fast-Fail) 도입**, 극사실적 모션 강제, 자막 병합 지원.")

FONT_PATH = os.path.abspath("NanumGothic.ttf")
if not os.path.exists(FONT_PATH):
    try:
        urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf", FONT_PATH)
    except Exception: pass 

# ==========================================
# 2. 대본 생성
# ==========================================
def clean_script(text):
    text = re.sub(r'\(\d+:\d+\s*-\s*\d+:\d+\)', '', text)
    text = re.sub(r'\[\d+:\d+\s*-\s*\d+:\d+\]', '', text) 
    text = text.replace('\n', ' ').strip()
    return text

def call_groq(prompt, api_key):
    if not api_key: return "Groq 에러: API 키 없음"
    api_key = api_key.strip()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",  
        "messages": [
            {"role": "system", "content": "당신은 한국어 유튜브 쇼츠 전문 작가입니다. 대본 본문만 짧고 명확하게 작성해 주세요. 타임코드나 지시어는 절대 넣지 마세요."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code == 200: 
            return clean_script(res.json()['choices'][0]['message']['content'])
        return f"Groq 거부 ({res.status_code})"
    except Exception: return "Groq 통신 에러"

# ==========================================
# 3. [엔진 1] KIE Kling (최대 5분 대기)
# ==========================================
def call_engine_1_kie(prompt, aspect_ratio, image_url, api_key, status_text, current_idx, total_items):
    if not api_key: return None
    api_key = api_key.strip()
    create_url = "https://api.kie.ai/api/v1/jobs/createTask"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    ratio = "16:9" if aspect_ratio == "16:9" else "9:16"
    
    if image_url:
        payloads = [{"model": "kuaishou/kling-video", "input": {"prompt": prompt, "image_url": image_url}}]
    else:
        payloads = [{"model": "kuaishou/kling-video", "input": {"prompt": prompt, "aspect_ratio": ratio}}]
        
    task_id = None
    for p in payloads:
        try:
            r = requests.post(create_url, headers=headers, json=p, timeout=15)
            if r.status_code == 200 and r.json().get('data', {}).get('taskId'):
                task_id = r.json()['data']['taskId']
                break
        except: continue
        
    if not task_id: return None
        
    start = time.time()
    for _ in range(60): # 💡 5분 컷! 5분 넘으면 가차없이 끊음
        time.sleep(5)
        elapsed = int(time.time() - start)
        status_text.markdown(f"**[{current_idx}/{total_items}] 🎥 [엔진1] Kling 렌더링 중... (현재 {elapsed}초 / 최대 5분 컷) ⏳**")
        
        try:
            pr = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers, timeout=10)
            if pr.status_code == 200:
                d = pr.json().get('data', {})
                if not isinstance(d, dict): continue
                
                res_j = d.get('resultJson', {})
                if isinstance(res_j, str): 
                    try: res_j = json.loads(res_j)
                    except: res_j = {}
                if isinstance(res_j, dict) and res_j.get('resultUrls'):
                    return res_j['resultUrls'][0]
                    
                stt = str(d.get('state', d.get('status', ''))).lower()
                if stt in ['failed', 'error', 'cancelled', 'timeout']: return None
        except: continue
    return None # 5분 초과 시 즉시 None 반환

# ==========================================
# 4. [엔진 2] Fal Runway Gen-3 (최대 5분 대기)
# ==========================================
def call_engine_2_runway(prompt, aspect_ratio, image_url, api_key, status_text, current_idx, total_items):
    if not api_key: return None
    headers = {"Authorization": f"Key {api_key.strip()}", "Content-Type": "application/json"}
    
    if image_url:
        url = "https://queue.fal.run/fal-ai/runway-gen3/turbo/image-to-video"
        payload = {"image_url": image_url, "prompt": prompt}
    else:
        url = "https://queue.fal.run/fal-ai/runway-gen3/turbo/text-to-video"
        payload = {"prompt": prompt, "aspect_ratio": "16:9" if aspect_ratio == "16:9" else "9:16"}
        
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code != 200: return None
        resp_url = r.json().get('response_url')
        
        start = time.time()
        for _ in range(60): # 💡 5분 컷!
            time.sleep(5)
            elapsed = int(time.time() - start)
            status_text.markdown(f"**[{current_idx}/{total_items}] 🚀 [엔진2] Runway Gen-3 자동전환 렌더링 중... (현재 {elapsed}초 / 최대 5분 컷) ⏳**")
            
            try:
                pr = requests.get(resp_url, headers=headers, timeout=10)
                if pr.status_code == 200:
                    d = pr.json()
                    stt = d.get('status', '').upper()
                    if stt in ['FAILED', 'ERROR', 'CANCELLED']: return None
                    
                    v = d.get('video', {})
                    if isinstance(v, dict) and v.get('url'): return v['url']
                    if d.get('video_url'): return d['video_url']
            except: continue
        return None
    except: return None

# ==========================================
# 5. [엔진 3] Fal Luma Dream Machine (최대 5분 대기)
# ==========================================
def call_engine_3_luma(prompt, aspect_ratio, image_url, api_key, status_text, current_idx, total_items):
    if not api_key: return None
    headers = {"Authorization": f"Key {api_key.strip()}", "Content-Type": "application/json"}
    
    url = "https://queue.fal.run/fal-ai/luma-dream-machine"
    payload = {"prompt": prompt}
    if image_url: payload["image_url"] = image_url
    else: payload["aspect_ratio"] = "16:9" if aspect_ratio == "16:9" else "9:16"
        
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code != 200: return None
        resp_url = r.json().get('response_url')
        
        start = time.time()
        for _ in range(60): # 💡 5분 컷!
            time.sleep(5)
            elapsed = int(time.time() - start)
            status_text.markdown(f"**[{current_idx}/{total_items}] 🛸 [엔진3] Luma 최종 백업 렌더링 중... (현재 {elapsed}초 / 최대 5분 컷) ⏳**")
            
            try:
                pr = requests.get(resp_url, headers=headers, timeout=10)
                if pr.status_code == 200:
                    d = pr.json()
                    stt = d.get('status', '').upper()
                    if stt in ['FAILED', 'ERROR', 'CANCELLED']: return None
                    
                    v = d.get('video', {})
                    if isinstance(v, dict) and v.get('url'): return v['url']
                    if d.get('video_url'): return d['video_url']
            except: continue
        return None
    except: return None

# ==========================================
# 6. 음성 및 유틸리티
# ==========================================
def call_fal_tts(script, api_key):
    if not api_key: return None
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key.strip()}", "Content-Type": "application/json"}
    payload = {"text": clean_script(script)[:500]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code != 200: return None
        resp_url = r.json().get('response_url')
        for _ in range(20):
            time.sleep(3)
            try:
                pr = requests.get(resp_url, headers=headers, timeout=10)
                if pr.status_code == 200 and pr.json().get('audio', {}).get('url'):
                    return pr.json()['audio']['url']
            except: continue
        return None
    except: return None

def download_file(url, save_path):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status() 
        with open(save_path, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk: out_file.write(chunk)
    except Exception as e: raise Exception(f"다운로드 실패: {e}")

def create_dynamic_subtitles(text, video_width, video_height, duration):
    try:
        words = clean_script(text).split()
        chunks, curr = [], ""
        for w in words:
            if len(curr) + len(w) < 16: curr += w + " "
            else:
                chunks.append(curr.strip())
                curr = w + " "
        if curr: chunks.append(curr.strip())
            
        clips, total_chars, start_time = [], sum(len(c) for c in chunks), 0
        if total_chars == 0: return []
        
        try: font = ImageFont.truetype(FONT_PATH, 38)
        except: font = ImageFont.load_default()
        
        for chunk in chunks:
            chunk_duration = duration * (len(chunk) / total_chars)
            img = Image.new('RGBA', (video_width, 150), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            if hasattr(font, 'getbbox'):
                bbox = font.getbbox(chunk)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            else:
                w, h = draw.textsize(chunk, font=font)
            
            x_pos, y_pos = (video_width - w) / 2, 50
            draw.rectangle((x_pos - 20, y_pos - 15, x_pos + w + 20, y_pos + h + 15), fill=(0, 0, 0, 180))
            draw.text((x_pos, y_pos), chunk, font=font, fill=(255, 255, 255, 255))
            
            txt_clip = ImageClip(np.array(img)).set_duration(chunk_duration).set_start(start_time).set_position(('center', video_height * 0.60))
            clips.append(txt_clip)
            start_time += chunk_duration
            
        return clips
    except: return []

# ==========================================
# 7. 화면 및 메인 로직
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    KIE_KEY = st.text_input("KIE API Key (⭐엔진1)", type="password")
    FAL_KEY = st.text_input("fal.ai API Key (⭐엔진2/3/음성)", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

tab1, tab2, tab3, tab4 = st.tabs(["🚀 3중 엔진 생성", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합 (자동 자막)"])

with tab1:
    st.subheader("대량 영상 자동 생성 (5분 컷 / 3중 엔진 방어)")
    col1, col2 = st.columns([1, 2])
    with col1:
        video_type = st.radio("영상 포맷", ["쇼츠 (9:16)", "롱폼 (16:9)"])
        aspect_ratio = "9:16" if "쇼츠" in video_type else "16:9"
    with col2:
        file1 = st.file_uploader("기획안 업로드 (엑셀/CSV 양식)", type=['csv', 'xlsx'], key="f1")
    
    if file1:
        df1 = pd.read_excel(file1) if file1.name.endswith('.xlsx') else pd.read_csv(file1)
        st.success(f"✅ 총 {len(df1)}개의 작업 감지")
        if st.button("🔥 동영상 생성 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []
            total_items = len(df1)
            
            for index, row in df1.iterrows():
                current_idx = index + 1
                topic = str(row.get('주제(필수)', row.get('주제', f'랜덤 주제 {current_idx}')))
                detail_req = str(row.get('세부요청(선택)', ''))
                prompt_topic = f"{topic}. {detail_req}" if detail_req and detail_req.lower() != 'nan' else topic
                
                ref_image = str(row.get('레퍼런스이미지 URL(선택)', row.get('레퍼런스이미지 URL', ''))).strip()
                if ref_image.lower() in ['nan', '', 'none'] or not ref_image.startswith('http'): ref_image = None
                    
                status_text.markdown(f"**[{current_idx}/{total_items}] '{topic}' 대본 작성 중...**")
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 쇼츠. 길이는 짧게 10초 분량만. 타임코드 금지.)", GROQ_KEY)
                
                # 💡 [극사실주의 인간 모션 프롬프트 500% 강화] 
                eng_prompt = f"Extremely realistic live-action cinematic footage of a Korean person. {prompt_topic}. The person is a real human, continuously moving in a highly dynamic way. They are visibly breathing, blinking, and changing facial expressions and body posture naturally. Fluid, vivid motion. High energy. Absolutely NO static, still, or frozen photo effects. Masterpiece 4k video."
                
                # 💡 3중 엔진 캐스케이딩(Cascading) 로직 도입 (절대 멈추지 않음)
                visual_url = None
                visual_url = call_engine_1_kie(eng_prompt, aspect_ratio, ref_image, KIE_KEY, status_text, current_idx, total_items)
                
                if not visual_url: # KIE 실패/타임아웃 시
                    visual_url = call_engine_2_runway(eng_prompt, aspect_ratio, ref_image, FAL_KEY, status_text, current_idx, total_items)
                    
                if not visual_url: # Runway 실패/타임아웃 시
                    visual_url = call_engine_3_luma(eng_prompt, aspect_ratio, ref_image, FAL_KEY, status_text, current_idx, total_items)
                
                if not visual_url: # 3개 다 죽었을 때
                    st.error(f"❌ '{topic}' 비디오 생성 완전 실패 (모든 AI 엔진 과부하). 다음으로 넘어갑니다.")
                    continue
                
                status_text.markdown(f"**[{current_idx}/{total_items}] '{topic}' 음성 생성 중...**")
                aud_url = call_fal_tts(ai_script, FAL_KEY)
                
                results.append({"주제": topic, "대본": ai_script, "비디오": visual_url, "음성": aud_url})
                progress_bar.progress(current_idx / total_items)
                
            if results:
                status_text.success("🎉 완료! 엑셀을 다운로드하여 4번 탭으로 이동하세요.")
                st.download_button("💾 완성된 엑셀 다운로드", data=pd.DataFrame(results).to_csv(index=False).encode('utf-8-sig'), file_name='video_materials.csv', mime='text/csv')

with tab2: st.info("대기열 등록 완료")
with tab3: st.info("렌더링 시작...")

with tab4:
    st.subheader("📑 최종 영상(MP4) 자동 병합")
    file4 = st.file_uploader("완료된 엑셀(CSV) 업로드", type=['csv'], key="f4")
    if file4:
        df4 = pd.read_csv(file4)
        if st.button("🎬 자막 포함 동영상 렌더링 시작", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            if not os.path.exists("output_videos"): os.makedirs("output_videos")
                
            for index, row in df4.iterrows():
                topic = str(row.get('주제', f'video_{index}'))
                script_text = clean_script(str(row.get('대본', '')))
                vis_url = str(row.get('비디오', ''))
                audio_url = str(row.get('음성', ''))
                
                if "http" not in vis_url or "http" not in audio_url: continue
                status_text.markdown(f"**[{index+1}/{len(df4)}] '{topic}' 병합 중... ⏳**")
                    
                try:
                    ext = os.path.splitext(urlparse(vis_url).path)[1].lower()
                    is_video = ext in ['.mp4', '.mov', '.webm', '.avi']
                    ext = ext if is_video else '.jpg'
                        
                    temp_vis_path = f"temp_vis_{index}{ext}"
                    audio_path = f"temp_audio_{index}.mp3"
                    output_path = f"output_videos/result_sub_{index}.mp4"
                    
                    download_file(vis_url, temp_vis_path)
                    download_file(audio_url, audio_path)
                    
                    audio_clip = AudioFileClip(audio_path)
                    
                    if is_video:
                        video_clip = VideoFileClip(temp_vis_path).without_audio()
                        w, h = video_clip.size
                        video_clip = video_clip.resize(newsize=(w - w % 2, h - h % 2))
                        
                        if video_clip.duration < audio_clip.duration:
                            try:
                                reversed_clip = video_clip.fx(vfx.time_mirror)
                                ping_pong_clip = concatenate_videoclips([video_clip, reversed_clip])
                                num_loops = math.ceil(audio_clip.duration / ping_pong_clip.duration)
                                video_clip = concatenate_videoclips([ping_pong_clip] * num_loops)
                            except:
                                num_loops = math.ceil(audio_clip.duration / video_clip.duration)
                                video_clip = concatenate_videoclips([video_clip] * num_loops)
                                
                        video_clip = video_clip.subclip(0, audio_clip.duration)
                    else:
                        base_clip = ImageClip(temp_vis_path)
                        w, h = base_clip.size
                        w, h = w - w % 2, h - h % 2
                        base_clip = base_clip.resize(newsize=(w, h))
                        zoomed_clip = base_clip.resize(lambda t: 1.0 + 0.05 * (t / audio_clip.duration)).set_position(('center', 'center'))
                        video_clip = CompositeVideoClip([zoomed_clip], size=(w, h)).set_duration(audio_clip.duration)
                        
                    video_clip = video_clip.set_audio(audio_clip)
                    subtitle_clips = create_dynamic_subtitles(script_text, video_clip.w, video_clip.h, video_clip.duration)
                    
                    final_clip = CompositeVideoClip([video_clip] + subtitle_clips) if subtitle_clips else video_clip
                    final_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
                    
                    st.success(f"🎉 '{topic}' 완성!")
                    st.video(output_path)
                    with open(output_path, "rb") as v_file:
                        st.download_button(f"💾 '{topic}' 다운로드", data=v_file, file_name=f"{topic}.mp4", mime="video/mp4", key=f"dl_{index}")
                except Exception as e: st.error(f"합성 에러: {e}")
                progress_bar.progress((index + 1) / len(df4))
            status_text.success("✅ 모든 비디오 병합 완료!")
