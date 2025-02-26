import numpy as np
import webrtcvad
import collections
import struct
import time
import threading
from typing import Dict, Optional, List, Tuple, Deque
from logging_utils import LogManager

class AudioSegmenter:
    """
    오디오 세그멘테이션 클래스
    - 음성/비음성 구간 감지
    - 일정 길이의 음성 세그먼트 구성
    - 적절한 문장 단위 분리
    """
    def __init__(self, sample_rate: int = 16000):
        """오디오 세그멘터 초기화"""
        self.logger = LogManager()
        self.logger.log_info(f"오디오 세그멘터 초기화 (샘플레이트: {sample_rate}Hz)")

        self.sample_rate = sample_rate

        # VAD 초기화 (0-3 범위의 모드, 높을수록 더 엄격한 음성 감지)
        self.vad_mode = 1  # 중간 정도의 엄격성
        self.vad = webrtcvad.Vad(self.vad_mode)

        # 프레임 크기 및 지속시간 설정
        self.frame_duration_ms = 30  # 30ms (WebRTC VAD의 표준 프레임 크기)
        self.frame_size = int(sample_rate * self.frame_duration_ms / 1000)
        self.logger.log_debug(f"프레임 크기: {self.frame_size} 샘플 ({self.frame_duration_ms}ms)")

        # 세그먼트 설정
        self.config = {
            'min_segment_duration': 1.0,       # 최소 세그먼트 길이 (초)
            'max_segment_duration': 10.0,      # 기본 최대 세그먼트 길이 (초)
            'absolute_max_duration': 15.0,     # 절대 최대 세그먼트 길이 (초) - 새로 추가
            'speech_pad_duration': 0.3,        # 음성 전후 패딩 (초)
            'min_speech_duration': 0.3,        # 최소 음성 인식 길이 (초)
            'silence_threshold': 0.3,          # 묵음 간주할 임계값 (초)
            'max_silence_length': 1.5,         # 세그먼트 내 허용 묵음 길이 (초)
            'energy_threshold': 0.001,         # 음성 에너지 임계값
            'energy_boost_threshold': 0.01,    # 에너지 기반 음성 감지 부스트 임계값
            'adaptive_segmentation': True      # 적응형 세그먼테이션 활성화 - 새로 추가
        }

        # 샘플 단위로 변환
        self.min_segment_samples = int(self.config['min_segment_duration'] * sample_rate)
        self.max_segment_samples = int(self.config['max_segment_duration'] * sample_rate)
        self.absolute_max_samples = int(self.config['absolute_max_duration'] * sample_rate)  # 새로 추가
        self.speech_pad_samples = int(self.config['speech_pad_duration'] * sample_rate)
        self.min_speech_samples = int(self.config['min_speech_duration'] * sample_rate)
        self.min_speech_frames = int(self.config['min_speech_duration'] * 1000 / self.frame_duration_ms)
        self.silence_threshold_frames = int(self.config['silence_threshold'] * 1000 / self.frame_duration_ms)
        self.max_silence_frames = int(self.config['max_silence_length'] * 1000 / self.frame_duration_ms)


        # 상태 변수 초기화
        self.reset_state()

        # 로깅
        self.logger.log_info(
            f"세그멘터 설정 - 최소 길이: {self.config['min_segment_duration']}초, "
            f"최대 길이: {self.config['max_segment_duration']}초, "
            f"절대 최대 길이: {self.config['absolute_max_duration']}초, "  # 로그에도 추가
            f"VAD 모드: {self.vad_mode}"
        )

    def reset_state(self):
        """상태 변수 초기화"""
        # 버퍼 및 상태 변수
        self.audio_buffer = collections.deque(maxlen=self.absolute_max_samples)  # 여기를 수정
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speech_active = False
        self.current_segment_frames = 0
        self.triggered = False
        self.voiced_frames = []
        self.last_voiced_frame_time = 0
        self.stats = {
            'total_segments': 0,
            'avg_segment_duration': 0,
            'speech_ratio': 0
        }

        self.logger.log_debug("세그멘터 상태가 초기화되었습니다")

    def _frame_to_bytes(self, frame: np.ndarray) -> bytes:
        """float32 오디오 프레임을 int16 바이트로 변환 (VAD용)"""
        # float32 -> int16 변환 (VAD는 int16 요구)
        frame_int16 = (frame * 32767).astype(np.int16)
        return frame_int16.tobytes()

    def _is_speech(self, frame: np.ndarray, energy: float) -> bool:
        """주어진 프레임이 음성인지 판단"""
        try:
            # 에너지가 매우 낮으면 즉시 비음성으로 판단
            if energy < self.config['energy_threshold']:
                return False

            # 에너지가 매우 높으면 VAD와 상관없이 음성으로 판단
            if energy > self.config['energy_boost_threshold']:
                return True

            # WebRTC VAD 사용한 음성 감지
            frame_bytes = self._frame_to_bytes(frame)
            return self.vad.is_speech(frame_bytes, self.sample_rate)
        except Exception as e:
            self.logger.log_error("vad_processing", f"VAD 처리 중 오류: {str(e)}")
            # 오류 발생 시 에너지만으로 판단
            return energy > self.config['energy_threshold']

    def process_chunk(self, audio_chunk: np.ndarray, energy: float) -> Optional[Dict]:
        """
        오디오 청크 처리 및 세그먼트 관리

        Args:
            audio_chunk: 오디오 데이터 (float32 numpy 배열)
            energy: 오디오 청크의 에너지 레벨

        Returns:
            완성된 세그먼트가 있는 경우 세그먼트 정보 포함한 딕셔너리, 없으면 None
        """
        try:
            # 버퍼에 오디오 추가
            for sample in audio_chunk:
                self.audio_buffer.append(sample)

            # 프레임 단위 처리를 위한 분할
            frames = []
            frame_count = len(audio_chunk) // self.frame_size
            for i in range(frame_count):
                start_idx = i * self.frame_size
                end_idx = start_idx + self.frame_size
                if end_idx <= len(audio_chunk):
                    frames.append(audio_chunk[start_idx:end_idx])

            # 각 프레임 분석
            for frame in frames:
                frame_energy = np.sqrt(np.mean(np.square(frame)))
                is_speech = self._is_speech(frame, frame_energy)

                if is_speech:
                    self.speech_frames += 1
                    self.silence_frames = 0
                    if not self.is_speech_active:
                        self.is_speech_active = True
                        self.logger.log_debug(f"음성 시작 감지 (에너지: {frame_energy:.6f})")

                    # 음성 프레임 저장
                    self.voiced_frames.append(True)
                    self.last_voiced_frame_time = time.time()
                else:
                    self.silence_frames += 1
                    if self.is_speech_active and self.silence_frames > self.silence_threshold_frames:
                        self.is_speech_active = False
                        self.logger.log_debug(f"음성 종료 감지 (묵음 프레임: {self.silence_frames})")

                    # 묵음 프레임 저장
                    self.voiced_frames.append(False)

                self.current_segment_frames += 1

                # 세그먼트 완료 조건 체크
                segment_result = self._check_segment_complete()
                if segment_result:
                    return segment_result

            return None

        except Exception as e:
            self.logger.log_error("chunk_processing", f"청크 처리 중 오류: {str(e)}")
            return None

    def _check_segment_complete(self) -> Optional[Dict]:
        """세그먼트 완료 조건 확인"""
        try:
            # 세그먼트가 없으면 체크할 필요 없음
            if len(self.audio_buffer) < self.min_segment_samples:
                return None
                
                
            # 음성 비율 계산 (최근 100 프레임)
            recent_frames = min(len(self.voiced_frames), 100)
            if recent_frames > 0:
                recent_voice_ratio = sum(self.voiced_frames[-recent_frames:]) / recent_frames
            else:
                recent_voice_ratio = 0

            # 디버그 정보 로깅
            self.logger.log_debug(
                f"상태 - 음성활성: {self.is_speech_active}, "
                f"묵음프레임: {self.silence_frames} / {self.max_silence_frames}, "
                f"음성인식프레임: {self.speech_frames} / {self.min_speech_frames} ,"
                f"최근음성비율: {recent_voice_ratio:.3f}"
            )
    
            # 1. 발화 종료 후 충분한 묵음 감지 (가장 중요한 조건)
            if (not self.is_speech_active and
                self.speech_frames > self.min_speech_frames and
                self.silence_frames > self.max_silence_frames):
                self.logger.log_info(f"충분한 묵음 감지됨 (묵음 프레임: {self.silence_frames})")
                return self._finalize_segment("silence")
                
            # 2. 절대 최대 길이 도달 - 무조건 세그먼트 완료
            if len(self.audio_buffer) >= self.absolute_max_samples:
                self.logger.log_debug("절대 최대 세그먼트 길이에 도달")
                return self._finalize_segment("absolute_max_length")
                
            # 3. 기본 최대 길이에 도달했지만 현재 활발한 발화 중인 경우 추가 시간 허용
            if len(self.audio_buffer) >= self.max_segment_samples:
                # 현재 활발히 말하고 있는 경우 계속 진행 (절대 최대까지)
                if self.is_speech_active and self.config.get('adaptive_segmentation', False):
                    return None
                    
                self.logger.log_debug("기본 최대 세그먼트 길이에 도달")
                return self._finalize_segment("max_length")
                
            # 4. 마지막 음성 감지 후 일정 시간 경과 (타임아웃)
            if (self.speech_frames > self.min_speech_samples and
                time.time() - self.last_voiced_frame_time > self.config['silence_threshold']):
                self.logger.log_info("음성 감지 타임아웃")
                return self._finalize_segment("timeout")
    
            return None
            
        except Exception as e:
            self.logger.log_error("segment_check", f"세그먼트 완료 확인 중 오류: {str(e)}")
            return None

    def _finalize_segment(self, reason: str) -> Dict:
        """현재 버퍼의 오디오를 세그먼트로 완성"""
        try:
            # 음성 활동 비율 계산
            voiced_ratio = sum(self.voiced_frames) / len(self.voiced_frames) if self.voiced_frames else 0

            # 통계 업데이트
            segment_duration = len(self.audio_buffer) / self.sample_rate
            self.stats['total_segments'] += 1
            self.stats['avg_segment_duration'] = (
                (self.stats['avg_segment_duration'] * (self.stats['total_segments'] - 1) +
                 segment_duration) / self.stats['total_segments']
            )
            self.stats['speech_ratio'] = (
                (self.stats['speech_ratio'] * (self.stats['total_segments'] - 1) +
                 voiced_ratio) / self.stats['total_segments']
            )

            # 세그먼트 정보 생성
            segment = {
                'audio': np.array(list(self.audio_buffer)),
                'duration': segment_duration,
                'speech_ratio': voiced_ratio,
                'reason': reason,
                'sample_count': len(self.audio_buffer),
                'timestamp': time.time()
            }

            self.logger.log_info(
                f"세그먼트 완료 - 길이: {segment_duration:.2f}초, "
                f"샘플 수: {len(self.audio_buffer)}, "
                f"음성 비율: {voiced_ratio:.3f}, "
                f"원인: {reason}"
            )

            # 상태 초기화
            self.reset_state()

            return segment

        except Exception as e:
            self.logger.log_error("segment_finalization", f"세그먼트 완료 처리 중 오류: {str(e)}")
            self.reset_state()
            return {
                'audio': np.array([]),
                'duration': 0,
                'speech_ratio': 0,
                'reason': 'error',
                'sample_count': 0,
                'timestamp': time.time()
            }

    def get_stats(self) -> Dict:
        """세그멘터 통계 정보 반환"""
        return self.stats

    def update_config(self, new_config: Dict) -> None:
        """세그멘터 설정 업데이트"""
        for key, value in new_config.items():
            if key in self.config:
                self.config[key] = value

        # 샘플 단위 값 재계산
        self.min_segment_samples = int(self.config['min_segment_duration'] * self.sample_rate)
        self.max_segment_samples = int(self.config['max_segment_duration'] * self.sample_rate)
        self.speech_pad_samples = int(self.config['speech_pad_duration'] * self.sample_rate)
        self.min_speech_samples = int(self.config['min_speech_duration'] * self.sample_rate)
        self.silence_threshold_frames = int(self.config['silence_threshold'] * 1000 / self.frame_duration_ms)
        self.max_silence_frames = int(self.config['max_silence_length'] * 1000 / self.frame_duration_ms)

        self.logger.log_info("세그멘터 설정이 업데이트되었습니다")


class AudioProcessor:
    """
    오디오 처리 클래스
    - 오디오 데이터 전처리
    - 음성 활동 감지 관리
    - 세그먼트 구성 및 큐 관리
    """
    def __init__(self, sample_rate: int = 16000):
        """오디오 프로세서 초기화"""
        self.logger = LogManager()
        self.logger.log_info(f"오디오 프로세서 초기화 (샘플레이트: {sample_rate}Hz)")

        self.sample_rate = sample_rate
        self.segmenter = AudioSegmenter(sample_rate)

        # 상태 정보
        self.processed_chunks = 0
        self.segments_created = 0
        self.is_calibrating = True
        self.calibration_samples = []
        self.calibration_count = 10  # 캘리브레이션 필요 청크 수

        # 오디오 통계용 윈도우 버퍼
        self.energy_window = collections.deque(maxlen=20)  # 약 0.6초 에너지 흐름

        self.logger.log_info("오디오 프로세서가 초기화되었습니다")

    def process_audio(self, audio_data: Dict) -> Optional[Dict]:
        """
        오디오 데이터 처리 및 세그먼트 관리

        Args:
            audio_data: 오디오 데이터 정보가 포함된 딕셔너리
                - audio: float32 numpy 배열
                - energy: 오디오 에너지 레벨
                - timestamp: 오디오 캡처 시간

        Returns:
            완성된 오디오 세그먼트 또는 None
        """
        try:
            self.processed_chunks += 1

            # 오디오 데이터 추출
            audio_chunk = audio_data['audio']
            energy = audio_data['energy']

            # 에너지 레벨 저장
            self.energy_window.append(energy)

            # 캘리브레이션 단계 (초기 환경 노이즈 레벨 파악)
            if self.is_calibrating:
                self.calibration_samples.append(energy)
                if len(self.calibration_samples) >= self.calibration_count:
                    self._complete_calibration()
                return None

            # 오디오 세그먼테이션
            segment = self.segmenter.process_chunk(audio_chunk, energy)

            if segment is not None and segment['sample_count'] > 0:
                self.segments_created += 1
                self.logger.log_debug(f"세그먼트 생성됨 ({self.segments_created}번째) - 길이: {segment['duration']:.2f}초")

                # 추가 정보 첨부
                segment['average_energy'] = np.mean(self.energy_window) if self.energy_window else 0
                segment['id'] = self.segments_created

                # 세그먼트 유효성 확인
                if segment['duration'] < 0.5:# or segment['speech_ratio'] < 0.1:
                    self.logger.log_info(f"너무 짧거나 음성 비율이 낮은 세그먼트 무시 (길이: {segment['duration']:.2f}초, 음성 비율: {segment['speech_ratio']:.2f})")
                    return None

                return segment

            return None

        except Exception as e:
            self.logger.log_error("audio_processing", f"오디오 처리 중 오류: {str(e)}")
            return None

    def _complete_calibration(self):
        """캘리브레이션 완료 및 설정 조정"""
        try:
            # 환경 노이즈 레벨 추정
            avg_energy = np.mean(self.calibration_samples)
            energy_std = np.std(self.calibration_samples)

            # 에너지 임계값 자동 조정
            # 평균 + 1 표준편차를 기본 임계값으로 설정
            threshold = avg_energy + energy_std
            boost_threshold = avg_energy + 2 * energy_std

            # 임계값 하한선 설정
            threshold = max(threshold, 0.001)
            boost_threshold = max(boost_threshold, 0.005)

            # 세그멘터 설정 업데이트
            self.segmenter.update_config({
                'energy_threshold': threshold,
                'energy_boost_threshold': boost_threshold
            })

            self.is_calibrating = False
            self.logger.log_info(
                f"캘리브레이션 완료 - 평균 환경 에너지: {avg_energy:.6f}, "
                f"임계값: {threshold:.6f}, 부스트 임계값: {boost_threshold:.6f}"
            )
            print(f"\n[캘리브레이션 완료] 기본 에너지 임계값: {threshold:.6f}")

        except Exception as e:
            self.logger.log_error("calibration", f"캘리브레이션 중 오류: {str(e)}")
            self.is_calibrating = False

    def get_stats(self) -> Dict:
        """프로세서 상태 정보 반환"""
        segmenter_stats = self.segmenter.get_stats()
        stats = {
            'processed_chunks': self.processed_chunks,
            'segments_created': self.segments_created,
            'average_energy': np.mean(self.energy_window) if self.energy_window else 0,
            'segmenter': segmenter_stats
        }
        return stats

    def reset(self):
        """상태 초기화"""
        self.segmenter.reset_state()
        self.energy_window.clear()
        self.logger.log_info("오디오 프로세서 상태가 초기화되었습니다")
