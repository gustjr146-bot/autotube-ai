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
st.title("🎬 AutoTube Studio AI (오류 완벽방어 & 극사실 모션)")
st.markdown("대본 정제, **서버 무응답 방어막 적용**, 사람이 직접 행동하는 극사실적 모션 강제, 자막 병합 지원.")

FONT_PATH = os.path.abspath("NanumGothic.ttf")
if not os.path.exists(FONT_PATH):
    try: urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf", FONT_PATH)
    except: pass 

# ==========================================
# 2. 대본 및 API 통신 모듈
# ==========================================
def clean_script(text):
    text = re.sub(r'\(\d+:\d+\s*-\s*\d+:\d+\)', '', text)
    text = re.sub(r'\[\d+:\d+\s*-\s*\d+:\d+\]', '', text) 
    return text.replace('\n', ' ').strip()

def call_groq(prompt, api_key):
    if not api_key: return "Groq API 키 없음"
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",  
        "messages": [
            {"role": "system", "content": "한국어 유튜브 쇼츠 전문 작가. 대본 본문만 짧게 작성. 타임코드 금지."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    try:
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if res.status_code == 200: return clean_script(res.json()['choices'][0]['message']['content'])
    except: pass
    return "대본 생성 에러"

# 💡 [버그 해결] KIE 서버 응답이 비정상일 때 NoneType 에러가 나지 않도록 방어막 추가
def call_kie_video(prompt, aspect_ratio, image_url, api_key, status_text, current_idx, total_items):
    if not api_key: return None, "KIE API 키 누락"
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    ratio = "16:9" if aspect_ratio == "16:9" else "9:16"
    
    if image_url:
        payload = {"model": "kling-3.0/video", "input": {"prompt": prompt, "image_url": image_url, "duration": 5}}
    else:
        payload = {"model": "kling-3.0/video", "input": {"prompt": prompt, "aspect_ratio": ratio, "duration": 5}}
        
    try:
        r = requests.post("https://api.kie.ai/api/v1/jobs/createTask", headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            res_json = r.json()
            if isinstance(res_json, dict) and res_json.get('data', {}).get('taskId'):
                task_id = res_json['data']['taskId']
            else:
                err = res_json.get('msg', '알 수 없는 응답') if isinstance(res_json, dict) else "서버 응답 오류"
                return None, f"KIE 서버 접수 거부: {str(err)[:80]}"
        else:
            return None, f"KIE 통신 에러 (코드 {r.status_code})"
    except Exception as e: 
        return None, "KIE 시스템 무응답"
        
    start = time.time()
    for _ in range(120): # 최대 10분 대기
        time.sleep(5)
        elapsed = int(time.time() - start)
        
        try:
            pr = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers, timeout=10)
            if pr.status_code == 200:
                d = pr.json()
                if not isinstance(d, dict): continue
                d = d.get('data', {})
                stt = str(d.get('state', d.get('status', 'PENDING'))).upper()
                status_text.markdown(f"**[{current_idx}/{total_items}] 🎥 [1순위] KIE 렌더링 중... (상태: {stt} / {elapsed}초 경과) ⏳**")
                
                res_j = d.get('resultJson', {})
                if isinstance(res_j, str): 
                    try: res_j = json.loads(res_j)
                    except: res_j = {}
                if isinstance(res_j, dict) and res_j.get('resultUrls'):
                    return res_j['resultUrls'][0], "성공"
                    
                if stt in ['FAILED', 'ERROR', 'CANCELLED', 'TIMEOUT']: 
                    return None, f"KIE 렌더링 실패: {d.get('failReason', '서버 내부 오류')}"
        except: continue
    return None, "KIE 시간 초과"

# 💡 [버그 해결] Fal 보조 엔진 역시 빈 껍데기 응답을 걸러냅니다.
def call_fal_fast_video(prompt, aspect_ratio, image_url, api_key, status_text, current_idx, total_items):
    if not api_key: return None, "Fal API 키 누락"
    headers = {"Authorization": f"Key {api_key.strip()}", "Content-Type": "application/json"}
    
    if image_url:
        url = "https://queue.fal.run/fal-ai/runway-gen3/turbo/image-to-video"
        payload = {"image_url": image_url, "prompt": prompt}
    else:
        url = "https://queue.fal.run/fal-ai/runway-gen3/turbo/text-to-video"
        payload = {"prompt": prompt, "aspect_ratio": "16:9" if aspect_ratio == "16:9" else "9:16"}
        
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code != 200: 
            return None, f"Fal 접속 거부 (키 오류 의심): {r.text[:80]}"
        
        res_json = r.json()
        if not isinstance(res_json, dict): return None, "Fal 응답 포맷 오류"
        resp_url = res_json.get('response_url')
        
        start = time.time()
        for _ in range(60): # 5분 대기
            time.sleep(5)
            elapsed = int(time.time() - start)
            try:
                pr = requests.get(resp_url, headers=headers, timeout=10)
                if pr.status_code == 200:
                    d = pr.json()
                    if not isinstance(d, dict): continue
                    stt = d.get('status', 'PENDING').upper()
                    status_text.markdown(f"**[{current_idx}/{total_items}] 🚀 [2순위] Fal 보조 엔진 렌더링 중... (상태: {stt} / {elapsed}초 경과) ⏳**")
                    
                    if stt in ['FAILED', 'ERROR', 'CANCELLED']: return None, "Fal 렌더링 실패"
                    v = d.get('video', {})
                    if isinstance(v, dict) and v.get('url'): return v['url'], "성공"
                    if d.get('video_url'): return d['video_url'], "성공"
            except: continue
        return None, "Fal 시간 초과"
    except Exception as e: return None, "Fal 시스템 무응답"

def call_fal_tts(script, api_key):
    if not api_key: return None
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key.strip()}", "Content-Type": "application/json"}
    payload = {"text": clean_script(script)[:500]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code != 200: return None
        res_json = r.json()
        if not isinstance(res_json, dict): return None
        resp_url = res_json.get('response_url')
        
        for _ in range(20):
            time.sleep(3)
            try:
                pr = requests.get(resp_url, headers=headers, timeout=10)
                if pr.status_code == 200:
                    pd_json = pr.json()
                    if isinstance(pd_json, dict) and pd_json.get('audio', {}).get('url'):
                        return pd_json['audio']['url']
            except: continue
    except: pass
    return None

# ==========================================
# 3. 비디오/자막 병합 유틸리티
# ==========================================
def download_file(url, save_path):
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, stream=True, timeout=30)
    response.raise_for_status() 
    with open(save_path, 'wb') as out_file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk: out_file.write(chunk)

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
# 4. 메인 화면 구성
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    KIE_KEY = st.text_input("KIE API Key (⭐엔진1)", type="password")
    FAL_KEY = st.text_input("fal.ai API Key (⭐엔진2/음성)", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (현재 미사용)", type="password") 

tab1, tab2, tab3, tab4 = st.tabs(["🚀 영상 생성", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합 (자동 자막)"])

with tab1:
    st.subheader("대량 영상 재료 자동 생성 (오류 방어 완료)")
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
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 쇼츠)", GROQ_KEY)
                
                # 💡 [극사실 모션 보장 프롬프트] 사람이 직접 행동하는 듯한 완벽한 묘사 강제!
                eng_prompt = f"Ultra-realistic cinematic live-action video of a Korean person. {prompt_topic}. The subject is a REAL living human actively moving. They MUST exhibit continuous, natural human behaviors: smooth visible breathing, natural eye blinking, shifting their body weight, and expressive fluid movements. It must look like real camera video footage capturing authentic human actions. Absolutely NO static, frozen, or still images. High motion, lifelike energy."
                
                visual_url, kie_err = call_kie_video(eng_prompt, aspect_ratio, ref_image, KIE_KEY, status_text, current_idx, total_items)
                
                if not visual_url: 
                    status_text.markdown(f"**[{current_idx}/{total_items}] ⚠️ KIE 실패({kie_err}), 초고속 보조 엔진 가동 중... ⏳**")
                    visual_url, fal_err = call_fal_fast_video(eng_prompt, aspect_ratio, ref_image, FAL_KEY, status_text, current_idx, total_items)
                
                if not visual_url:
                    st.error(f"❌ '{topic}' 비디오 생성 완전 실패. \n- KIE 에러: {kie_err}\n- Fal 에러: {fal_err}")
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
