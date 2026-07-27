import streamlit as st
import pandas as pd
import requests
import json
import time

# ==========================================
# 1. 화면 기본 설정
# ==========================================
st.set_page_config(page_title="AutoTube Studio AI", page_icon="🎬", layout="wide")
st.title("🎬 AutoTube Studio AI (통합형 마스터)")
st.markdown("엑셀 업로드 한 번으로 대본(Groq), 이미지, 음성을 자동 생성합니다.")

# ==========================================
# 2. API 연동 함수 정의 (구글 제거 -> Groq Llama3 도입)
# ==========================================
def call_groq(prompt, api_key):
    """결제 오류가 잦은 구글 대신, 빠르고 무료인 Groq API를 사용합니다."""
    if not api_key: return "Groq 에러: API 키가 없습니다."
    api_key = api_key.strip()
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-70b-8192",  # 초고속 최신 AI 모델
        "messages": [
            {"role": "system", "content": "유튜브 쇼츠나 롱폼 대본을 재치있게 한국어로 작성해주는 전문 작가입니다."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        else:
            return f"Groq 거부 ({res.status_code}): {res.text[:150]}"
    except Exception as e:
        return f"Groq 통신 에러: {str(e)[:150]}"

def call_kie_image(prompt, ref_url, aspect_ratio, api_key):
    if not api_key: return "KIE 에러: API 키가 없습니다."
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
        if create_res.status_code != 200: return f"KIE 서버 거부 ({create_res.status_code})"
        data = create_res.json().get('data')
        if not data: return "KIE 에러: 크레딧 부족 등"
        task_id = data.get('taskId')
        
        for _ in range(12):
            time.sleep(5)
            poll_res = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers)
            if poll_res.status_code != 200: continue
            poll_data_inner = poll_res.json().get('data')
            if not poll_data_inner: return "KIE 상태 조회 에러"
            state = str(poll_data_inner.get('state', '')).lower()
            if state in ['success', 'completed', 'done']:
                res_json = poll_data_inner.get('resultJson', '{}')
                if isinstance(res_json, str):
                    try: res_json = json.loads(res_json)
                    except: res_json = {}
                urls = res_json.get('resultUrls', [])
                return urls[0] if urls else "KIE 이미지 생성됨 (URL 없음)"
            elif state in ['failed', 'error']: return "KIE 이미지 생성 실패"
        return "KIE 응답 시간 초과"
    except Exception as e: return f"KIE 통신 에러: {str(e)[:50]}"

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
# 3. 사이드바 (API 키 설정)
# ==========================================
with st.sidebar:
    st.header("🔑 API 키 설정")
    st.markdown("발급받으신 API 키를 입력해주세요.")
    # Gemini 대신 Groq를 받도록 화면 수정
    GROQ_KEY = st.text_input("Groq API Key (대본용)", type="password", help="https://console.groq.com/keys 에서 무료 발급")
    KIE_KEY = st.text_input("KIE API Key", type="password")
    FAL_KEY = st.text_input("fal.ai API Key", type="password")
    RENDI_KEY = st.text_input("Rendi API Key (모션용)", type="password")

# ==========================================
# 4. 메인 대시보드 탭 (전체 엑셀 업로드 지원)
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚀 자동화 파이프라인 (쇼츠/롱폼)", "🎵 음원 제작", "💃 AI 모션", "📑 영상 병합"])

with tab1:
    st.subheader("대량 영상 자동 제작 (쇼츠/롱폼 시트 업로드)")
    col1, col2 = st.columns([1, 2])
    with col1:
        video_type = st.radio("영상 포맷", ["쇼츠 (9:16)", "롱폼 (16:9)"])
        aspect_ratio = "9:16" if "쇼츠" in video_type else "16:9"
    with col2:
        file1 = st.file_uploader("기획안 업로드 (쇼츠/롱폼 시트)", type=['csv', 'xlsx'], key="f1")
    
    if file1:
        df1 = pd.read_excel(file1) if file1.name.endswith('.xlsx') else pd.read_csv(file1)
        st.success(f"✅ 총 {len(df1)}개의 작업이 감지되었습니다.")
        st.dataframe(df1.head(3))
        
        if st.button("🔥 파이프라인 가동 시작", type="primary", key="btn1"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []
            
            for index, row in df1.iterrows():
                status_text.markdown(f"**작업 {index+1}/{len(df1)} 진행 중...**")
                topic_col = next((c for c in df1.columns if '주제' in c), None)
                ref_col = next((c for c in df1.columns if '레퍼런스' in c), None)
                topic = str(row[topic_col]) if topic_col and pd.notna(row[topic_col]) else "랜덤 주제"
                ref_image = str(row[ref_col]) if ref_col and pd.notna(row[ref_col]) else ""
                
                # 구글 대신 Groq(Llama3)로 대본 생성
                ai_script = call_groq(f"주제: {topic} ({video_type} 유튜브 대본 작성)", GROQ_KEY)
                img_url = call_kie_image(f"High quality, {topic}", ref_image, aspect_ratio, KIE_KEY)
                test_script = f"주제는 {topic} 입니다." if "거부" in ai_script or "에러" in ai_script else ai_script
                aud_url = call_fal_tts(test_script, FAL_KEY)
                
                results.append({"주제": topic, "대본": ai_script[:150], "이미지": img_url, "음성": aud_url})
                progress_bar.progress((index + 1) / len(df1))
                
            status_text.success("🎉 작업 완료! (결과를 확인해주세요)")
            st.dataframe(pd.DataFrame(results))

# ... (탭 2, 3, 4는 이전과 동일) ...
with tab2: st.info("음원 생성 기능 연동")
with tab3: st.info("AI 모션 연동")
with tab4: st.info("영상 병합 연동")
