import streamlit as st
import pandas as pd
import requests
import json
import time

# ==========================================
# 1. 화면 기본 설정
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (통합형)")
st.markdown("엑셀 업로드 한 번으로 대본(Gemini) ➡️ 이미지(KIE) ➡️ 음성(fal)을 자동 생성합니다.")

# ==========================================
# 2. API 연동 함수 정의
# ==========================================
def call_gemini(prompt, api_key):
    """Gemini API를 호출하여 대본/기획안 생성"""
    if not api_key: return "Gemini API 키가 없습니다."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload)
        res.raise_for_status()
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Gemini API 에러: {e}"

def call_kie_image(prompt, ref_url, aspect_ratio, api_key):
    """KIE API를 호출하여 이미지 생성 (Task 생성 후 Polling)"""
    if not api_key: return "KIE API 키가 없습니다."
    
    # 1. 생성 요청 (Task)
    create_url = "https://api.kie.ai/api/v1/jobs/createTask"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "google/nano-banana-edit",
        "input": {"prompt": prompt, "output_format": "png", "aspect_ratio": aspect_ratio}
    }
    if pd.notna(ref_url) and str(ref_url).strip():
        payload["input"]["image_urls"] = [str(ref_url).strip()]
        
    try:
        create_res = requests.post(create_url, headers=headers, json=payload)
        create_res.raise_for_status()
        task_id = create_res.json().get('data', {}).get('taskId')
        
        # 2. 결과 대기 (Polling)
        for _ in range(12):
            time.sleep(5)
            poll_res = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers)
            poll_data = poll_res.json()
            state = str(poll_data.get('data', {}).get('state', '')).lower()
            
            if state in ['success', 'completed', 'done']:
                result_json = poll_data['data']['resultJson']
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                return result_json['resultUrls'][0]
            elif state in ['failed', 'error']:
                return f"KIE 생성 실패: {state}"
        return "KIE 응답 시간 초과"
    except Exception as e:
        return f"KIE API 에러: {e}"

def call_fal_tts(script, api_key):
    """fal.ai API를 호출하여 음성(TTS) 생성"""
    if not api_key: return "fal API 키가 없습니다."
    
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {"text": script}
    
    try:
        # 1. 생성 요청
        create_res = requests.post(url, headers=headers, json=payload)
        create_res.raise_for_status()
        response_url = create_res.json().get('response_url')
        
        # 2. 결과 대기
        for _ in range(10):
            time.sleep(3)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                audio_url = poll_res.json().get('audio', {}).get('url')
                if audio_url:
                    return audio_url
        return "fal TTS 응답 시간 초과"
    except Exception as e:
        return f"fal API 에러: {e}"

# ==========================================
# 3. 사이드바 (API 키 설정)
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    st.markdown("발급받으신 API 키를 입력해주세요.")
    GEMINI_KEY = st.text_input("Gemini API Key", type="password")
    KIE_KEY = st.text_input("KIE API Key", type="password")
    FAL_KEY = st.text_input("fal.ai API Key", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚀 자동화 파이프라인 (쇼츠/롱폼)", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합"])

with tab1:
    st.subheader("대량 영상 자동 제작 (엑셀 연동)")
    st.markdown("엑셀 파일을 업로드하면, 각 행(Row)의 데이터를 읽어 AI 모델들이 대본, 이미지, 음성을 순차적으로 생성합니다.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        video_type = st.radio("영상 포맷", ["쇼츠 (9:16)", "롱폼 (16:9)"])
        aspect_ratio = "9:16" if "쇼츠" in video_type else "16:9"
        
    with col2:
        uploaded_file = st.file_uploader("기획안 업로드 (CSV 또는 엑셀)", type=['csv', 'xlsx'])
    
    if uploaded_file is not None:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        st.success(f"✅ 총 {len(df)}개의 작업이 감지되었습니다.")
        st.dataframe(df.head(3))
        
        if st.button("🔥 파이프라인 가동 시작", type="primary"):
            if not GEMINI_KEY or not KIE_KEY or not FAL_KEY:
                st.error("사이드바에 Gemini, KIE, fal API 키를 모두 입력해주세요!")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                results = []
                
                # 엑셀 데이터 한 줄씩 처리
                for index, row in df.iterrows():
                    status_text.markdown(f"**작업 {index+1}/{len(df)} 진행 중...**")
                    
                    topic = str(row.get('주제', ''))
                    ref_image = str(row.get('레퍼런스이미지', ''))
                    
                    # 1. Gemini 기획/대본
                    status_text.markdown(f"작업 {index+1}: ✍️ Gemini로 대본/프롬프트 작성 중...")
                    script_prompt = f"다음 주제로 {video_type}용 대본과 이미지 생성 프롬프트를 JSON 형식으로 작성해줘: {topic}"
                    ai_response = call_gemini(script_prompt, GEMINI_KEY)
                    
                    # 2. KIE 이미지
                    status_text.markdown(f"작업 {index+1}: 🎨 KIE로 이미지 렌더링 중...")
                    img_prompt = f"High quality, cinematic, {topic}"
                    image_url = call_kie_image(img_prompt, ref_image, aspect_ratio, KIE_KEY)
                    
                    # 3. fal 음성
                    status_text.markdown(f"작업 {index+1}: 🗣️ fal.ai로 음성(TTS) 생성 중...")
                    audio_url = call_fal_tts(f"안녕하세요! 오늘의 주제는 {topic}입니다.", FAL_KEY)
                    
                    # 임시로 FFMPEG 병합되었다고 가정
                    final_video = "병합 대기 (FFMPEG는 로컬 환경에서 실행됨)"
                    
                    results.append({
                        "주제": topic,
                        "대본/기획": ai_response[:50] + "...",
                        "이미지 링크": image_url,
                        "음성 링크": audio_url,
                        "상태": "✅ 성공" if "http" in image_url and "http" in audio_url else "❌ 일부 실패"
                    })
                    
                    progress_bar.progress((index + 1) / len(df))
                
                status_text.success("🎉 모든 파이프라인 작업이 완료되었습니다!")
                
                # 결과 엑셀 다운로드
                result_df = pd.DataFrame(results)
                st.dataframe(result_df)
                
                csv = result_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="💾 결과 엑셀 다운로드",
                    data=csv,
                    file_name='video_pipeline_results.csv',
                    mime='text/csv',
                )

with tab2:
    st.subheader("🎵 음원 + 영상 번들 제작")
    st.info("이곳에 fal.ai의 음악 생성 API 모델을 호출하여 이미지를 씌우는 로직이 들어갑니다.")

with tab3:
    st.subheader("💃 AI 모션 인플루언서")
    st.info("이곳에 Rendi API(모션 트래킹)와 KIE(이미지 변환)를 연동하여 입력한 사진을 춤추게 만드는 로직이 들어갑니다.")

with tab4:
    st.subheader("📑 롱폼 영상 자동 병합")
    st.info("서버(또는 로컬 PC)에 설치된 FFMPEG를 활용해 여러 개의 짧은 클립을 하나의 영상으로 이어붙입니다.")
