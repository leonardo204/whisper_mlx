import os
import time
import numpy as np
from typing import Dict, Optional, List
from logging_utils import LogManager

class MLXWhisperTranscriber:
    """Apple Silicon에 최적화된 LightningWhisperMLX를 사용한 전사기"""

    def __init__(self, model_name: str = "large-v3"):
        """MLX Whisper 전사기 초기화"""
        self.logger = LogManager()
        self.logger.log_info(f"MLX Whisper 전사기 초기화 (모델: {model_name})")

        self.model_name = model_name
        self.model = None
        self._init_model()

    def _init_model(self):
        """MLX Whisper 모델 초기화"""
        try:
            # 모델 초기화 전 라이브러리 확인
            try:
                from lightning_whisper_mlx import LightningWhisperMLX

                self.logger.log_info("Apple Silicon용 LightningWhisperMLX 로드 중...")

                # 모델 로드
                self.model = LightningWhisperMLX(
                    model=self.model_name,
                    batch_size=6,  # 기본값, 메모리에 따라 조정 가능
                )
                self.logger.log_info(f"MLX Whisper 모델 '{self.model_name}'이 로드되었습니다")

            except ImportError as e:
                self.logger.log_critical(f"LightningWhisperMLX를 가져올 수 없습니다: {str(e)}")
                self.logger.log_info("pip install lightning-whisper-mlx로 설치하세요")
                raise

        except Exception as e:
            self.logger.log_critical(f"MLX Whisper 모델 초기화 실패: {str(e)}")
            raise RuntimeError(f"MLX Whisper 모델을 초기화할 수 없습니다: {str(e)}")

    def transcribe(self, audio_data: np.ndarray) -> Dict:
        """오디오 데이터 전사"""
        try:
            start_time = time.time()

            # MLX 모델은 16kHz 샘플레이트, float32 데이터 예상
            result = self.model.transcribe(audio_data)

            # 처리 시간 계산
            process_time = time.time() - start_time

            # 결과 형식화
            transcription = {
                'text': result.get('text', ''),
                'language': result.get('language', 'unknown'),
                'confidence': 1.0,  # MLX 모델은 신뢰도 점수 제공 안함
                'processing_time': process_time
            }

            return transcription

        except Exception as e:
            self.logger.log_error("mlx_transcribe", f"MLX 전사 중 오류: {str(e)}")
            # 최소한의 결과 반환
            return {
                'text': '',
                'language': 'unknown',
                'confidence': 0.0,
                'error': str(e)
            }
