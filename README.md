# 실시간 음성 인식 및 번역기

## TL;DR
Whisper 모델을 활용한 실시간 음성 인식 및 번역 프로그램입니다. 마이크나 시스템 오디오를 캡처하여 음성을 감지하고, 텍스트로 변환한 후 자동으로 한국어로 번역합니다. 화면 위에 자막으로 결과를 표시할 수 있습니다.

## 주요 기능
- 🎤 **실시간 음성 캡처**: 마이크 또는 시스템 오디오(루프백) 입력 지원
- 🔊 **음성 활동 감지(VAD)**: WebRTC VAD 라이브러리를 사용한 효율적인 음성/비음성 구간 분리
- 🗣️ **음성 인식**: OpenAI Whisper 또는 Faster-Whisper를 통한 고품질 음성 인식
- 🌍 **다국어 지원**: 다양한 언어 자동 감지 및 인식
- 🔄 **자동 번역**: Google Translator를 이용한 한국어 번역
- 📊 **분석 및 모니터링**: 실시간 처리 상태 및 통계 제공
- 💻 **Apple Silicon 최적화**: Apple silicon Mac에서 MLX 기반 가속 지원
- 📝 **텍스트 후처리**: 반복 제거, 문장 완성도 개선 등 텍스트 정제
- 🖥️ **화면 자막 표시**: 인식 및 번역 결과를 화면 위에 자막으로 표시
- ⚙️ **확장된 설정**: JSON 기반 설정 파일로 다양한 설정 제어 가능
- 🖥️ **멀티 모니터 지원**: 여러 모니터에 자막 표시 가능

## 시스템 요구사항
- Python 3.8 이상
- PyAudio(portaudio 사전 설치 필수), NumPy, WebRTCVAD
- PyQt5 (자막 오버레이 기능)
- Apple Silicon MLX 지원 (LightningWhisperMlx)
- OpenAI Whisper 또는 Faster-Whisper
- 옵션: GPU 지원 (CUDA)

## 설치 방법
> venv 가상 개발 환경 추천
```bash
# 저장소 클론
git clone https://github.com/leonardo204/whisper_mlx.git
cd whisper_mlx

# 필수 패키지 설치
pip install -r requirements.txt

# PyQt5 설치 (자막 기능 사용 시)
pip install PyQt5

# Whisper 모델 설치 (옵션 중 하나 선택)
pip install faster-whisper   # Faster Whisper
# 또는
pip install lightning-whisper-mlx  # Apple Silicon 최적화 버전 (권장)
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

# 자막 설정
python main.py --caption  # 자막 활성화
python main.py --no-caption  # 자막 비활성화
python main.py --caption-position bottom  # 자막 위치 설정 (top, middle, bottom)
python main.py --caption-duration 5000  # 자막 표시 시간 (ms)
python main.py --caption-font-size 36  # 자막 폰트 크기

# 디버그 모드
python main.py --debug  # 상세 로그 출력
```

## 설정 파일 (settings.json)
프로그램은 `settings.json` 파일을 통해 다양한 설정을 지원합니다. 주요 설정 항목은 다음과 같습니다:

```json
{
  "audio": {
    "calibration_duration": 3
  },
  "transcription": {
    "model_name": "tiny",
    "use_faster_whisper": false,
    "max_history": 1000
  },
  "translation": {
    "enabled": true,
    "target_language": "ko"
  },
  "output": {
    "save_transcript": true,
    "output_dir": "results"
  },
  "system": {
    "log_level": "info"
  },
  "caption": {
    "enabled": true,
    "auto_start": true,
    "display_duration": 3000,
    "position": "bottom",
    "show_translation": true,
    "font_size": 36,
    "font_family": "AppleGothic",
    "text_color": "#FFFFFF",
    "translation_color": "#f5cc00",
    "background_color": "#88000000",
    "monitor": 0
  }
}
```

## 명령어 가이드
프로그램 실행 중 다음 명령어를 사용할 수 있습니다:
- `help`: 도움말 표시
- `stats`: 현재 통계 정보 표시
- `save`: 현재까지의 전사 결과 저장
- `config`: 현재 설정 표시
- `set [옵션]`: 설정 변경 (예: `set translate_to=en`)
- `reset`: 세션 초기화
- `cc on`: 자막 기능 활성화
- `cc off`: 자막 기능 비활성화
- `cc toggle`: 자막 표시/숨김 토글
- `cc [텍스트]`: 특정 텍스트를 자막으로 표시
- `exit`: 프로그램 종료

## 자막 기능 설명
프로그램은 인식 및 번역 결과를 화면 위에 자막으로 표시할 수 있습니다:

- **자막 위치**: 상단, 중앙, 하단 중 선택 가능
- **자막 스타일**: 폰트 종류, 크기, 색상, 배경 색상 등 설정 가능
- **번역 표시**: 원본 텍스트와 번역 텍스트를 함께 표시 가능
- **멀티 모니터**: 여러 모니터 중 원하는 모니터에 자막 표시 가능
- **단축키**: Space(표시/숨김 토글), ESC(프로그램 종료)
- **컨텍스트 메뉴**: 우클릭으로 자막 설정 변경 가능

### 자막 설정 명령어
```bash
# 자막 폰트 크기 변경
set caption.font_size=32

# 자막 위치 변경
set caption.position=top

# 자막 표시 시간 변경
set caption.display_duration=5000

# 자막 색상 변경
set caption.text_color=#FFFFFF
set caption.translation_color=#f5cc00
set caption.background_color=#88000000

# 자막 표시 모니터 변경
set caption.monitor=1
```

## Whisper 모델 선택 가이드

| 모델 | 메모리 요구사항 | 처리 속도 | 정확도 | 권장 사용 사례 |
|------|------------|--------|------|------------|
| tiny | ~1GB | 매우 빠름 | 낮음 | 간단한 테스트, 저사양 환경 |
| base | ~1GB | 빠름 | 기본 | 일반적인 용도, 단순한 내용 |
| small | ~2GB | 보통 | 좋음 | 일상 대화, 회의 전사 |
| medium | ~5GB | 느림 | 매우 좋음 | 중요한 내용, 전문 용어 포함 |
| large-v3 | ~10GB | 매우 느림 | 최고 | 다국어, 최고 품질 요구 시 |

## 예제 출력
```
[전사완료][2.34초][영어] This is an example of speech recognition.
[번역완료][0.15초][한국어] 이것은 음성 인식의 예시입니다.
```

## 시스템 구성 요소
- **main.py**: 메인 프로그램, 전체 워크플로우 관리
- **audio_device.py**: 오디오 장치 및 녹음 관리
- **audio_processor.py**: 오디오 처리 및 VAD 통합
- **transcription.py**: 음성 인식 및 번역 처리
- **settings.py**: 설정 관리 시스템
- **caption_overlay.py**: 화면 자막 오버레이 GUI
- **caption_client.py**: 자막 클라이언트 및 프로세스 간 통신
- **logging_utils.py**: 로깅 유틸리티

## 참고자료
- [LightningWhisperMlx](https://github.com/mustafaaljadery/lightning-whisper-mlx)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [Faster Whisper](https://github.com/guillaumekln/faster-whisper)
- [WebRTC VAD](https://github.com/wiseman/py-webrtcvad)
- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/)

## 라이센스
MIT License