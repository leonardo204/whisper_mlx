import numpy as np
import os
import time
import tempfile
import json
import re
from typing import Dict, Optional, List, Union, Tuple
import threading
from collections import deque
import datetime
from deep_translator import GoogleTranslator  # 새로운 라이브러리 사용
from logging_utils import LogManager

# 모델 지원 언어
SUPPORTED_LANGUAGES = {
    'ko': '한국어',
    'en': '영어',
    'ja': '일본어',
    'zh': '중국어',
    'es': '스페인어',
    'fr': '프랑스어',
    'de': '독일어',
    'it': '이탈리아어',
    'ru': '러시아어',
    'ar': '아랍어',
    'hi': '힌디어',
    'pt': '포르투갈어',
    'nl': '네덜란드어',
    'tr': '터키어',
    'pl': '폴란드어',
    'vi': '베트남어',
    'th': '태국어',
    'id': '인도네시아어'
}

class TextProcessor:
    """
    텍스트 처리 클래스
    - 텍스트 정제
    - 불완전한 문장 처리
    - 반복 제거
    - 문장 병합
    """
    def __init__(self):
        """텍스트 프로세서 초기화"""
        self.logger = LogManager()
        self.logger.log_info("텍스트 프로세서 초기화")
        
        # 최근 처리 텍스트 기록 (중복 검사용)
        self.recent_texts = deque(maxlen=5)
        
        # 정제 패턴
        self.cleanup_patterns = [
            (r'\s+', ' '),                # 연속된 공백 정규화
            (r'[\s.,!?]+$', ''),          # 끝부분 특수문자 제거
            (r'^[\s.,!?]+', ''),          # 시작부분 특수문자 제거
            (r'[.]{2,}', '...'),          # 마침표 정규화
            (r'[,]{2,}', ','),            # 쉼표 정규화
            (r'[!]{2,}', '!!'),           # 느낌표 정규화
            (r'[?]{2,}', '??')            # 물음표 정규화
        ]
        
        # 한국어 문장 종결 패턴
        self.ko_sentence_end = r'[.!?~…]\s*$|[다요죠양함임니까까요까봐봐죠네요네죠]\s*$'
        
        # 단어 반복 패턴 (단일 단어 반복)
        self.word_repetition_pattern = r'(\b\w+\b)(\s+\1\b)+'
        
        # 구문 반복 패턴 (2-5단어 구문 반복) - 새로 추가
        self.phrase_repetition_patterns = [
            # 2단어 구문 반복 패턴
            r'(\b\w+\s+\w+\b)(\s+\1\b)+',
            # 3단어 구문 반복 패턴
            r'(\b\w+\s+\w+\s+\w+\b)(\s+\1\b)+',
            # 4단어 구문 반복 패턴
            r'(\b\w+\s+\w+\s+\w+\s+\w+\b)(\s+\1\b)+',
            # 5단어 구문 반복 패턴
            r'(\b\w+\s+\w+\s+\w+\s+\w+\s+\w+\b)(\s+\1\b)+'
        ]
        
        # 한국어 반복 패턴 (2-5어절 구문 반복) - 새로 추가
        self.korean_repetition_patterns = [
            # 2어절 구문 반복
            r'([가-힣]+\s+[가-힣]+)(\s+\1)+',
            # 3어절 구문 반복
            r'([가-힣]+\s+[가-힣]+\s+[가-힣]+)(\s+\1)+',
            # 4어절 구문 반복
            r'([가-힣]+\s+[가-힣]+\s+[가-힣]+\s+[가-힣]+)(\s+\1)+',
            # 5어절 구문 반복
            r'([가-힣]+\s+[가-힣]+\s+[가-힣]+\s+[가-힣]+\s+[가-힣]+)(\s+\1)+'
        ]
        
        self.logger.log_info("텍스트 프로세서가 초기화되었습니다")

    def process_text(self, text: str) -> Optional[str]:
        """전사 텍스트 처리"""
        try:
            if not text or not text.strip():
                return None
                
            # 기본 정제
            processed = text.strip()
            
            # 정규화 패턴 적용
            for pattern, replacement in self.cleanup_patterns:
                processed = re.sub(pattern, replacement, processed)
                
            # 단일 단어 반복 제거
            processed = re.sub(self.word_repetition_pattern, r'\1', processed)
            
            # 영어 구문 반복 제거
            for pattern in self.phrase_repetition_patterns:
                processed = re.sub(pattern, r'\1', processed)
                
            # 한국어 구문 반복 제거
            for pattern in self.korean_repetition_patterns:
                processed = re.sub(pattern, r'\1', processed)
                
            # 한국어 반복 구문 추가 검사 (정규식으로 감지하기 어려운 경우)
            processed = self._remove_korean_repetitions(processed)
            
            # 이전 텍스트와 유사도 확인 (중복 방지)
            if self._is_duplicate(processed):
                self.logger.log_debug(f"중복 텍스트 감지됨: {processed}")
                return None
                
            # 결과 저장 및 반환
            self.recent_texts.append(processed)
            return processed
            
        except Exception as e:
            self.logger.log_error("text_processing", f"텍스트 처리 중 오류: {str(e)}")
            return text  # 오류 시 원본 반환

    def _remove_korean_repetitions(self, text: str) -> str:
        """한국어 반복 구문 추가 검사 및 제거"""
        try:
            words = text.split()
            if len(words) < 6:  # 적은 단어 수는 처리 불필요
                return text
                
            # 반복 윈도우 크기 (2-6어절)
            for window_size in range(2, 7):
                if len(words) < window_size * 2:  # 윈도우 크기의 2배 이상 단어가 있어야 함
                    continue
                    
                i = 0
                result = []
                skip_to = -1
                
                while i < len(words):
                    if i < skip_to:
                        i += 1
                        continue
                        
                    # 현재 위치에서 윈도우 크기만큼의 단어들
                    curr_window = words[i:i+window_size]
                    
                    # 반복 감지
                    repetition_found = False
                    for j in range(i + window_size, len(words) - window_size + 1, window_size):
                        next_window = words[j:j+window_size]
                        
                        # 윈도우가 동일한지 확인
                        if curr_window == next_window:
                            if not repetition_found:  # 첫 번째 윈도우는 저장
                                result.extend(curr_window)
                                repetition_found = True
                            
                            skip_to = j + window_size  # 반복된 부분 건너뛰기
                        else:
                            break
                            
                    if not repetition_found:
                        result.append(words[i])
                        i += 1
                    else:
                        i = skip_to
                
                words = result  # 다음 윈도우 크기 처리를 위해 결과 업데이트
                
            return ' '.join(words)
            
        except Exception as e:
            self.logger.log_error("korean_repetition", f"한국어 반복 구문 처리 중 오류: {str(e)}")
            return text  # 오류 시 원본 반환

    def _is_duplicate(self, text: str) -> bool:
        """텍스트 중복 여부 확인"""
        if not self.recent_texts:
            return False

        # 정확히 일치하는 경우
        if text in self.recent_texts:
            return True

        # 일부만 다른 경우 (80% 이상 유사)
        latest = self.recent_texts[-1]

        # 길이가 크게 다르면 중복 아님
        if abs(len(text) - len(latest)) > min(len(text), len(latest)) * 0.5:
            return False

        # 간단한 유사도 계산 (자카드 유사도)
        words1 = set(text.split())
        words2 = set(latest.split())

        if not words1 or not words2:
            return False

        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        similarity = intersection / union if union > 0 else 0
        return similarity > 0.8  # 80% 이상 유사하면 중복으로 간주

    def is_complete_sentence(self, text: str) -> bool:
        """문장 완성도 확인"""
        # 한국어 문장 종결 확인
        if re.search(self.ko_sentence_end, text):
            return True

        # 영어 문장 종결 확인
        if re.search(r'[.!?]\s*$', text):
            return True

        # 최소 길이 기준
        if len(text) > 30:  # 긴 문장은 완성으로 간주
            return True

        return False

    def combine_texts(self, texts: List[str]) -> str:
        """여러 텍스트 조각을 하나로 결합"""
        if not texts:
            return ""

        # 중복 제거
        unique_texts = []
        for text in texts:
            if text and text not in unique_texts:
                unique_texts.append(text)

        # 결합
        return " ".join(unique_texts)


class WhisperTranscriber:
    """
    Whisper 기반 음성 전사 클래스
    - 오디오 세그먼트의 음성을 텍스트로 변환
    - 언어 감지 및 처리
    - 번역 기능 (옵션)
    """
    def __init__(self, model_name: str = "large-v3", use_faster_whisper: bool = True,
                translator_enabled: bool = True, translate_to: str = 'ko'):
        """Whisper 전사기 초기화"""
        self.logger = LogManager()
        self.logger.log_info(f"Whisper 전사기 초기화 (모델: {model_name})")

        self.model_name = model_name
        self.use_faster_whisper = use_faster_whisper
        self.translator_enabled = translator_enabled
        self.translate_to = translate_to

        self.text_processor = TextProcessor()

        # 번역기 초기화 (옵션)
        self.translator = None
        #if self.translator_enabled:
        #    try:
        #        self.translator = Translator()
        #        self.logger.log_info("Google 번역기가 초기화되었습니다")
        #    except Exception as e:
        #        self.logger.log_error("translator_init", f"번역기 초기화 중 오류: {str(e)}")

        # Whisper 모델 초기화
        self.model = None
        self._init_model()

        # 캐시 및 통계 변수 초기화
        self.cache = {}  # 동일 오디오에 대한 결과 캐싱
        self.stats = {
            'total_processed': 0,
            'cache_hits': 0,
            'avg_processing_time': 0,
            'language_counts': {},
            'success_rate': 1.0
        }

        # 스레드 안전성
        self._lock = threading.Lock()

        self.logger.log_info("Whisper 전사기가 초기화되었습니다")

    def _init_model(self):
        """Whisper 모델 초기화"""
        try:
            # Apple Silicon 확인 - MLX 사용 시도
            if self._is_mac_silicon():
                try:
                    from mlx_whisper import MLXWhisperTranscriber
                    
                    self.logger.log_info("Apple Silicon 감지됨: LightningWhisperMLX 사용")
                    self.model = MLXWhisperTranscriber(model_name=self.model_name)
                    self.use_mlx = True
                    return
                except Exception as e:
                    self.logger.log_warning(f"MLX 모델 초기화 실패, 대체 방법 시도: {str(e)}")
                    self.use_mlx = False
            else:
                self.use_mlx = False
                
            # MLX 사용 실패 시 Faster Whisper 시도
            if self.use_faster_whisper:
                try:
                    from faster_whisper import WhisperModel
                    
                    # 장치 설정
                    compute_type = "float16"  # 기본 설정
                    
                    # 가능하면 GPU 사용
                    try:
                        import torch
                        if torch.cuda.is_available():
                            device = "cuda"
                            self.logger.log_info("CUDA 지원 GPU를 사용합니다")
                        else:
                            device = "cpu"
                            compute_type = "float32"  # CPU에서는 float32 사용
                            self.logger.log_info("CPU를 사용합니다 (GPU 사용 불가)")
                    except ImportError:
                        device = "cpu"
                        compute_type = "float32"  # CPU에서는 float32 사용
                        self.logger.log_info("PyTorch가 설치되지 않았습니다. CPU를 사용합니다.")
                    
                    self.logger.log_info(f"계산 타입: {compute_type}")
                    
                    # 모델 로드
                    self.model = WhisperModel(
                        self.model_name,
                        device=device,
                        compute_type=compute_type
                    )
                    self.logger.log_info(f"Faster Whisper 모델 '{self.model_name}'이 로드되었습니다 (장치: {device})")
                    
                except ImportError:
                    self.logger.log_warning("Faster Whisper를 가져올 수 없습니다. 기본 Whisper로 대체합니다.")
                    self.use_faster_whisper = False
            
            # 기본 Whisper 사용 (다른 모든 옵션 실패 시)
            if not self.use_faster_whisper and not self.use_mlx:
                import whisper
                self.model = whisper.load_model(self.model_name)
                self.logger.log_info(f"Whisper 모델 '{self.model_name}'이 로드되었습니다")
            
        except Exception as e:
            self.logger.log_critical(f"Whisper 모델 초기화 실패: {str(e)}")
            raise RuntimeError(f"Whisper 모델을 초기화할 수 없습니다: {str(e)}")

    def _is_mac_silicon(self) -> bool:
        """Apple Silicon Mac 여부 확인"""
        try:
            import platform
            return (platform.system() == 'Darwin' and
                   (platform.machine() == 'arm64' or 'M1' in platform.processor()))
        except:
            return False

    def process_audio(self, segment: Dict) -> Optional[Dict]:
        """
        오디오 세그먼트 전사 처리

        Args:
            segment: 오디오 데이터 포함 세그먼트 딕셔너리

        Returns:
            전사 결과 딕셔너리 또는 None
        """
        start_time = time.time()
        audio_data = segment.get('audio')

        if audio_data is None or len(audio_data) == 0:
            self.logger.log_warning("전사 처리할 오디오 데이터가 없습니다")
            return None

        # 캐시 키 생성 (오디오 데이터의 해시)
        cache_key = str(hash(audio_data.tobytes()))

        # 캐시 확인
        with self._lock:
            if cache_key in self.cache:
                self.stats['cache_hits'] += 1
                self.logger.log_debug("캐시에서 전사 결과를 찾았습니다")
                return self.cache[cache_key]

        # 전사 처리
        try:
            transcription_result = self._transcribe_audio(audio_data)
            if not transcription_result:
                return None

            # 텍스트 후처리
            processed_text = self.text_processor.process_text(transcription_result.get('text', ''))
            if not processed_text:
                return None

            # 번역 (필요시)
            translation_result = None
            detected_language = transcription_result.get('language', 'unknown')

            #if (self.translator_enabled and self.translator and
            if (self.translator_enabled and
                detected_language != self.translate_to and
                detected_language in SUPPORTED_LANGUAGES):
                try:
                    translation_result = self._translate_text(processed_text, detected_language)
                except Exception as e:
                    self.logger.log_error("translation", f"번역 중 오류: {str(e)}")

            # 결과 생성
            processing_time = time.time() - start_time
            result = {
                'text': processed_text,
                'language': detected_language,
                'language_name': SUPPORTED_LANGUAGES.get(detected_language, detected_language),
                'confidence': transcription_result.get('confidence', 0),
                'duration': processing_time,
                'audio_duration': segment.get('duration', 0),
                'timestamp': time.time()
            }

            # 번역 결과 추가 (있는 경우)
            if translation_result:
                result['translation'] = translation_result

            # 통계 업데이트
            with self._lock:
                self.stats['total_processed'] += 1
                self.stats['avg_processing_time'] = (
                    (self.stats['avg_processing_time'] * (self.stats['total_processed'] - 1) +
                     processing_time) / self.stats['total_processed']
                )

                # 언어별 카운트
                if detected_language in self.stats['language_counts']:
                    self.stats['language_counts'][detected_language] += 1
                else:
                    self.stats['language_counts'][detected_language] = 1

                # 캐시 저장
                self.cache[cache_key] = result

                # 캐시 크기 제한 (최대 100개)
                if len(self.cache) > 100:
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]

            self.logger.log_info(
                f"전사 완료 - 언어: {result['language_name']}, "
                f"길이: {result['audio_duration']:.2f}초, "
                f"처리 시간: {processing_time:.2f}초"
            )

            return result

        except Exception as e:
            self.logger.log_error("transcription", f"전사 중 오류: {str(e)}")

            # 실패 통계 업데이트
            with self._lock:
                self.stats['total_processed'] += 1
                # 성공률 업데이트 (지수 이동 평균)
                self.stats['success_rate'] = 0.9 * self.stats['success_rate']

            return None

    def _transcribe_audio(self, audio_data: np.ndarray) -> Optional[Dict]:
        """Whisper 모델을 사용한 오디오 전사"""
        try:
            # MLX 사용 시 직접 처리
            if hasattr(self, 'use_mlx') and self.use_mlx:
                result = self.model.transcribe(audio_data)
                
                # 결과가 없으면 None 반환
                if not result or not result.get('text'):
                    return None
                    
                return result
                
            # 임시 파일 사용 (메모리 형식에 따른 문제 방지)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as temp_file:
                # float32 -> int16 변환 및 정규화
                audio_int16 = (audio_data * 32767).astype(np.int16)
                
                # NumPy 배열을 파일로 저장
                import wave
                with wave.open(temp_file.name, 'wb') as wf:
                    wf.setnchannels(1)  # 모노
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(16000)  # 16kHz
                    wf.writeframes(audio_int16.tobytes())
                
                # Faster Whisper 사용
                if self.use_faster_whisper:
                    return self._transcribe_with_faster_whisper(temp_file.name)
                # 일반 Whisper 사용
                else:
                    return self._transcribe_with_whisper(temp_file.name)
                
        except Exception as e:
            self.logger.log_error("whisper_transcribe", f"Whisper 전사 중 오류: {str(e)}")
            return None

    def _transcribe_with_faster_whisper(self, audio_file: str) -> Optional[Dict]:
        """Faster Whisper 라이브러리로 전사"""
        try:
            segments, info = self.model.transcribe(
                audio_file,
                beam_size=5,
                word_timestamps=False,
                language=None,  # 자동 감지
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)  # 0.5초 이상의 묵음 제거
            )

            # 세그먼트 텍스트 모으기
            texts = []
            for segment in segments:
                texts.append(segment.text)

            full_text = " ".join(texts).strip()

            # 결과가 없으면 None 반환
            if not full_text:
                return None

            # 결과 구성
            result = {
                'text': full_text,
                'language': info.language,
                'confidence': info.language_probability
            }

            return result

        except Exception as e:
            self.logger.log_error("faster_whisper", f"Faster Whisper 전사 중 오류: {str(e)}")
            return None

    def _transcribe_with_whisper(self, audio_file: str) -> Optional[Dict]:
        """일반 Whisper 라이브러리로 전사"""
        try:
            result = self.model.transcribe(audio_file)

            # 결과가 없으면 None 반환
            if not result or not result.get('text'):
                return None

            # 결과 구성
            return {
                'text': result['text'],
                'language': result['language'],
                'confidence': 1.0  # 기본 Whisper는 신뢰도 제공 안함
            }

        except Exception as e:
            self.logger.log_error("whisper", f"Whisper 전사 중 오류: {str(e)}")
            return None

    def _translate_text(self, text: str, source_lang: str = None) -> Optional[Dict]:
        """Google Translate로 텍스트 번역"""
        try:
            start_time = time.time()
            
            # source_lang이 'unknown'이면 'auto'로 설정
            src_lang = 'auto' if source_lang == 'unknown' else source_lang
            
            # deep-translator를 사용한 번역
            translator = GoogleTranslator(source=src_lang, target=self.translate_to)
            translated_text = translator.translate(text)
            
            translation_time = time.time() - start_time
    
            if translated_text:
                return {
                    'text': translated_text,
                    'source_lang': source_lang,
                    'target_lang': self.translate_to,
                    'duration': translation_time
                }
            return None
    
        except Exception as e:
            self.logger.log_error("translation", f"번역 중 오류: {str(e)}")
            return None

    def get_stats(self) -> Dict:
        """전사기 통계 정보 반환"""
        with self._lock:
            stats_copy = self.stats.copy()
            # 캐시 사용률 추가
            stats_copy['cache_usage'] = len(self.cache)
            stats_copy['cache_hit_ratio'] = (
                stats_copy['cache_hits'] / stats_copy['total_processed']
                if stats_copy['total_processed'] > 0 else 0
            )
            return stats_copy

    def set_translate_language(self, language_code: str) -> bool:
        """번역 대상 언어 설정"""
        if language_code in SUPPORTED_LANGUAGES:
            self.translate_to = language_code
            self.logger.log_info(f"번역 대상 언어가 변경되었습니다: {SUPPORTED_LANGUAGES[language_code]}")
            return True
        self.logger.log_warning(f"지원되지 않는 언어 코드: {language_code}")
        return False


class TranscriptionManager:
    """
    전사 관리 클래스
    - 오디오 세그먼트 처리 조정
    - 결과 관리 및 필터링
    - 세션 컨텍스트 유지
    """
    def __init__(self, model_name: str = "large-v3", use_faster_whisper: bool = True,
                translator_enabled: bool = True, translate_to: str = 'ko'):
        """전사 관리자 초기화"""
        self.logger = LogManager()
        self.logger.log_info("전사 관리자 초기화")

        # 전사기 초기화
        self.transcriber = WhisperTranscriber(
            model_name=model_name,
            use_faster_whisper=use_faster_whisper,
            translator_enabled=translator_enabled,
            translate_to=translate_to
        )

        # 세션 정보
        self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start_time = time.time()

        # 결과 기록
        self.transcription_history = []  # 최근 전사 결과 기록
        self.max_history = 100  # 최대 기록 수

        # 스레드 안전성
        self._lock = threading.Lock()

        self.logger.log_info(f"전사 세션 시작: {self.session_id}")

    def process_segment(self, segment: Dict) -> Optional[Dict]:
        """
        오디오 세그먼트 처리 및 전사

        Args:
            segment: 오디오 세그먼트 데이터

        Returns:
            전사 결과 또는 None
        """
        try:
            # 전사 처리
            result = self.transcriber.process_audio(segment)
            if not result:
                return None

            # 결과 기록 추가
            with self._lock:
                self.transcription_history.append(result)
                # 최대 기록 수 제한
                if len(self.transcription_history) > self.max_history:
                    self.transcription_history.pop(0)

            return result

        except Exception as e:
            self.logger.log_error("segment_processing", f"세그먼트 처리 중 오류: {str(e)}")
            return None

    def get_recent_transcriptions(self, count: int = 5) -> List[Dict]:
        """최근 전사 결과 반환"""
        with self._lock:
            return self.transcription_history[-count:] if self.transcription_history else []

    def get_session_transcript(self) -> str:
        """현재 세션의 전체 전사 결과 텍스트 반환"""
        with self._lock:
            texts = [item['text'] for item in self.transcription_history if 'text' in item]
            return "\n".join(texts)

    def get_statistics(self) -> Dict:
        """전사 관리자 및 전사기 통계 반환"""
        transcriber_stats = self.transcriber.get_stats()

        stats = {
            'session_id': self.session_id,
            'session_duration': time.time() - self.session_start_time,
            'total_transcriptions': len(self.transcription_history),
            'transcriber': transcriber_stats
        }

        return stats

    def save_transcript(self, filename: str) -> bool:
        """현재 세션의 전사 결과를 파일로 저장"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                # 세션 정보 헤더
                session_info = {
                    'session_id': self.session_id,
                    'start_time': datetime.datetime.fromtimestamp(self.session_start_time).strftime("%Y-%m-%d %H:%M:%S"),
                    'end_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'duration': time.time() - self.session_start_time,
                    'total_items': len(self.transcription_history)
                }

                # JSON 형식으로 저장
                json.dump({
                    'session_info': session_info,
                    'transcriptions': self.transcription_history
                }, f, ensure_ascii=False, indent=2)

            self.logger.log_info(f"전사 결과가 저장되었습니다: {filename}")
            return True

        except Exception as e:
            self.logger.log_error("save_transcript", f"전사 결과 저장 중 오류: {str(e)}")
            return False

    def export_text(self, filename: str, include_translations: bool = True) -> bool:
        """텍스트 형식으로 전사 결과 내보내기"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                # 헤더 정보
                f.write(f"# 전사 세션: {self.session_id}\n")
                f.write(f"# 날짜: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                # 전사 내용
                for idx, item in enumerate(self.transcription_history, 1):
                    timestamp = datetime.datetime.fromtimestamp(item.get('timestamp', 0)).strftime("%H:%M:%S")
                    language = item.get('language_name', '알 수 없음')

                    f.write(f"[{idx}] {timestamp} [{language}]\n")
                    f.write(f"{item.get('text', '')}\n")

                    # 번역 포함 (옵션)
                    if include_translations and 'translation' in item:
                        f.write(f"번역: {item['translation']['text']}\n")

                    f.write("\n")

            self.logger.log_info(f"텍스트 형식으로 내보내기 완료: {filename}")
            return True

        except Exception as e:
            self.logger.log_error("export_text", f"텍스트 내보내기 중 오류: {str(e)}")
            return False

    def reset_session(self):
        """현재 세션 초기화 (기록 삭제)"""
        with self._lock:
            self.transcription_history.clear()
            self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_start_time = time.time()

        self.logger.log_info(f"세션이 초기화되었습니다. 새 세션 ID: {self.session_id}")
