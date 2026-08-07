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
st.title("🎬 AutoTube Studio AI (Runway 극사실 모션 마스터)")
st.markdown("대본 정제, **KIE/Runway 투트랙 완벽 방어**, 극사실적 모션, **에러 방지 및 2/5 위치 자막 병합**까지 지원합니다.")

FONT_PATH = os.path.abspath("NanumGothic.ttf")
if not os.path.exists(FONT_PATH):
    try:
        urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf", FONT_PATH)
    except Exception: pass 

# ==========================================
# 2. API 연동 함수 정의
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
        else: return f"Groq 거부 ({res.status_code})"
    except Exception: return "Groq 통신 에러"

def call_kie_video(prompt, aspect_ratio, duration, image_url, api_key):
    if not api_key: return None, "API 키 없음"
    api_key = api_key.strip()
    create_url = "https://api.kie.ai/api/v1/jobs/createTask"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    dur_str = "5" if str(duration) not in ["5", "10"] else str(duration)
    ratio_str = "16:9" if aspect_ratio == "16:9" else "9:16"
    
    models_to_try = []
    
    if image_url:
        models_to_try = [
            {"model": "kling/v2-5-turbo-image-to-video-pro", "input": {"prompt": prompt, "image_url": image_url, "duration": dur_str}},
            {"model": "kling/v2-1-master-image-to-video", "input": {"prompt": prompt, "image_url": image_url, "duration": dur_str}}
        ]
    else:
        models_to_try = [
            {"model": "kling/v2-5-turbo-text-to-video-pro", "input": {"prompt": prompt, "aspect_ratio": ratio_str, "duration": dur_str}},
            {"model": "kling/v2-1-master-text-to-video", "input": {"prompt": prompt, "aspect_ratio": ratio_str, "duration": dur_str}}
        ]
        
    task_id = None
    
    for payload in models_to_try:
        try:
            res = requests.post(create_url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                resp_json = res.json()
                data = resp_json.get('data')
                if isinstance(data, dict) and data.get('taskId'):
                    task_id = data.get('taskId')
                    break
        except Exception: pass
            
    if not task_id: return None, "KIE 서버 접수 거부됨"
        
    try:
        for _ in range(240): # KIE 내부 에러를 대비해 넉넉히 대기
            time.sleep(5)
            poll_res = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers, timeout=15)
            if poll_res.status_code != 200: continue
            
            try: poll_data = poll_res.json().get('data', {})
            except: continue
            if not isinstance(poll_data, dict): continue
            
            state = str(poll_data.get('state', '')).lower()
            if state in ['success', 'completed', 'done']:
                res_json = poll_data.get('resultJson', '{}')
                if isinstance(res_json, str):
                    try: res_json = json.loads(res_json)
                    except: res_json = {}
                urls = res_json.get('resultUrls', [])
                if urls: return urls[0], "성공"
            elif state in ['failed', 'error']: 
                fail_msg = poll_data.get('failReason', '서버 과부하 렌더링 에러')
                return None, f"KIE 내부 렌더링 실패 ({fail_msg})"
        return None, "KIE 시간 초과"
    except Exception as e: return None, f"KIE 폴링 에러: {str(e)}"

# 💡 [가장 핵심] KIE가 뻗었을 때 대타로 나서는 fal.ai를 '자연스러운 인물 모션 끝판왕'인 Runway Gen-3로 전면 업그레이드!
def call_fal_video(prompt, aspect_ratio, image_url, api_key):
    if not api_key: return None, "API 키 없음"
    api_key = api_key.strip()
    
    if image_url:
        url = "https://queue.fal.run/fal-ai/runway-gen3/turbo/image-to-video"
        payload = {"image_url": image_url, "prompt": prompt}
    else:
        url = "https://queue.fal.run/fal-ai/runway-gen3/turbo/text-to-video"
        payload = {"prompt": prompt, "aspect_ratio": "16:9" if aspect_ratio == "16:9" else "9:16"}
        
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    try:
        create_res = requests.post(url, headers=headers, json=payload, timeout=20)
        if create_res.status_code != 200: 
            return None, f"Runway 거부(코드{create_res.status_code})"
        response_url = create_res.json().get('response_url')
        
        for _ in range(120): # 최대 10분 대기
            time.sleep(5)
            poll_res = requests.get(response_url, headers=headers, timeout=15)
            if poll_res.status_code == 200:
                poll_json = poll_res.json()
                status = poll_json.get('status', '').lower()
                if status in ['failed', 'error', 'cancelled']: return None, f"Runway 렌더링 실패"
                video_url = poll_json.get('video', {}).get('url')
                if video_url: return video_url, "성공"
        return None, "Runway 시간 초과"
    except Exception as e: return None, f"Runway 에러"

def call_fal_tts(script, api_key):
    if not api_key: return "fal 에러: API 키 없음"
    api_key = api_key.strip()
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    clean_text = clean_script(script)
    payload = {"text": clean_text[:500] if len(clean_text) > 500 else clean_text}
    try:
        create_res = requests.post(url, headers=headers, json=payload, timeout=20)
        if create_res.status_code != 200: return f"fal 거부"
        response_url = create_res.json().get('response_url')
        for _ in range(15):
            time.sleep(3)
            poll_res = requests.get(response_url, headers=headers, timeout=15)
            if poll_res.status_code == 200:
                audio_url = poll_res.json().get('audio', {}).get('url')
                if audio_url: return audio_url
        return "fal 시간 초과"
    except Exception: return f"fal 통신 에러"

def download_file(url, save_path):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status() 
        with open(save_path, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk: out_file.write(chunk)
        if os.path.getsize(save_path) < 1024:
            raise Exception("다운로드된 파일이 손상되었습니다.")
    except Exception as e:
        raise Exception(f"안전 다운로드 실패: {e}")

def create_dynamic_subtitles(text, video_width, video_height, duration):
    try:
        clean_text = clean_script(text)
        words = clean_text.split()
        chunks = []
        curr = ""
        for w in words:
            if len(curr) + len(w) < 16:
                curr += w + " "
            else:
                chunks.append(curr.strip())
                curr = w + " "
        if curr: chunks.append(curr.strip())
            
        clips = []
        total_chars = sum(len(c) for c in chunks)
        if total_chars == 0: return []
        
        start_time = 0
        try: font = ImageFont.truetype(FONT_PATH, 38)
        except Exception: font = ImageFont.load_default()
        
        for chunk in chunks:
            chunk_duration = duration * (len(chunk) / total_chars)
            img = Image.new('RGBA', (video_width, 150), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            if hasattr(font, 'getbbox'):
                bbox = font.getbbox(chunk)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            else:
                w, h = draw.textsize(chunk, font=font)
            
            x_pos = (video_width - w) / 2
            y_pos = 50
            
            draw.rectangle((x_pos - 20, y_pos - 15, x_pos + w + 20, y_pos + h + 15), fill=(0, 0, 0, 180))
            draw.text((x_pos, y_pos), chunk, font=font, fill=(255, 255, 255, 255))
            
            img_np = np.array(img)
            txt_clip = ImageClip(img_np).set_duration(chunk_duration).set_start(start_time)
            
            subtitle_y = video_height * 0.60
            txt_clip = txt_clip.set_position(('center', subtitle_y))
            clips.append(txt_clip)
            
            start_time += chunk_duration
            
        return clips
    except Exception as e:
        print(f"자막 에러: {e}")
        return []

# ==========================================
# 3. 사이드바 
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password")
    KIE_KEY = st.text_input("KIE API Key (⭐1순위: 메인 비디오용)", type="password")
    FAL_KEY = st.text_input("fal.ai API Key (⭐2순위: 비디오/음성용)", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚀 자동화 파이프라인", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합 (자동 자막)"])

with tab1:
    st.subheader("대량 영상 재료 자동 생성 (Runway 극사실 모션 마스터)")
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
            
            for index, row in df1.iterrows():
                topic = str(row.get('주제(필수)', row.get('주제', f'랜덤 주제 {index}')))
                detail_req = str(row.get('세부요청(선택)', ''))
                prompt_topic = f"{topic}. {detail_req}" if detail_req and detail_req.lower() != 'nan' else topic
                
                ref_image = str(row.get('레퍼런스이미지 URL(선택)', row.get('레퍼런스이미지 URL', ''))).strip()
                if ref_image.lower() in ['nan', '', 'none'] or not ref_image.startswith('http'):
                    ref_image = None
                    
                vid_length = str(row.get('영상길이_초(필수)', '5')).strip()
                if vid_length not in ['5', '10']: vid_length = '5'
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 대본 작성 중...**")
                raw_script = call_groq(f"주제: {topic} ({video_type} 유튜브 쇼츠. 길이는 짧게 10초 분량만. 타임코드 금지.)", GROQ_KEY)
                ai_script = clean_script(raw_script)
                
                # 💡 [진짜 사람 모션 강제 프롬프트] Runway Gen-3가 제일 좋아하는 방식의 '실사 움직임' 프롬프트
                eng_prompt = f"Cinematic, ultra-realistic live-action video of a Korean person. {prompt_topic}. The person is breathing smoothly, blinking naturally, and moving their head and body like a real living human. Highly detailed, high motion, dynamic energy. Absolutely NO static image."
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] 🎥 KIE API 영상 생성 시도 중... ⏳**")
                visual_url, kie_status = call_kie_video(eng_prompt, aspect_ratio, vid_length, ref_image, KIE_KEY)
                
                if not visual_url or "http" not in visual_url:
                    st.warning(f"⚠️ KIE 거부/서버오류됨:\n{kie_status}")
                    status_text.markdown(f"**[{index+1}/{len(df1)}] 🚀 자연스러운 모션 1위 [Runway Gen-3] 엔진으로 전격 교체 렌더링 중... ⏳**")
                    # 💡 KIE가 뻗으면 Runway Gen-3를 긴급 투입합니다!
                    visual_url, fal_vid_status = call_fal_video(eng_prompt, aspect_ratio, ref_image, FAL_KEY)
                
                if not visual_url or "http" not in visual_url:
                    status_text.error(f"❌ 비디오 생성 완전 실패! (아래 에러를 확인해주세요)")
                    st.error(f"❌ KIE 오류: [{kie_status}] \n\n❌ Runway 오류: [{fal_vid_status}]")
                    continue
                
                status_text.markdown(f"**[{index+1}/{len(df1)}] '{topic}' 음성 생성 중...**")
                aud_url = call_fal_tts(ai_script, FAL_KEY)
                
                results.append({"주제": topic, "대본": ai_script, "비디오": visual_url, "음성": aud_url})
                progress_bar.progress((index + 1) / len(df1))
                
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
                vis_url = str(row.get('비디오', row.get('이미지', '')))
                audio_url = str(row.get('음성', ''))
                
                status_text.markdown(f"**[{index+1}/{len(df4)}] '{topic}' 안전 다운로드 및 렌더링 중... ⏳**")
                
                if "http" not in vis_url or vis_url.lower() == 'nan': continue
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
                        video_clip = VideoFileClip(temp_vis_path).without_audio()
                        w, h = video_clip.size
                        video_clip = video_clip.resize(newsize=(w - w % 2, h - h % 2))
                        
                        if video_clip.duration < audio_clip.duration:
                            try:
                                reversed_clip = video_clip.fx(vfx.time_mirror)
                                ping_pong_clip = concatenate_videoclips([video_clip, reversed_clip])
                                num_loops = math.ceil(audio_clip.duration / ping_pong_clip.duration)
                                video_clip = concatenate_videoclips([ping_pong_clip] * num_loops)
                            except Exception:
                                num_loops = math.ceil(audio_clip.duration / video_clip.duration)
                                video_clip = concatenate_videoclips([video_clip] * num_loops)
                                
                        video_clip = video_clip.subclip(0, audio_clip.duration)
                    else:
                        base_clip = ImageClip(temp_vis_path)
                        w, h = base_clip.size
                        w, h = w - w % 2, h - h % 2
                        base_clip = base_clip.resize(newsize=(w, h))
                        
                        def zoom(t): return 1.0 + 0.05 * (t / audio_clip.duration)
                        zoomed_clip = base_clip.resize(zoom).set_position(('center', 'center'))
                        video_clip = CompositeVideoClip([zoomed_clip], size=(w, h)).set_duration(audio_clip.duration)
                        
                    video_clip = video_clip.set_audio(audio_clip)
                    
                    subtitle_clips = create_dynamic_subtitles(script_text, video_clip.w, video_clip.h, video_clip.duration)
                    
                    if subtitle_clips:
                        final_clip = CompositeVideoClip([video_clip] + subtitle_clips)
                    else:
                        final_clip = video_clip
                    
                    final_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
                    
                    st.success(f"🎉 '{topic}' 완벽한 동영상 완성!")
                    st.video(output_path)
                    
                    with open(output_path, "rb") as v_file:
                        st.download_button(f"💾 '{topic}' 다운로드", data=v_file, file_name=f"{topic}.mp4", mime="video/mp4", key=f"dl_{index}")
                        
                except Exception as e:
                    st.error(f"합성 에러 발생: {e}")
                
                progress_bar.progress((index + 1) / len(df4))
                
            status_text.success("✅ 모든 비디오 병합이 완료되었습니다!")
