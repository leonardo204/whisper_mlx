import os
import sys
import time
import threading
import queue
import argparse
import signal
from typing import Dict, Optional, List, Tuple
import json
import importlib.util
from datetime import datetime

# 자체 모듈 임포트
from logging_utils import LogManager
from audio_device import AudioDevice, AudioRecorder
from audio_processor import AudioProcessor
from transcription import TranscriptionManager

class RealTimeTranscriber:
    """
    실시간 음성 인식 메인 클래스
    - 전체 처리 흐름 조율
    - 사용자 인터페이스 관리
    - 모듈 간 연결 및 통합
    """
    def __init__(self, config: Dict = None):
        """실시간 음성 인식기 초기화"""
        # 로거 초기화
        self.logger = LogManager()
        self.logger.log_info("실시간 음성 인식기를 초기화합니다")

        # 기본 설정
        self.config = {
            'model_name': 'medium',            # Whisper 모델 이름
            'use_faster_whisper': True,          # Faster Whisper 사용 여부
            'translator_enabled': True,          # 번역 활성화 여부
            'translate_to': 'ko',                # 번역 대상 언어
            'save_transcript': True,             # 전사 결과 자동 저장 여부
            'output_dir': 'results',             # 결과 저장 디렉토리
            'log_level': 'info',                 # 로그 레벨 (debug/info)
            'calibration_duration': 3            # 초기 환경 캘리브레이션 시간 (초)
        }

        # 사용자 설정으로 업데이트
        if config:
            self.config.update(config)

        # 로그 레벨 설정
        if self.config['log_level'] == 'info':
            import logging
            self.logger.set_log_level(logging.INFO)

        # 결과 저장 디렉토리 생성
        if self.config['save_transcript']:
            os.makedirs(self.config['output_dir'], exist_ok=True)

        # 프로그램 제어용 이벤트
        self.stop_event = threading.Event()

        # 오디오 큐 및 세그먼트 큐
        self.audio_queue = queue.Queue()
        self.segment_queue = queue.Queue()

        # 초기화 완료 플래그
        self.initialized = False

        # 사용자 명령 히스토리
        self.command_history = []

        # 세션 정보
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.logger.log_info("초기화가 완료되었습니다")

    def initialize_components(self):
        """모든 구성 요소 초기화"""
        try:
            # 장치 관리자 초기화
            self.device_manager = AudioDevice()

            # 오디오 장치 선택
            device_index = self.device_manager.select_device()
            if device_index is None:
                self.logger.log_warning("오디오 장치가 선택되지 않았습니다")
                print("\n프로그램을 종료합니다.")
                sys.exit(0)

            # 오디오 설정 가져오기
            device_config = self.device_manager.get_config()

            # 레코더 초기화
            self.recorder = AudioRecorder(device_index, device_config)

            # 오디오 프로세서 초기화
            self.processor = AudioProcessor(sample_rate=device_config['sample_rate'])

            # 전사 관리자 초기화
            self.transcription_manager = TranscriptionManager(
                model_name=self.config['model_name'],
                use_faster_whisper=self.config['use_faster_whisper'],
                translator_enabled=self.config['translator_enabled'],
                translate_to=self.config['translate_to']
            )

            # 초기화 성공
            self.initialized = True
            self.logger.log_info("모든 구성 요소가 초기화되었습니다")

            # 시작 시간 표시
            print(f"\n시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"세션 ID: {self.session_id}")

            return True

        except Exception as e:
            self.logger.log_critical(f"구성 요소 초기화 중 오류 발생: {str(e)}")
            print(f"\n[오류] 초기화 중 문제가 발생했습니다: {e}")
            return False

    def start(self):
        """음성 인식 시작"""
        if not self.initialized and not self.initialize_components():
            return

        try:
            self.logger.log_info("음성 인식을 시작합니다")

            # 시그널 핸들러 등록
            signal.signal(signal.SIGINT, self._signal_handler)

            # 워크플로우 스레드 시작
            self._start_workflows()

            # 사용자 명령 처리
            self._process_user_commands()

        except Exception as e:
            self.logger.log_error("runtime", f"실행 중 예외 발생: {str(e)}")
            print(f"\n[오류] 실행 중 예외 발생: {e}")
        finally:
            self._cleanup()

    def _start_workflows(self):
        """워크플로우 스레드 시작"""
        # 1. 오디오 녹음 스레드
        self.record_thread = threading.Thread(
            target=self._record_audio_workflow,
            name="RecordThread"
        )
        self.record_thread.daemon = True

        # 2. 오디오 처리 스레드
        self.process_thread = threading.Thread(
            target=self._process_audio_workflow,
            name="ProcessThread"
        )
        self.process_thread.daemon = True

        # 3. 전사 스레드
        self.transcribe_thread = threading.Thread(
            target=self._transcribe_segments_workflow,
            name="TranscribeThread"
        )
        self.transcribe_thread.daemon = True

        # 4. 상태 모니터링 스레드
        self.monitor_thread = threading.Thread(
            target=self._monitor_status,
            name="MonitorThread"
        )
        self.monitor_thread.daemon = True

        # 모든 스레드 시작
        self.record_thread.start()
        self.process_thread.start()
        self.transcribe_thread.start()
        self.monitor_thread.start()

        self.logger.log_info("모든 워크플로우 스레드가 시작되었습니다")

    def _record_audio_workflow(self):
        """오디오 녹음 워크플로우"""
        try:
            self.logger.log_info("오디오 녹음 워크플로우를 시작합니다")
            self.recorder.record(self.audio_queue, self.stop_event)
        except Exception as e:
            self.logger.log_error("recording", f"녹음 중 예외 발생: {str(e)}")
            print(f"\n[오류] 녹음 중 예외 발생: {e}")
            self.stop_event.set()

    def _process_audio_workflow(self):
        """오디오 처리 워크플로우"""
        self.logger.log_info("오디오 처리 워크플로우를 시작합니다")

        try:
            # 환경 적응을 위한 초기 대기
            print(f"\n환경 소리 학습 중... ({self.config['calibration_duration']}초)")
            time.sleep(self.config['calibration_duration'])

            while not self.stop_event.is_set() or not self.audio_queue.empty():
                try:
                    # 오디오 데이터 가져오기
                    audio_data = self.audio_queue.get(timeout=0.1)

                    # 오디오 처리 및 세그먼트 생성
                    segment = self.processor.process_audio(audio_data)

                    # 세그먼트가 생성되면 큐에 추가
                    if segment:
                        self.segment_queue.put(segment)

                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.log_error("processing", f"처리 중 예외 발생: {str(e)}")
                    continue

        except Exception as e:
            self.logger.log_error("audio_processing", f"오디오 처리 중 예외 발생: {str(e)}")
            self.stop_event.set()

    def _transcribe_segments_workflow(self):
        """세그먼트 전사 워크플로우"""
        self.logger.log_info("전사 워크플로우를 시작합니다")

        try:
            while not self.stop_event.is_set() or not self.segment_queue.empty():
                try:
                    # 세그먼트 가져오기
                    segment = self.segment_queue.get(timeout=0.1)

                    # 세그먼트 전사
                    result = self.transcription_manager.process_segment(segment)

                    # 결과 출력
                    if result:
                        self._print_result(result)

                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.log_error("transcription", f"전사 중 예외 발생: {str(e)}")
                    continue

        except Exception as e:
            self.logger.log_error("transcription_workflow", f"전사 워크플로우 중 예외 발생: {str(e)}")
            self.stop_event.set()

    def _print_result(self, result: Dict):
        """전사 결과 출력"""
        duration = result['audio_duration']
        process_time = result['duration']

        if 'translation' in result:
            # 번역이 포함된 경우
            print(f"[전사완료][{duration:.2f}초][{result['language_name']}] {result['text']}")
            print(f"[번역완료][{result['translation']['duration']:.2f}초][한국어] {result['translation']['text']}\n")
        else:
            # 번역이 없는 경우
            print(f"[전사완료][{duration:.2f}초][{result['language_name']}] {result['text']}\n")

    def _monitor_status(self):
        """상태 모니터링 워크플로우"""
        try:
            while not self.stop_event.is_set():
                # 10초마다 간단한 상태 업데이트
                time.sleep(10)
    
                if self.stop_event.is_set():
                    break
    
                # 큐 상태 로깅
                audio_queue_size = self.audio_queue.qsize()
                segment_queue_size = self.segment_queue.qsize()
    
                if audio_queue_size > 20 or segment_queue_size > 5:
                    self.logger.log_warning(
                        f"큐 백로그 발생 - 오디오: {audio_queue_size}, 세그먼트: {segment_queue_size}"
                    )
    
                self.logger.log_debug(
                    f"상태 - 오디오 큐: {audio_queue_size}, 세그먼트 큐: {segment_queue_size}"
                )
                
                # 메모리 모니터링 추가
                self._monitor_memory_usage()
    
        except Exception as e:
            self.logger.log_error("monitoring", f"모니터링 중 예외 발생: {str(e)}")

    def _monitor_memory_usage(self):
        """메모리 사용량 모니터링"""
        try:
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            # MB 단위로 변환
            rss_mb = memory_info.rss / (1024 * 1024)
            vms_mb = memory_info.vms / (1024 * 1024)
            
            self.logger.log_debug(f"메모리 사용량 - RSS: {rss_mb:.2f}MB, VMS: {vms_mb:.2f}MB")
            
            if rss_mb > 500:  # 500MB 이상 사용 시 경고
                self.logger.log_warning(f"높은 메모리 사용량 감지: {rss_mb:.2f}MB")
                
                
            # 메모리 사용량이 매우 높으면(4GB 이상) 강제 정리
            if rss_mb > 4000:
                self.logger.log_warning(f"메모리 사용량이 매우 높습니다. 캐시를 강제로 정리합니다.")
                self.transcription_manager.transcriber.clear_cache()
                import gc
                gc.collect()
                
            return rss_mb, vms_mb
        
        except ImportError:
            self.logger.log_debug("psutil 모듈이 설치되지 않아 메모리 모니터링을 수행할 수 없습니다")
            return 0, 0
        except Exception as e:
            self.logger.log_error("memory_monitor", f"메모리 모니터링 중 오류: {str(e)}")
            return 0, 0

    def _process_user_commands(self):
        """사용자 명령 처리"""
        print("\n실시간 음성 인식이 시작되었습니다. 명령을 입력하려면 Enter를 누르세요.")
        print("사용 가능한 명령: stats, save, reset, config, help, exit")

        try:
            while not self.stop_event.is_set():
                # 사용자가 Enter를 누를 때까지 대기
                user_input = input("")

                if not user_input:
                    print("\n명령어를 입력하세요 (help로 도움말 확인):")
                    user_input = input("> ").strip().lower()

                if not user_input:
                    continue

                # 명령 이력에 추가
                self.command_history.append(user_input)

                # 명령 처리
                if user_input in ('q', 'quit', 'exit'):
                    print("프로그램을 종료합니다...")
                    self.stop_event.set()
                    break

                elif user_input in ('h', 'help'):
                    self._show_help()

                elif user_input in ('s', 'stats'):
                    self._show_stats()

                elif user_input in ('save', 'export'):
                    self._save_results()

                elif user_input in ('r', 'reset'):
                    self._reset_session()

                elif user_input in ('c', 'config'):
                    self._show_config()

                elif user_input.startswith('set '):
                    self._change_config(user_input[4:])

                else:
                    print(f"알 수 없는 명령: {user_input}")
                    print("'help'를 입력하면 사용 가능한 명령어를 확인할 수 있습니다.")

        except KeyboardInterrupt:
            print("\n프로그램을 종료합니다...")
            self.stop_event.set()

        except Exception as e:
            self.logger.log_error("command_processing", f"명령 처리 중 오류: {str(e)}")
            print(f"\n[오류] 명령 처리 중 오류 발생: {e}")
            self.stop_event.set()

    def _show_help(self):
        """도움말 표시"""
        print("\n=== 사용 가능한 명령어 ===")
        print("help, h      : 이 도움말 표시")
        print("stats, s     : 현재 전사 통계 표시")
        print("save, export : 현재까지의 전사 결과 저장")
        print("reset, r     : 세션 초기화 (기록 삭제)")
        print("config, c    : 현재 설정 확인")
        print("set [옵션]   : 설정 변경 (예: set translate_to=en)")
        print("  주요 설정 옵션:")
        print("  - log_level    : 로그 레벨 설정 (debug, info)")
        print("  - translate_to : 번역 대상 언어 설정 (ko, en, ja, zh 등)")
        print("  - model_name   : Whisper 모델 변경 (tiny, base, small, medium, large-v3)")
        print("  - translator_enabled : 번역 기능 활성화/비활성화 (true, false)")
        print("  - save_transcript    : 자동 저장 기능 활성화/비활성화 (true, false)")
        print("exit, quit, q: 프로그램 종료")
        
        print("\n=== 로그 레벨 설정 ===")
        print("set log_level=debug : 상세 로그 출력 (개발 및 디버깅용)")
        print("set log_level=info  : 기본 정보 로그만 출력 (일반 사용)")

    def _show_stats(self):
        """통계 정보 표시"""
        try:
            # 전사 통계
            transcription_stats = self.transcription_manager.get_statistics()
            
            # 오디오 처리 통계
            processor_stats = self.processor.get_stats()
            
            print("\n=== 전사 통계 ===")
            print(f"세션 ID: {self.session_id}")
            print(f"세션 시간: {transcription_stats['session_duration']:.1f}초")
            print(f"전사 항목 수: {transcription_stats['total_transcriptions']}")
            
            # Whisper 통계
            whisper_stats = transcription_stats['transcriber']
            if whisper_stats['total_processed'] > 0:
                print(f"\n=== Whisper 통계 ===")
                print(f"처리된 세그먼트: {whisper_stats['total_processed']}")
                print(f"평균 처리 시간: {whisper_stats['avg_processing_time']:.2f}초")
                print(f"성공률: {whisper_stats['success_rate']*100:.1f}%")
                
                # 언어별 통계
                if whisper_stats['language_counts']:
                    print("\n언어별 통계:")
                    # 자주 사용되는 언어 코드에 대한 간단한 매핑 직접 정의
                    lang_names = {
                        'ko': '한국어', 
                        'en': '영어',
                        'ja': '일본어',
                        'zh': '중국어',
                        'es': '스페인어',
                        'fr': '프랑스어',
                        'de': '독일어',
                        'it': '이탈리아어',
                        'ru': '러시아어',
                        'pt': '포르투갈어',
                        'nl': '네덜란드어',
                        'tr': '터키어',
                        'pl': '폴란드어',
                        'ar': '아랍어',
                        'hi': '힌디어',
                        'vi': '베트남어',
                        'th': '태국어',
                        'id': '인도네시아어',
                        'unknown': '알 수 없음'
                    }
                    
                    for lang, count in whisper_stats['language_counts'].items():
                        # 직접 정의한 매핑 사용
                        lang_name = lang_names.get(lang, lang)  # 매핑에 없으면 코드 그대로 사용
                        percentage = count / whisper_stats['total_processed'] * 100
                        print(f"  {lang_name}: {count}개 ({percentage:.1f}%)")
            
            # 오디오 처리 통계
            print(f"\n=== 오디오 처리 통계 ===")
            print(f"처리된 청크: {processor_stats['processed_chunks']}")
            print(f"생성된 세그먼트: {processor_stats['segments_created']}")
            avg_segment_duration = processor_stats['segmenter'].get('avg_segment_duration', 0)
            print(f"평균 세그먼트 길이: {avg_segment_duration:.2f}초")
            
            print("\n큐 상태:")
            print(f"오디오 큐 크기: {self.audio_queue.qsize()}")
            print(f"세그먼트 큐 크기: {self.segment_queue.qsize()}")
            
        except Exception as e:
            self.logger.log_error("stats_display", f"통계 표시 중 오류: {str(e)}")
            print(f"통계를 가져오는 중 오류가 발생했습니다: {e}")

    def _save_results(self):
        """현재 결과 저장"""
        try:
            # 타임스탬프로 파일명 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # JSON 및 텍스트 파일 경로
            json_path = os.path.join(self.config['output_dir'], f"transcript_{timestamp}.json")
            text_path = os.path.join(self.config['output_dir'], f"transcript_{timestamp}.txt")

            # JSON 형식으로 저장
            success_json = self.transcription_manager.save_transcript(json_path)

            # 텍스트 형식으로 저장
            success_text = self.transcription_manager.export_text(text_path)

            if success_json and success_text:
                print(f"\n전사 결과가 성공적으로 저장되었습니다:")
                print(f"JSON: {json_path}")
                print(f"텍스트: {text_path}")
            else:
                print("\n일부 결과 저장에 실패했습니다.")

        except Exception as e:
            self.logger.log_error("save_results", f"결과 저장 중 오류: {str(e)}")
            print(f"결과를 저장하는 중 오류가 발생했습니다: {e}")

    def _reset_session(self):
        """세션 초기화"""
        try:
            # 사용자 확인
            confirm = input("\n정말로 현재 세션을 초기화하시겠습니까? 모든 전사 기록이 삭제됩니다. (y/n): ")
            if confirm.lower() != 'y':
                print("세션 초기화가 취소되었습니다.")
                return

            # 현재 세션 저장 (선택적)
            save_current = input("현재 세션을 저장하시겠습니까? (y/n): ")
            if save_current.lower() == 'y':
                self._save_results()

            # 세션 초기화
            self.transcription_manager.reset_session()
            self.processor.reset()

            # 큐 비우기
            while not self.segment_queue.empty():
                self.segment_queue.get()

            # 세션 ID 업데이트
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

            print(f"\n세션이 초기화되었습니다. 새 세션 ID: {self.session_id}")
            self.logger.log_info(f"세션 초기화 완료. 새 세션 ID: {self.session_id}")

        except Exception as e:
            self.logger.log_error("reset_session", f"세션 초기화 중 오류: {str(e)}")
            print(f"세션 초기화 중 오류가 발생했습니다: {e}")

    def _show_config(self):
        """현재 설정 표시"""
        print("\n=== 현재 설정 ===")
        for key, value in self.config.items():
            print(f"{key}: {value}")

    def _change_config(self, config_str: str):
        """설정 변경"""
        try:
            # 입력 형식: key=value
            if '=' not in config_str:
                print("잘못된 형식입니다. 'set key=value' 형식으로 입력하세요.")
                return

            key, value = config_str.split('=', 1)
            key = key.strip()
            value = value.strip()

            # 설정 키 확인
            if key not in self.config:
                print(f"알 수 없는 설정 키: {key}")
                print(f"사용 가능한 키: {', '.join(self.config.keys())}")
                return

            # 타입에 맞게 변환
            old_value = self.config[key]
            if isinstance(old_value, bool):
                if value.lower() in ('true', 'yes', 'y', '1'):
                    value = True
                elif value.lower() in ('false', 'no', 'n', '0'):
                    value = False
                else:
                    print(f"잘못된 불리언 값: {value}")
                    return
            elif isinstance(old_value, int):
                value = int(value)
            elif isinstance(old_value, float):
                value = float(value)

            # 특별한 설정 처리
            if key == 'log_level':
                import logging
                log_levels = {
                    'debug': logging.DEBUG,
                    'info': logging.INFO,
                    'warning': logging.WARNING,
                    'error': logging.ERROR,
                    'critical': logging.CRITICAL
                }
                
                if value.lower() in log_levels:
                    self.logger.set_log_level(log_levels[value.lower()])
                    print(f"로그 레벨이 '{value}'로 변경되었습니다.")
                else:
                    print(f"지원되지 않는 로그 레벨: {value}")
                    print(f"지원되는 로그 레벨: {', '.join(log_levels.keys())}")
                    return
            elif key == 'translate_to':
                from transcription import SUPPORTED_LANGUAGES
                if value not in SUPPORTED_LANGUAGES:
                    print(f"지원되지 않는 언어 코드: {value}")
                    supported = ', '.join(SUPPORTED_LANGUAGES.keys())
                    print(f"지원되는 코드: {supported}")
                    return
                self.transcription_manager.transcriber.set_translate_language(value)

            # 설정 업데이트
            self.config[key] = value
            print(f"설정이 변경되었습니다: {key} = {value}")
            self.logger.log_info(f"설정 변경: {key} = {value}")

        except Exception as e:
            self.logger.log_error("config_change", f"설정 변경 중 오류: {str(e)}")
            print(f"설정 변경 중 오류가 발생했습니다: {e}")

    def _signal_handler(self, signum, frame):
        """시그널 처리"""
        self.logger.log_info("프로그램 종료 신호를 받았습니다")
        print("\n\n프로그램을 종료합니다...")
        self.stop_event.set()

    def _cleanup(self):
        """리소스 정리"""
        try:
            self.logger.log_info("리소스 정리 중...")

            # 자동 저장 (설정된 경우)
            if self.config['save_transcript']:
                try:
                    self._save_results()
                except Exception as e:
                    self.logger.log_error("auto_save", f"자동 저장 중 오류: {str(e)}")

            # 요약 통계 출력
            self._print_summary()

            self.logger.log_info("프로그램이 종료되었습니다")
            print("\n프로그램이 종료되었습니다.")

        except Exception as e:
            self.logger.log_error("cleanup", f"정리 중 오류 발생: {str(e)}")

    def _print_summary(self):
        """요약 통계 출력"""
        try:
            stats = self.transcription_manager.get_statistics()

            print("\n=== 세션 요약 ===")
            print(f"세션 시간: {stats['session_duration']:.1f}초")
            print(f"총 전사 항목: {stats['total_transcriptions']}개")

            transcriber_stats = stats['transcriber']
            if transcriber_stats['total_processed'] > 0:
                print(f"총 처리 세그먼트: {transcriber_stats['total_processed']}개")
                print(f"평균 처리 시간: {transcriber_stats['avg_processing_time']:.2f}초/세그먼트")

        except Exception as e:
            self.logger.log_error("summary", f"요약 출력 중 오류: {str(e)}")
            print("통계 요약을 생성할 수 없습니다.")


def check_dependencies():
    """필수 라이브러리 확인"""
    missing = []

    # 필수 라이브러리 목록
    required = {
        'numpy': 'numpy',
        'pyaudio': 'pyaudio',
        'webrtcvad': 'webrtcvad',
        'googletrans': 'googletrans==4.0.0-rc1'
    }

    # 선택적 라이브러리 (없어도 동작 가능하지만 권장)
    optional = {
        'faster_whisper': 'faster-whisper',
        'whisper': 'openai-whisper'
    }

    # 필수 라이브러리 확인
    for module, package in required.items():
        if importlib.util.find_spec(module) is None:
            missing.append(package)

    # 결과 처리
    if missing:
        print("다음 필수 라이브러리가 설치되지 않았습니다:")
        for package in missing:
            print(f"  - {package}")
        print("\n설치 명령어:")
        print(f"pip install {' '.join(missing)}")
        return False

    # 선택적 라이브러리 확인
    missing_optional = []
    for module, package in optional.items():
        if importlib.util.find_spec(module) is None:
            missing_optional.append(package)

    if missing_optional:
        print("다음 선택적 라이브러리가 설치되지 않았습니다:")
        for package in missing_optional:
            print(f"  - {package}")
        print("\n선택적 라이브러리 설치 명령어:")
        print(f"pip install {' '.join(missing_optional)}")
        print("\n선택적 라이브러리 없이도 기본 기능은 작동합니다.")

    return True

def parse_arguments():
    """명령줄 인수 파싱"""
    parser = argparse.ArgumentParser(description='실시간 음성 인식 및 전사 프로그램')

    parser.add_argument('--model', type=str, default='large-v3',
                        help='사용할 Whisper 모델 (tiny, base, small, medium, large-v3 등)')

    parser.add_argument('--no-faster-whisper', action='store_true',
                        help='Faster Whisper 사용하지 않음 (기본 Whisper 사용)')

    parser.add_argument('--no-translate', action='store_true',
                        help='자동 번역 비활성화')

    parser.add_argument('--translate-to', type=str, default='ko',
                        help='번역 대상 언어 코드 (기본값: ko)')

    parser.add_argument('--no-save', action='store_true',
                        help='자동 저장 비활성화')

    parser.add_argument('--output-dir', type=str, default='results',
                        help='출력 디렉토리 경로 (기본값: results)')

    parser.add_argument('--debug', action='store_true',
                        help='디버그 로그 활성화')

    parser.add_argument('--config', type=str,
                        help='설정 파일 경로 (JSON)')

    args = parser.parse_args()

    # 인수를 설정 딕셔너리로 변환
    config = {
        'model_name': args.model,
        'use_faster_whisper': not args.no_faster_whisper,
        'translator_enabled': not args.no_translate,
        'translate_to': args.translate_to,
        'save_transcript': not args.no_save,
        'output_dir': args.output_dir,
        'log_level': 'debug' if args.debug else 'info'
    }

    # 설정 파일이 제공된 경우 로드 및 병합
    if args.config:
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"설정 파일 로드 중 오류: {e}")

    return config


def main():
    """메인 함수"""
    print("실시간 음성 인식 프로그램을 초기화하는 중...")

    # 의존성 확인
    if not check_dependencies():
        sys.exit(1)

    # 인수 파싱
    config = parse_arguments()

    # 우선 사용자 정보 출력
    print("\n=== 실시간 음성 인식 및 전사 ===")
    print(f"모델: {config['model_name']}")
    print(f"Faster Whisper: {'사용' if config['use_faster_whisper'] else '사용 안 함'}")
    print(f"자동 번역: {'활성화' if config['translator_enabled'] else '비활성화'}")
    if config['translator_enabled']:
        from transcription import SUPPORTED_LANGUAGES
        lang_name = SUPPORTED_LANGUAGES.get(config['translate_to'], config['translate_to'])
        print(f"번역 대상 언어: {lang_name} ({config['translate_to']})")

    # 프로그램 시작
    transcriber = RealTimeTranscriber(config)
    transcriber.start()


if __name__ == "__main__":
    main()
