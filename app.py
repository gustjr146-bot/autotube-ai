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
# 2. API 연동 함수 정의 (에러 메시지 원본 출력형)
# ==========================================
def call_gemini(prompt, api_key):
    if not api_key: return "Gemini 에러: API 키가 없습니다."
    api_key = api_key.strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload)
        if res.status_code != 200:
            # 구글 서버가 보내는 진짜 에러 메시지를 화면에 출력
            return f"Gemini 서버 거부 ({res.status_code}): {res.text[:150]}"
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Gemini 통신 에러: {str(e)[:150]}"

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
        if create_res.status_code != 200:
            return f"KIE 서버 거부 ({create_res.status_code}): {create_res.text[:150]}"
            
        resp_json = create_res.json()
        data = resp_json.get('data')
        if not data:
            return f"KIE 에러: {resp_json.get('message', '크레딧 부족 또는 키 오류')}"
            
        task_id = data.get('taskId')
        
        for _ in range(12):
            time.sleep(5)
            poll_res = requests.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers)
            if poll_res.status_code != 200:
                continue
            poll_data = poll_res.json()
            poll_data_inner = poll_data.get('data')
            
            if not poll_data_inner:
                return f"KIE 상태 조회 에러"
                
            state = str(poll_data_inner.get('state', '')).lower()
            
            if state in ['success', 'completed', 'done']:
                result_json = poll_data_inner['data']['resultJson']
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                return result_json['resultUrls'][0]
            elif state in ['failed', 'error']:
                return f"KIE 서버 내부 에러: 이미지 생성 실패"
        return "KIE 응답 시간 초과"
    except Exception as e:
        return f"KIE 통신 에러: {str(e)[:150]}"

def call_fal_tts(script, api_key):
    if not api_key: return "fal 에러: API 키가 없습니다."
    api_key = api_key.strip()
    
    url = "https://queue.fal.run/fal-ai/elevenlabs/tts/turbo-v2.5"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    safe_script = script[:500] if len(script) > 500 else script 
    payload = {"text": safe_script}
    
    try:
        create_res = requests.post(url, headers=headers, json=payload)
        if create_res.status_code != 200:
            return f"fal 서버 거부 ({create_res.status_code}): {create_res.text[:150]}"
            
        response_url = create_res.json().get('response_url')
        
        for _ in range(10):
            time.sleep(3)
            poll_res = requests.get(response_url, headers=headers)
            if poll_res.status_code == 200:
                audio_url = poll_res.json().get('audio', {}).get('url')
                if audio_url:
                    return audio_url
        return "fal 응답 시간 초과"
    except Exception as e:
        return f"fal 통신 에러: {str(e)[:150]}"

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
    st.markdown("엑셀 파일을 업로드하면, 각 행(Row)의 데이터를 읽어 AI 모델들이 대본, 이미지, 음성을 생성합니다.")
    
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
                
                topic_col = next((c for c in df.columns if '주제' in c), None)
                ref_col = next((c for c in df.columns if '레퍼런스' in c), None)
                
                for index, row in df.iterrows():
                    status_text.markdown(f"**작업 {index+1}/{len(df)} 진행 중...**")
                    
                    topic = str(row[topic_col]) if topic_col and pd.notna(row[topic_col]) else f"랜덤 {video_type} 주제"
                    ref_image = str(row[ref_col]) if ref_col and pd.notna(row[ref_col]) else ""
                    
                    # 1. Gemini
                    status_text.markdown(f"작업 {index+1}: ✍️ Gemini로 대본 작성 중...")
                    script_prompt = f"다음 주제로 {video_type}용 유튜브 대본을 300자 이내로 작성해줘. 주제: {topic}"
                    ai_response = call_gemini(script_prompt, GEMINI_KEY)
                    
                    # 2. KIE
                    status_text.markdown(f"작업 {index+1}: 🎨 KIE로 이미지 렌더링 중...")
                    safe_prompt = topic if "에러" in ai_response else ai_response[:100]
                    img_prompt = f"High quality, cinematic, {safe_prompt}"
                    image_url = call_kie_image(img_prompt, ref_image, aspect_ratio, KIE_KEY)
                    
                    # 3. fal
                    status_text.markdown(f"작업 {index+1}: 🗣️ fal.ai로 음성(TTS) 생성 중...")
                    if "에러" in ai_response:
                        # 💡 대본 생성이 에러나더라도 fal 음성 키가 정상인지 테스트하기 위해 임시 대본 전송
                        test_script = f"안녕하세요. 대본 생성이 지연되어 임시 음성으로 테스트합니다. 주제는 {topic} 입니다."
                        audio_url = call_fal_tts(test_script, FAL_KEY)
                    else:
                        audio_url = call_fal_tts(ai_response, FAL_KEY)
                    
                    is_success = "에러" not in str(ai_response) and "에러" not in str(image_url) and "에러" not in str(audio_url)
                    
                    results.append({
                        "주제": topic,
                        "대본/기획": ai_response[:100] + "..." if len(ai_response) > 100 else ai_response,
                        "이미지 링크": image_url,
                        "음성 링크": audio_url,
                        "상태": "✅ 성공" if is_success else "❌ 실패"
                    })
                    
                    progress_bar.progress((index + 1) / len(df))
                
                status_text.success("🎉 모든 파이프라인 작업이 완료되었습니다! 에러 메시지를 확인해주세요.")
                result_df = pd.DataFrame(results)
                st.dataframe(result_df)
                
                csv = result_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(label="💾 결과 엑셀 다운로드", data=csv, file_name='video_pipeline_results.csv', mime='text/csv')

with tab2:
    st.subheader("🎵 음원 + 영상 번들 제작")
    st.info("이곳에 fal.ai 음악 생성 기능이 연동됩니다.")
with tab3:
    st.subheader("💃 AI 모션 인플루언서")
    st.info("이곳에 Rendi API 기능이 연동됩니다.")
with tab4:
    st.subheader("📑 롱폼 영상 자동 병합")
    st.info("이곳에 영상 병합 로직이 포함됩니다.")
