# 실시간 음성 인식 및 번역기

## TL;DR
Whisper 모델을 활용한 실시간 음성 인식 및 번역 프로그램입니다. 마이크나 시스템 오디오를 캡처하여 음성을 감지하고, 텍스트로 변환한 후 자동으로 한국어로 번역합니다.

## 주요 기능
- 🎤 **실시간 음성 캡처**: 마이크 또는 시스템 오디오(루프백) 입력 지원
- 🔊 **음성 활동 감지(VAD)**: WebRTC VAD 라이브러리를 사용한 효율적인 음성/비음성 구간 분리
- 🗣️ **음성 인식**: OpenAI Whisper 또는 Faster-Whisper를 통한 고품질 음성 인식
- 🌍 **다국어 지원**: 다양한 언어 자동 감지 및 인식
- 🔄 **자동 번역**: Google Translator를 이용한 한국어 번역
- 📊 **분석 및 모니터링**: 실시간 처리 상태 및 통계 제공
- 💻 **Apple Silicon 최적화**: M1/M2 Mac에서 MLX 기반 가속 지원
- 📝 **텍스트 후처리**: 반복 제거, 문장 완성도 개선 등 텍스트 정제

## 시스템 요구사항
- Python 3.8 이상
- PyAudio, NumPy, WebRTCVAD
- OpenAI Whisper 또는 Faster-Whisper
- 옵션: GPU 지원 (CUDA)
- 옵션: Apple Silicon의 경우 MLX 지원

## 설치 방법
```bash
# 저장소 클론
git clone https://github.com/yourusername/realtime-whisper-transcriber.git
cd realtime-whisper-transcriber

# 필수 패키지 설치
pip install -r requirements.txt

# Whisper 모델 설치 (옵션 중 하나 선택)
pip install openai-whisper  # 기본 Whisper
# 또는
pip install faster-whisper   # Faster Whisper (권장)
# 또는
pip install lightning-whisper-mlx  # Apple Silicon 최적화 버전
```

## 사용 방법
### 기본 실행
```bash
python main.py
```

### 고급 옵션
```bash
# 다양한 모델 크기 설정
python main.py --model medium  # tiny, base, small, medium, large-v3 중 선택

# 번역 설정
python main.py --translate-to en  # 번역 대상 언어 설정
python main.py --no-translate  # 번역 비활성화

# 디버그 모드
python main.py --debug  # 상세 로그 출력
```

## 명령어 가이드
프로그램 실행 중 다음 명령어를 사용할 수 있습니다:
- `help`: 도움말 표시
- `stats`: 현재 통계 정보 표시
- `save`: 현재까지의 전사 결과 저장
- `config`: 현재 설정 표시
- `set [옵션]`: 설정 변경 (예: `set translate_to=en`)
- `reset`: 세션 초기화
- `exit`: 프로그램 종료

## 예제 출력
```
[전사완료][2.34초][영어] This is an example of speech recognition.
[번역완료][0.15초][한국어] 이것은 음성 인식의 예시입니다.
```

## 참고자료
- [OpenAI Whisper](https://github.com/openai/whisper)
- [Faster Whisper](https://github.com/guillaumekln/faster-whisper)
- [WebRTC VAD](https://github.com/wiseman/py-webrtcvad)

## 라이센스
MIT License
