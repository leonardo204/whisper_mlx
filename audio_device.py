import numpy as np
import pyaudio
import wave
import os
import time
import threading
from typing import Optional, List, Dict, Tuple
from logging_utils import LogManager

class AudioDevice:
    """
    오디오 장치 관리 클래스
    - 사용 가능한 오디오 장치 검색
    - 장치 선택 및 검증
    - 오디오 설정 구성
    """
    def __init__(self):
        """오디오 장치 관리자 초기화"""
        self.logger = LogManager()
        self.logger.log_info("오디오 장치 관리자를 초기화합니다")

        try:
            self.audio = pyaudio.PyAudio()
            self._device_info = None
            self._sample_rate = 16000  # Whisper 최적 샘플레이트
            self._channels = 1         # 모노 채널
            self._format = pyaudio.paFloat32  # 32비트 부동 소수점 형식
            self._chunk_size = int(self._sample_rate * 0.03)  # 30ms 청크
        except Exception as e:
            self.logger.log_critical(f"PyAudio 초기화 실패: {str(e)}")
            raise

    def list_devices(self) -> List[Dict]:
        """사용 가능한 모든 오디오 장치 목록 반환"""
        devices = []
        try:
            info = self.audio.get_host_api_info_by_index(0)
            num_devices = info.get('deviceCount')

            self.logger.log_info(f"사용 가능한 장치 수: {num_devices}")
            print("\n사용 가능한 오디오 장치:")

            for i in range(num_devices):
                try:
                    device_info = self.audio.get_device_info_by_host_api_device_index(0, i)
                    device_name = device_info.get('name')
                    max_input_channels = device_info.get('maxInputChannels')

                    # 입력 채널이 있는 장치만 추가
                    if max_input_channels > 0:
                        # Loopback 장치 확인 (시스템 오디오 캡처용)
                        is_loopback = 'Loopback' in device_name or 'loopback' in device_name.lower() or '루프백' in device_name

                        device_data = {
                            'index': i,
                            'name': device_name,
                            'channels': max_input_channels,
                            'is_loopback': is_loopback,
                            'default_sample_rate': int(device_info.get('defaultSampleRate'))
                        }

                        devices.append(device_data)
                        print(f"{i}: {device_name} {'(Loopback)' if is_loopback else ''} - {max_input_channels}채널")
                        self.logger.log_debug(f"장치 {i} 정보: {device_data}")

                except Exception as e:
                    self.logger.log_error("device_info", f"장치 {i} 정보 조회 중 오류: {str(e)}")

        except Exception as e:
            self.logger.log_error("list_devices", f"장치 목록 조회 중 오류: {str(e)}")

        return devices

    def validate_device(self, device_index: int) -> bool:
        """선택한 장치가 유효한지 확인"""
        try:
            device_info = self.audio.get_device_info_by_host_api_device_index(0, device_index)
            if not device_info:
                self.logger.log_warning(f"장치 인덱스 {device_index}에 대한 정보를 찾을 수 없습니다")
                return False

            # 기본 검증
            if device_info.get('maxInputChannels', 0) <= 0:
                self.logger.log_warning(f"장치 {device_index}는 입력 채널이 없습니다")
                return False

            # 샘플레이트 호환성 확인
            default_rate = int(device_info.get('defaultSampleRate', 44100))
            if default_rate < 16000:
                self.logger.log_warning(f"장치의 기본 샘플레이트({default_rate}Hz)가 권장값(16000Hz)보다 낮습니다")
                # 낮은 샘플레이트도 사용은 가능하므로 경고만 출력

            # 테스트 스트림 생성
            try:
                test_stream = self.audio.open(
                    format=self._format,
                    channels=1,  # 모노로 강제
                    rate=16000,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=self._chunk_size,
                    start=False
                )
                test_stream.close()
                self._device_info = device_info
                self.logger.log_info(f"장치 {device_index} 검증 성공")
                return True
            except Exception as e:
                self.logger.log_error("device_test", f"장치 테스트 실패: {str(e)}")
                print(f"\n장치 테스트 실패: {e}")
                return False

        except Exception as e:
            self.logger.log_error("device_validation", f"장치 검증 중 오류 발생: {str(e)}")
            print(f"\n장치 검증 중 오류 발생: {e}")
            return False

    def select_device(self) -> Optional[int]:
        """사용자로부터 오디오 장치 선택 받기"""
        devices = self.list_devices()
        
        # 기본 마이크 정보 표시 (자동 선택하지는 않음)
        try:
            default_input = self.audio.get_default_input_device_info()
            if default_input:
                default_index = default_input.get('index')
                default_name = default_input.get('name')
                print(f"\n기본 입력 장치: {default_index} - {default_name}")
                print("기본 장치를 사용하려면 해당 번호를 입력하세요.")
        except Exception as e:
            self.logger.log_debug(f"기본 장치 정보 가져오기 실패: {str(e)}")
        
        # 사용자 선택 처리
        try:
            while True:
                try:
                    user_input = input("\n장치 인덱스를 선택하세요 (출력 캡처의 경우 루프백 장치): ").strip()
                    
                    if not user_input:
                        print("장치를 선택해주세요.")
                        continue
                        
                    device_index = int(user_input)
                    if self.validate_device(device_index):
                        self._configure_device(device_index)
                        self.logger.log_info(f"장치 {device_index} 선택됨")
                        return device_index
                    
                    self.logger.log_warning(f"잘못된 장치 인덱스: {device_index}")
                    print("\n잘못된 장치 인덱스입니다. 다시 시도해주세요.")
                    
                except ValueError:
                    self.logger.log_warning("숫자가 아닌 장치 인덱스 입력됨")
                    print("\n숫자를 입력해주세요.")
                    
        except KeyboardInterrupt:
            self.logger.log_info("사용자가 장치 선택을 취소했습니다")
            print("\n장치 선택이 취소되었습니다.")
            return None

    def _configure_device(self, device_index: int):
        """선택된 장치에 대한 최적 설정 구성"""
        device_info = self._device_info

        # 샘플레이트 설정
        default_rate = int(device_info.get('defaultSampleRate', 44100))
        if default_rate >= 16000:
            self._sample_rate = 16000  # Whisper 모델 최적 샘플레이트
        else:
            self._sample_rate = default_rate
            self.logger.log_warning(f"최적 샘플레이트보다 낮은 값({default_rate}Hz)을 사용합니다")

        # 채널 설정
        max_channels = device_info.get('maxInputChannels', 1)
        self._channels = 1  # 모노로 강제

        # 청크 크기 조정
        self._chunk_size = int(self._sample_rate * 0.03)  # 30ms 기준

        self.logger.log_info(f"장치 구성 완료 - 샘플레이트: {self._sample_rate}Hz, 채널: {self._channels}, 청크 크기: {self._chunk_size}")
        print(f"\n설정된 샘플레이트: {self._sample_rate}Hz")
        print(f"설정된 채널: {self._channels} (모노)")
        print(f"청크 크기: {self._chunk_size} 샘플")

    def get_config(self) -> Dict:
        """현재 오디오 설정 반환"""
        return {
            'sample_rate': self._sample_rate,
            'channels': self._channels,
            'format': self._format,
            'chunk_size': self._chunk_size
        }

    def __del__(self):
        """소멸자: 리소스 정리"""
        try:
            if hasattr(self, 'audio'):
                self.audio.terminate()
                self.logger.log_info("오디오 장치 리소스가 정리되었습니다")
        except Exception as e:
            self.logger.log_error("cleanup", f"리소스 정리 중 오류 발생: {str(e)}")


class AudioRecorder:
    """
    오디오 녹음 클래스
    - 스트림 관리
    - 오디오 청크 처리
    - 기본적인 전처리
    """
    def __init__(self, device_index: int, config: Dict):
        """오디오 레코더 초기화"""
        self.logger = LogManager()
        self.logger.log_info(f"오디오 레코더 초기화 (장치 인덱스: {device_index})")

        try:
            self.device_index = device_index
            self.config = config
            self.audio = pyaudio.PyAudio()

            # 청크 크기 사용
            self.chunk_size = config.get('chunk_size', 1024)
            self.sample_rate = config.get('sample_rate', 16000)
            self.channels = config.get('channels', 1)
            self.format = config.get('format', pyaudio.paFloat32)

            self.logger.log_info(f"설정 - 샘플레이트: {self.sample_rate}, 청크 크기: {self.chunk_size}")

            # 스트림 상태 모니터링
            self.stream_status = {
                'overflows': 0,
                'chunks_processed': 0,
                'last_timestamp': time.time(),
                'avg_processing_time': 0
            }

            # 기본 에너지 임계값 설정
            self.energy_threshold = 0.01  # RMS 에너지 임계값 (0-1 범위)

        except Exception as e:
            self.logger.log_error("initialization", f"레코더 초기화 중 오류 발생: {str(e)}")
            raise

    def _create_stream(self):
        """오디오 스트림 생성"""
        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=None
            )
            self.logger.log_info("오디오 스트림이 성공적으로 생성되었습니다")
            return stream
        except Exception as e:
            self.logger.log_error("stream_creation", f"스트림 생성 중 오류 발생: {str(e)}")
            raise

    def _update_status(self, process_time: float):
        """스트림 상태 업데이트"""
        try:
            self.stream_status['chunks_processed'] += 1
    
            # 평균 처리 시간 업데이트
            alpha = 0.1  # 평활화 계수
            self.stream_status['avg_processing_time'] = (
                (1 - alpha) * self.stream_status['avg_processing_time'] +
                alpha * process_time
            )
    
            # 주기적 상태 출력 (100 청크마다)
            if self.stream_status['chunks_processed'] % 100 == 0:
                # _print_status() 호출 부분 제거 (불필요)
                self.logger.log_debug(
                    f"처리 상태 - 청크: {self.stream_status['chunks_processed']}, "
                    f"평균 처리 시간: {self.stream_status['avg_processing_time']*1000:.1f}ms"
                )
        except Exception as e:
            self.logger.log_error("status_update", f"상태 업데이트 중 오류: {str(e)}")

    def _print_status(self):
        """현재 상태 출력 (debug log level에서만)"""
        avg_time = self.stream_status['avg_processing_time'] * 1000  # ms로 변환
        
        # 로그 시스템을 통해 debug 레벨로 출력
        self.logger.log_debug(
            f"처리 상태 - 청크: {self.stream_status['chunks_processed']}, "
            f"평균 처리 시간: {avg_time:.1f}ms"
        )

    def _preprocess_audio(self, audio_chunk: np.ndarray) -> np.ndarray:
        """최소한의 오디오 전처리 적용"""
        try:
            # 간단한 DC offset 제거 (평균값 제거)
            audio_chunk = audio_chunk - np.mean(audio_chunk)

            # 클리핑 방지를 위한 정규화 (과도한 볼륨 줄이기)
            max_val = np.max(np.abs(audio_chunk))
            if max_val > 0.95:  # 클리핑 임계값
                audio_chunk = audio_chunk * (0.95 / max_val)

            return audio_chunk

        except Exception as e:
            self.logger.log_error("preprocessing", f"전처리 중 오류: {str(e)}")
            return audio_chunk  # 오류 시 원본 반환

    def calculate_energy(self, audio_chunk: np.ndarray) -> float:
        """오디오 에너지 레벨 계산"""
        try:
            if len(audio_chunk) == 0:
                return 0.0
            # RMS(Root Mean Square) 에너지 계산
            return np.sqrt(np.mean(np.square(audio_chunk)))
        except Exception as e:
            self.logger.log_error("energy_calculation", f"에너지 계산 중 오류: {str(e)}")
            return 0.0

    def record(self, queue, stop_event: threading.Event) -> None:
        """오디오 녹음 및 큐에 추가"""
        try:
            stream = self._create_stream()
            self.logger.log_info("녹음을 시작합니다")
            print("\n녹음을 시작합니다...")

            while not stop_event.is_set():
                try:
                    # 오디오 데이터 읽기
                    process_start = time.time()
                    data = stream.read(self.chunk_size, exception_on_overflow=False)

                    # float32로 변환
                    if self.format == pyaudio.paInt16:
                        audio_chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    else:  # 이미 float32인 경우
                        audio_chunk = np.frombuffer(data, dtype=np.float32)

                    # 간단한 전처리
                    processed_chunk = self._preprocess_audio(audio_chunk)

                    # 에너지 레벨 계산
                    energy = self.calculate_energy(processed_chunk)

                    # 큐에 추가
                    queue.put({
                        'audio': processed_chunk,
                        'energy': energy,
                        'timestamp': time.time()
                    })

                    # 상태 업데이트
                    process_time = time.time() - process_start
                    self._update_status(process_time)

                except IOError as e:
                    self.stream_status['overflows'] += 1
                    self.logger.log_warning(f"버퍼 오버플로우 발생 ({self.stream_status['overflows']}번째)")
                    continue

                except Exception as e:
                    self.logger.log_error("recording", f"녹음 중 예외 발생: {str(e)}")
                    break

        except Exception as e:
            self.logger.log_error("stream", f"스트림 생성 중 예외 발생: {str(e)}")
            print(f"\n[오류] 스트림 생성 중 예외 발생: {e}")
        finally:
            try:
                stream.stop_stream()
                stream.close()
                self.logger.log_info("녹음이 중지되고 스트림이 정리되었습니다")
            except Exception as e:
                self.logger.log_error("cleanup", f"스트림 정리 중 오류 발생: {str(e)}")

            print("\n녹음이 중지되었습니다.")

    def record_to_file(self, filename: str, duration: float) -> bool:
        """지정된 시간 동안 녹음하여 파일로 저장"""
        try:
            stream = self._create_stream()
            self.logger.log_info(f"{duration}초 동안 녹음을 시작합니다 - 파일: {filename}")
            print(f"\n{duration}초 동안 녹음합니다...")

            frames = []
            chunk_count = int(self.sample_rate * duration / self.chunk_size)

            for _ in range(chunk_count):
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                frames.append(data)

            stream.stop_stream()
            stream.close()

            # WAV 파일로 저장
            wf = wave.open(filename, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))  # WAV는 항상 Int16
            wf.setframerate(self.sample_rate)

            # Float32 -> Int16 변환 (필요한 경우)
            if self.format == pyaudio.paFloat32:
                audio_array = np.array([])
                for frame in frames:
                    chunk = np.frombuffer(frame, dtype=np.float32)
                    audio_array = np.append(audio_array, chunk)

                # 클리핑 방지 정규화
                max_val = np.max(np.abs(audio_array))
                if max_val > 0:  # 0으로 나누기 방지
                    audio_array = audio_array / max_val

                # Float32 -> Int16 변환
                audio_array = (audio_array * 32767).astype(np.int16)
                wf.writeframes(audio_array.tobytes())
            else:
                # 이미 Int16인 경우
                for frame in frames:
                    wf.writeframes(frame)

            wf.close()
            self.logger.log_info(f"녹음 완료: {filename}")
            print(f"\n녹음이 완료되었습니다: {filename}")
            return True

        except Exception as e:
            self.logger.log_error("file_recording", f"파일 녹음 중 오류 발생: {str(e)}")
            print(f"\n[오류] 파일 녹음 중 오류 발생: {e}")
            return False

    def get_status(self) -> Dict:
        """현재 녹음 상태 반환"""
        return self.stream_status

    def __del__(self):
        """소멸자: 리소스 정리"""
        try:
            if hasattr(self, 'audio'):
                self.audio.terminate()
                self.logger.log_info("오디오 리소스가 정리되었습니다")
        except Exception as e:
            self.logger.log_error("cleanup", f"리소스 정리 중 오류 발생: {str(e)}")
