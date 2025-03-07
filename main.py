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
from settings import SettingsManager
from caption_client import CaptionClient

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

        # 설정 관리자 초기화
        self.settings_manager = SettingsManager()
        
        # 설정 로드
        self.config = self._load_config(config)

        # 로그 레벨 설정
        if self.config['system']['log_level'] == 'info':
            import logging
            self.logger.set_log_level(logging.INFO)

        # 결과 저장 디렉토리 생성
        if self.config['output']['save_transcript']:
            os.makedirs(self.config['output']['output_dir'], exist_ok=True)

        # 프로그램 제어용 이벤트
        self.stop_event = threading.Event()

        # 오디오 큐 및 세그먼트 큐
        self.audio_queue = queue.Queue()
        self.segment_queue = queue.Queue()

        # 초기화 완료 플래그
        self.initialized = False

        # 사용자 명령 히스토리
        self.command_history = []

        # 자막 클라이언트 초기화
        self.caption_client = None
        self.caption_enabled = self.config.get('caption', {}).get('enabled', False)
        
        # 자막 자동 시작 설정 확인
        if self.caption_enabled and self.config.get('caption', {}).get('auto_start', False):
            self.init_caption_client()

        # 세션 정보
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.logger.log_info("초기화가 완료되었습니다")

    def _load_config(self, config: Dict = None) -> Dict:
        """설정 로드 및 병합"""
        # 설정 관리자에서 설정 가져오기
        settings = self.settings_manager.get_all()
        
        # 명령줄/외부 설정이 있으면 업데이트
        if config:
            # 기존 코드 호환성을 위한 변환
            config_map = {
                'model_name': ('transcription', 'model_name'),
                'use_faster_whisper': ('transcription', 'use_faster_whisper'),
                'translator_enabled': ('translation', 'enabled'),
                'translate_to': ('translation', 'target_language'),
                'save_transcript': ('output', 'save_transcript'),
                'output_dir': ('output', 'output_dir'),
                'log_level': ('system', 'log_level'),
                'calibration_duration': ('audio', 'calibration_duration'),
                'max_history': ('transcription', 'max_history')  # 매핑 추가
            }
            
            # 설정 업데이트
            for old_key, (section, new_key) in config_map.items():
                if old_key in config:
                    self.settings_manager.set(f"{section}.{new_key}", config[old_key], save=False)
            
            # 설정 저장
            self.settings_manager.save_settings()
        

        # 최종 설정 반환 - 호환성 레이어 추가
        final_config = self.settings_manager.get_all()
        
        # 기존 코드와의 호환성을 위해 평면화된 설정 키도 추가
        flattened_config = {}
        for section, section_config in final_config.items():
            for key, value in section_config.items():
                flattened_config[key] = value
        
        # 기존 키 이름 매핑에 따라 추가
        for old_key, (section, new_key) in config_map.items():
            flattened_config[old_key] = final_config[section][new_key]
        
        # 새 구조와 평면화된 구조를 모두 포함
        combined_config = final_config.copy()
        combined_config.update(flattened_config)
        
        return combined_config

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

            # max_history 설정 가져오기 (호환성 레이어 활용)
            max_history = self.config.get('max_history', 
                                        self.config.get('transcription', {}).get('max_history', 1000))

            # 전사 관리자 초기화
            self.transcription_manager = TranscriptionManager(
                model_name=self.config['transcription']['model_name'],
                use_faster_whisper=self.config['transcription']['use_faster_whisper'],
                translator_enabled=self.config['translation']['enabled'],
                translate_to=self.config['translation']['target_language'],
                max_history=max_history  # max_history 설정 전달
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


    def init_caption_client(self):
        """자막 클라이언트 초기화 (개선됨)"""
        if self.caption_client is None:
            self.logger.log_info("자막 클라이언트를 초기화합니다.")
            try:
                self.caption_client = CaptionClient()
                
                # 자막 오버레이 시작
                if self.caption_client.start_overlay(wait_for_server=1.0):  # 대기 시간 증가
                    self.caption_enabled = True
                    self.logger.log_info("자막 오버레이가 시작되었습니다.")

                    # 초기 설정 적용
                    caption_settings = self.config.get('caption', {})
                    self.update_caption_settings(caption_settings)
                    
                    # 시작 메시지 표시
                    self.caption_client.set_caption("실시간 음성 인식 자막이 활성화되었습니다.", 3000)
                    return True
                else:
                    self.logger.log_error("caption_init", "자막 오버레이 시작에 실패했습니다.")
                    self.caption_client = None
                    self.caption_enabled = False
                    return False
            except Exception as e:
                self.logger.log_error("caption_init", f"자막 초기화 중 오류: {str(e)}")
                self.caption_client = None
                self.caption_enabled = False
                return False
        else:
            self.logger.log_info("자막 클라이언트가 이미 초기화되어 있습니다.")
            return True
    
    def update_caption_settings(self, settings):
        """자막 설정 업데이트 (개선된 버전)"""
        if not self.caption_client or not self.caption_enabled:
            return False
            
        # 설정 변환 (RealTimeTranscriber 설정 -> 자막 오버레이 설정)
        overlay_settings = {}
        
        # 폰트 크기
        if 'font_size' in settings:
            if 'font' not in overlay_settings:
                overlay_settings['font'] = {}
            overlay_settings['font']['size'] = settings['font_size']
        
        # 위치
        if 'position' in settings:
            if 'position' not in overlay_settings:
                overlay_settings['position'] = {}
            overlay_settings['position']['location'] = settings['position']
        
        # 표시 시간
        if 'display_duration' in settings:
            if 'display' not in overlay_settings:
                overlay_settings['display'] = {}
            overlay_settings['display']['duration'] = settings['display_duration']
        
        # 번역 설정
        if 'show_translation' in settings:
            if 'translation' not in overlay_settings:
                overlay_settings['translation'] = {}
            overlay_settings['translation']['enabled'] = settings['show_translation']
        
        # 수정된 설정을 메인 설정에 반영 (설정 동기화)
        caption_config = self.config.get('caption', {})
        for key, value in settings.items():
            caption_config[key] = value
        
        # 다음 번 실행을 위해 설정 매니저 업데이트
        if hasattr(self, 'settings_manager'):
            for key, value in settings.items():
                self.settings_manager.set(f"caption.{key}", value, save=False)
            # 설정 저장
            self.settings_manager.save_settings()
        
        # 설정 적용
        if overlay_settings:
            return self.caption_client.update_settings(overlay_settings)
        
        return True
    
    def send_caption(self, text, duration=None):
        """자막 텍스트 전송"""
        if not self.caption_client or not self.caption_enabled:
            return False
            
        try:
            return self.caption_client.set_caption(text, duration)
        except Exception as e:
            self.logger.log_error("caption_send", f"자막 전송 중 오류: {str(e)}")
            return False
    
    def toggle_caption_display(self):
        """자막 표시/숨김 토글"""
        if not self.caption_client:
            if not self.init_caption_client():
                return False
        
        try:
            return self.caption_client.toggle_caption()
        except Exception as e:
            self.logger.log_error("caption_toggle", f"자막 토글 중 오류: {str(e)}")
            return False
    
    def toggle_caption_enabled(self):
        """자막 기능 활성화/비활성화 토글"""
        if self.caption_enabled:
            # 비활성화
            if self.caption_client:
                try:
                    self.caption_client.hide_caption()
                    self.caption_enabled = False
                    self.logger.log_info("자막 기능이 비활성화되었습니다.")
                    print("자막 기능이 비활성화되었습니다.")
                    return True
                except Exception as e:
                    self.logger.log_error("caption_disable", f"자막 비활성화 중 오류: {str(e)}")
                    return False
        else:
            # 활성화
            if not self.caption_client:
                if not self.init_caption_client():
                    return False
            
            try:
                self.caption_client.show_caption()
                self.caption_enabled = True
                self.logger.log_info("자막 기능이 활성화되었습니다.")
                print("자막 기능이 활성화되었습니다.")
                return True
            except Exception as e:
                self.logger.log_error("caption_enable", f"자막 활성화 중 오류: {str(e)}")
                return False
        
        return True

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
        """전사 결과 출력 (개선된 버전)"""
        duration = result['audio_duration']
        process_time = result['duration']

        if 'translation' in result:
            # 번역이 포함된 경우
            print(f"[전사완료][{duration:.2f}초][{result['language_name']}] {result['text']}")
            print(f"[번역완료][{result['translation']['duration']:.2f}초][한국어] {result['translation']['text']}\n")
            
            # 자막 전송 (번역 포함)
            if self.caption_enabled and self.caption_client:
                caption_settings = self.config.get('caption', {})
                show_translation = caption_settings.get('show_translation', True)
                display_duration = caption_settings.get('display_duration', 5000)
                
                # 변경된 부분: 원본과 번역을 구분하여 전송
                if show_translation:
                    # 원본과 번역 모두 전송 (빈 줄로 구분)
                    # 2줄 줄바꿈으로 구분되면 set_caption 메서드에서 색상을 다르게 처리함
                    caption_text = f"{result['text']}\n\n{result['translation']['text']}"
                else:
                    # 원문만 표시
                    caption_text = result['text']
                
                self.send_caption(caption_text, display_duration)
        else:
            # 번역이 없는 경우
            print(f"[전사완료][{duration:.2f}초][{result['language_name']}] {result['text']}\n")
            
            # 자막 전송 (원문만)
            if self.caption_enabled and self.caption_client:
                display_duration = self.config.get('caption', {}).get('display_duration', 5000)
                self.send_caption(result['text'], display_duration)

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

                elif user_input in ('cc on', 'caption on'):
                    self.toggle_caption_enabled()

                elif user_input in ('cc off', 'caption off'):
                    if self.caption_enabled:
                        self.toggle_caption_enabled()
                    else:
                        print("자막 기능이 이미 비활성화되어 있습니다.")

                elif user_input in ('cc toggle', 'caption toggle'):
                    self.toggle_caption_display()
                    
                elif user_input.startswith('cc '):
                    # cc 명령으로 직접 자막 전송
                    caption_text = user_input[3:].strip()
                    if caption_text:
                        if self.caption_client and self.caption_enabled:
                            self.send_caption(caption_text)
                            print(f"자막 메시지를 전송했습니다: {caption_text}")
                        else:
                            print("자막 기능이 활성화되어 있지 않습니다. 'cc on'으로 활성화하세요.")
                    else:
                        print("전송할 자막 텍스트를 입력하세요. 예: cc 안녕하세요")

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
        print("\n=== 자막 관련 명령어 ===")
        print("cc on         : 자막 기능 활성화")
        print("cc off        : 자막 기능 비활성화")
        print("cc toggle     : 자막 표시/숨김 토글")
        print("cc [텍스트]   : 특정 텍스트를 자막으로 표시")
        print("\n=== 설정 관련 명령어 ===")
        print("set [옵션]   : 설정 변경 (예: set translate_to=en)")
        print("  주요 설정 옵션:")
        print("  - log_level    : 로그 레벨 설정 (debug, info)")
        print("  - translate_to : 번역 대상 언어 설정 (ko, en, ja, zh 등)")
        print("  - model_name   : Whisper 모델 변경 (tiny, base, small, medium, large-v3)")
        print("  - translator_enabled : 번역 기능 활성화/비활성화 (true, false)")
        print("  - save_transcript    : 자동 저장 기능 활성화/비활성화 (true, false)")
        print("\n=== 로그 레벨 설정 ===")
        print("set log_level=debug : 상세 로그 출력 (개발 및 디버깅용)")
        print("set log_level=info  : 기본 정보 로그만 출력 (일반 사용)")
        print("\n=== 프로그램 종료 ===")
        print("exit, quit, q: 프로그램 종료")


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
        
        # 설정 구조화하여 표시
        config = self.settings_manager.get_all()
        for section, settings in config.items():
            print(f"\n[{section}]")
            for key, value in settings.items():
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
            
            # 점 표기법을 사용하여 설정 경로 매핑
            key_mapping = {
                'model_name': 'transcription.model_name',
                'use_faster_whisper': 'transcription.use_faster_whisper',
                'translator_enabled': 'translation.enabled',
                'translate_to': 'translation.target_language',
                'save_transcript': 'output.save_transcript',
                'output_dir': 'output.output_dir',
                'log_level': 'system.log_level',
                'calibration_duration': 'audio.calibration_duration'
            }
            
            # 매핑된 설정 키 찾기
            setting_key = key_mapping.get(key, key)  # 매핑 없으면 원래 키 사용
            
            # 현재 값 가져오기
            current_value = self.settings_manager.get(setting_key)
            if current_value is None and '.' not in setting_key:
                print(f"알 수 없는 설정 키: {key}")
                print(f"사용 가능한 키: {', '.join(key_mapping.keys())}")
                return
            
            # 타입에 맞게 변환
            if isinstance(current_value, bool):
                if value.lower() in ('true', 'yes', 'y', '1'):
                    value = True
                elif value.lower() in ('false', 'no', 'n', '0'):
                    value = False
                else:
                    print(f"잘못된 불리언 값: {value}")
                    return
            elif isinstance(current_value, int):
                value = int(value)
            elif isinstance(current_value, float):
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
            self.settings_manager.set(setting_key, value)
            
            # 내부 config 업데이트
            self.config = self.settings_manager.get_all()
            
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
            
            # 자막 클라이언트 종료
            if self.caption_client:
                try:
                    self.logger.log_info("자막 클라이언트 종료 중...")
                    self.caption_client.shutdown()
                    self.caption_client = None
                except Exception as e:
                    self.logger.log_error("caption_cleanup", f"자막 클라이언트 종료 중 오류: {str(e)}")

            # 기존 코드...
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
        'webrtcvad': 'webrtcvad'
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
    # missing_optional = []
    # for module, package in optional.items():
    #     if importlib.util.find_spec(module) is None:
    #         missing_optional.append(package)

    # if missing_optional:
    #     print("다음 선택적 라이브러리가 설치되지 않았습니다:")
    #     for package in missing_optional:
    #         print(f"  - {package}")
    #     print("\n선택적 라이브러리 설치 명령어:")
    #     print(f"pip install {' '.join(missing_optional)}")
    #     print("\n선택적 라이브러리 없이도 기본 기능은 작동합니다.")

    return True

def parse_arguments():
    """명령줄 인수 파싱"""
    parser = argparse.ArgumentParser(description='실시간 음성 인식 및 전사 프로그램')

    parser.add_argument('--model', type=str, default=None,
                        help='사용할 Whisper 모델 (tiny, base, small, medium, large-v3 등)')

    parser.add_argument('--faster-whisper', action='store_true',
                        help='Faster Whisper 사용 (기본값: 사용 안함)')

    parser.add_argument('--no-translate', action='store_true',
                        help='자동 번역 비활성화')

    parser.add_argument('--translate-to', type=str, default=None,
                        help='번역 대상 언어 코드 (기본값: ko)')

    parser.add_argument('--no-save', action='store_true',
                        help='자동 저장 비활성화')

    parser.add_argument('--output-dir', type=str, default=None,
                        help='출력 디렉토리 경로 (기본값: results)')

    parser.add_argument('--debug', action='store_true',
                        help='디버그 로그 활성화')

    parser.add_argument('--config', type=str, default='settings.json',
                        help='설정 파일 경로 (기본값: settings.json)')
    
    parser.add_argument('--calibration-duration', type=int, default=None,
                        help='초기 환경 캘리브레이션 시간 (초)')

    parser.add_argument('--max-history', type=int, default=None,
                        help='최대 전사 기록 수 (기본값: 1000)')

    # 자막 관련 인수
    parser.add_argument('--caption', action='store_true',
                        help='자막 기능 활성화')
    parser.add_argument('--no-caption', action='store_true',
                        help='자막 기능 비활성화')
    parser.add_argument('--caption-position', type=str, choices=['top', 'middle', 'bottom'], default=None,
                        help='자막 위치 설정 (top, middle, bottom)')
    parser.add_argument('--caption-duration', type=int, default=None,
                        help='자막 표시 시간 (ms) - 0은 계속 표시')
    parser.add_argument('--caption-font-size', type=int, default=None,
                        help='자막 폰트 크기')

    args = parser.parse_args()

    # 설정 관리자 초기화 (지정된 설정 파일 사용)
    settings_manager = SettingsManager(args.config)
    
    # 명령줄 인수로 설정 업데이트
    settings_manager.update_from_args(vars(args))
    
    # 설정 반환
    return settings_manager.get_all()


def main():
    """메인 함수"""
    print("실시간 음성 인식 프로그램을 초기화하는 중...")

    # 의존성 확인
    if not check_dependencies():
        sys.exit(1)

    # 인수 파싱 및 설정 로드
    config = parse_arguments()

    # 우선 사용자 정보 출력
    print("\n=== 실시간 음성 인식 및 전사 ===")
    print(f"모델: {config['transcription']['model_name']}")
    print(f"Faster Whisper: {'사용' if config['transcription']['use_faster_whisper'] else '사용 안 함'}")
    print(f"자동 번역: {'활성화' if config['translation']['enabled'] else '비활성화'}")
    if config['translation']['enabled']:
        from transcription import SUPPORTED_LANGUAGES
        lang_name = SUPPORTED_LANGUAGES.get(config['translation']['target_language'], 
                                           config['translation']['target_language'])
        print(f"번역 대상 언어: {lang_name} ({config['translation']['target_language']})")

    # 프로그램 시작
    transcriber = RealTimeTranscriber(config)
    transcriber.start()


if __name__ == "__main__":
    main()
