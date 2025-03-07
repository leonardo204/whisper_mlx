import socket
import json
import time
import threading
import os
import signal
import subprocess
import sys
import atexit
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("CaptionClient")

class CaptionClient:
    """
    자막 오버레이와 통신하는 클라이언트 클래스
    - 소켓 통신을 통해 자막 오버레이 제어
    - 기본 포트: 10987
    """
    def __init__(self, host='127.0.0.1', port=10987):
        self.host = host
        self.port = port
        self.socket = None
        self.connected = False
        self.overlay_process = None
        self.lock = threading.Lock()
        self.response_buffer = ""
        self.response_event = threading.Event()
        self.last_response = None
        self.reader_thread = None
        self._shutdown_called = False
        
        # 클라이언트 종료 시 자막 프로세스도 종료하도록 등록
        atexit.register(self.shutdown)
    
    def start_overlay(self, settings=None, wait_for_server=1.0):
        """자막 오버레이 프로세스 시작"""
        if self.is_overlay_running():
            logger.info("자막 오버레이가 이미 실행 중입니다.")
            return True
            
        try:
            # 자막 오버레이 파일 경로 확인
            script_dir = os.path.dirname(os.path.abspath(__file__))
            overlay_script = os.path.join(script_dir, "caption_overlay.py")
            
            if not os.path.exists(overlay_script):
                logger.error(f"자막 오버레이 스크립트를 찾을 수 없습니다: {overlay_script}")
                return False
                
            # 자막 오버레이 프로세스 시작
            command = [sys.executable, overlay_script]
            
            # 설정이 있으면 Command-line 인수로 추가 (향후 구현)
            
            if os.name == 'nt':  # Windows
                self.overlay_process = subprocess.Popen(
                    command,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:  # Linux/Mac
                self.overlay_process = subprocess.Popen(
                    command,
                    preexec_fn=os.setpgrp
                )
                
            # 프로세스가 시작될 때까지 잠시 대기
            logger.info(f"자막 오버레이 프로세스 시작됨 (PID: {self.overlay_process.pid})")
            logger.info(f"서버 초기화를 위해 {wait_for_server}초 대기 중...")
            time.sleep(wait_for_server)
            
            # 연결 시도
            return self.connect()
            
        except Exception as e:
            logger.exception(f"자막 오버레이 시작 중 오류 발생: {str(e)}")
            return False
    
    def connect(self, max_attempts=1, retry_delay=1.0):
        """자막 오버레이에 연결 (개선된 버전)"""
        if self.connected and self.socket:
            logger.info("이미 자막 오버레이에 연결되어 있습니다.")
            return True
            
        # 이전 소켓 종료
        self.disconnect()
            
        for attempt in range(max_attempts):
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(5.0)  # 연결 타임아웃 증가
                self.socket.connect((self.host, self.port))
                self.connected = True
                
                # 응답 읽기 스레드 시작
                if self.reader_thread is None or not self.reader_thread.is_alive():
                    self.reader_thread = threading.Thread(target=self._read_responses)
                    self.reader_thread.daemon = True
                    self.reader_thread.start()
                
                logger.info(f"자막 오버레이에 연결되었습니다.")
                return True
                
            except socket.error as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"연결 시도 {attempt+1}/{max_attempts} 실패: {str(e)}. {retry_delay}초 후 재시도...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"자막 오버레이 연결 실패: {str(e)}")
                    
        self.connected = False
        self.socket = None
        return False
    
    def disconnect(self):
        """자막 오버레이 연결 종료"""
        with self.lock:
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except Exception as e:
                    logger.debug(f"소켓 종료 중 오류 (무시됨): {str(e)}")
                finally:
                    self.socket = None
                    logger.debug("소켓 연결이 종료되었습니다.")
    
    def is_overlay_running(self):
        """자막 오버레이 프로세스가 실행 중인지 확인"""
        if self.overlay_process:
            return self.overlay_process.poll() is None
        return False
    
    def terminate_overlay(self):
        """자막 오버레이 프로세스 종료"""
        if not self.is_overlay_running():
            logger.debug("자막 오버레이 프로세스가 이미 종료되었습니다.")
            return True
            
        # 먼저 소켓을 통해 정상 종료 메시지 전송
        if self.connected:
            try:
                logger.info("자막 오버레이에 종료 명령을 전송합니다.")
                self.send_command("exit")
                # 프로세스가 종료될 때까지 잠시 대기
                wait_time = 0
                while self.is_overlay_running() and wait_time < 3.0:
                    time.sleep(0.3)
                    wait_time += 0.3
            except Exception as e:
                logger.warning(f"종료 명령 전송 중 오류: {str(e)}")
            finally:
                self.disconnect()
        
        # 프로세스가 여전히 실행 중이면 강제 종료 시도
        if self.is_overlay_running():
            logger.warning("자막 오버레이가 정상 종료되지 않았습니다. 강제 종료를 시도합니다.")
            try:
                if os.name == 'nt':  # Windows
                    os.kill(self.overlay_process.pid, signal.CTRL_BREAK_EVENT)
                else:  # Linux/Mac
                    try:
                        os.killpg(os.getpgid(self.overlay_process.pid), signal.SIGTERM)
                    except:
                        # 그룹 킬이 실패하면 직접 종료
                        self.overlay_process.terminate()
                
                # 종료될 때까지 잠시 대기
                wait_time = 0
                while self.is_overlay_running() and wait_time < 3.0:
                    time.sleep(0.3)
                    wait_time += 0.3
                
                # 여전히 종료되지 않으면 SIGKILL
                if self.is_overlay_running():
                    logger.warning("SIGTERM으로 종료되지 않았습니다. SIGKILL을 시도합니다.")
                    if os.name == 'nt':  # Windows
                        self.overlay_process.kill()
                    else:  # Linux/Mac
                        try:
                            os.killpg(os.getpgid(self.overlay_process.pid), signal.SIGKILL)
                        except:
                            self.overlay_process.kill()
                    
                    # 마지막 확인
                    time.sleep(0.5)
                    if self.is_overlay_running():
                        logger.error("프로세스를 강제 종료할 수 없습니다.")
                        return False
            except Exception as e:
                logger.exception(f"프로세스 종료 중 오류 발생: {str(e)}")
                return False
        
        logger.info("자막 오버레이 프로세스가 종료되었습니다.")
        self.overlay_process = None
        return True
    
    def shutdown(self):
        """클라이언트 종료 - 중복 호출 방지"""
        if self._shutdown_called:
            return
            
        self._shutdown_called = True
        logger.info("클라이언트를 종료합니다...")
        
        # 자막 오버레이 종료
        self.terminate_overlay()
        
        # 소켓 연결 종료
        self.disconnect()
        
        logger.info("클라이언트가 종료되었습니다.")
    
    def _read_responses(self):
        """소켓으로부터 응답 읽기"""
        buffer = ""
        
        while self.connected and self.socket:
            try:
                # 데이터 수신
                try:
                    data = self.socket.recv(4096)
                    
                    if not data:
                        # 연결 종료
                        logger.info("서버와의 연결이 종료되었습니다.")
                        self.connected = False
                        break
                        
                    # 데이터 디코딩
                    text = data.decode('utf-8')
                    buffer += text
                except socket.timeout:
                    # 타임아웃은 무시하고 계속 진행
                    continue
                except Exception as e:
                    if self.connected:  # 의도적 종료가 아닌 경우만 로그
                        logger.error(f"응답 읽기 중 오류: {str(e)}")
                    self.connected = False
                    break
                
                # 완전한 메시지 추출
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            response = json.loads(line)
                            with self.lock:
                                self.last_response = response
                                self.response_event.set()
                        except json.JSONDecodeError as e:
                            logger.warning(f"잘못된 JSON 응답: {line}, 오류: {str(e)}")
                
            except Exception as e:
                if self.connected:  # 의도적 종료가 아닌 경우만 로그
                    logger.exception(f"응답 처리 중 예외 발생: {str(e)}")
                self.connected = False
                break
        
        logger.debug("응답 읽기 스레드가 종료되었습니다.")
    
    def _send_message(self, message):
        """소켓을 통해 메시지 전송"""
        if not self.connected or not self.socket:
            if not self.connect():
                return False
        
        try:
            with self.lock:
                # 메시지에 개행 추가
                message_str = json.dumps(message) + '\n'
                self.socket.sendall(message_str.encode('utf-8'))
                return True
        except Exception as e:
            logger.error(f"메시지 전송 중 오류: {str(e)}")
            self.connected = False
            return False
    
    def send_command(self, command, timeout=2.0):
        """명령 전송 및 응답 대기"""
        message = {"command": command}
        
        # 이전 응답 초기화
        self.response_event.clear()
        
        # 메시지 전송
        if not self._send_message(message):
            return {"status": "error", "message": "Failed to send command"}
        
        # 응답 대기
        if self.response_event.wait(timeout):
            with self.lock:
                response = self.last_response
                self.last_response = None
                return response
        
        return {"status": "error", "message": "Timeout waiting for response"}
    
    def set_caption(self, text, duration=None):
        """자막 텍스트 설정 (강화된 버전)"""
        # 텍스트 형식 확인 및 처리
        if not text:
            logger.warning("자막 텍스트가 비어 있습니다.")
            return False
            
        # 연결 상태 확인 및 재연결 시도
        if not self.connected:
            if not self.connect():
                # 연결 실패 시 자막 서버 재시작 시도
                logger.warning("자막 서버 연결 실패, 서버 재시작 시도...")
                if self.start_overlay(wait_for_server=1.0):
                    logger.info("자막 서버 재시작 성공")
                else:
                    logger.error("자막 서버 재시작 실패")
                    return False
        
        # 메시지 전송
        message = {"text": text}
        if duration is not None:
            message["duration"] = duration
        
        try:
            # 먼저 화면 지우기 명령 전송
            clear_message = {"clear": True}
            self._send_message(clear_message)
            
            # 잠시 대기 (화면 지우기 처리 시간)
            time.sleep(0.05)
            
            # 자막 메시지 전송
            if not self._send_message(message):
                logger.warning("자막 텍스트 설정에 실패했습니다.")
                return False
                
            return True
        except Exception as e:
            logger.error(f"자막 설정 중 오류: {str(e)}")
            self.connected = False  # 연결 상태 갱신
            return False
    
    def update_settings(self, settings):
        """자막 설정 업데이트 (수정된 버전)"""
        # 설정이 딕셔너리인지 확인
        if not isinstance(settings, dict):
            logger.warning("유효하지 않은 설정 형식입니다.")
            return False
        
        # 설정 변환 (확장된 매핑)
        expanded_settings = {}
        
        # 폰트 설정
        if 'font_size' in settings:
            if 'font' not in expanded_settings:
                expanded_settings['font'] = {}
            expanded_settings['font']['size'] = settings['font_size']
        
        if 'font_family' in settings:
            if 'font' not in expanded_settings:
                expanded_settings['font'] = {}
            expanded_settings['font']['family'] = settings['font_family']
        
        if 'font_bold' in settings:
            if 'font' not in expanded_settings:
                expanded_settings['font'] = {}
            expanded_settings['font']['bold'] = settings['font_bold']
        
        # 위치 설정
        if 'position' in settings:
            if 'position' not in expanded_settings:
                expanded_settings['position'] = {}
            expanded_settings['position']['location'] = settings['position']
        
        # 오프셋 설정
        if 'offset_x' in settings:
            if 'position' not in expanded_settings:
                expanded_settings['position'] = {}
            expanded_settings['position']['offset_x'] = settings['offset_x']
        
        if 'offset_y' in settings:
            if 'position' not in expanded_settings:
                expanded_settings['position'] = {}
            expanded_settings['position']['offset_y'] = settings['offset_y']
        
        # 표시 시간
        if 'display_duration' in settings:
            if 'display' not in expanded_settings:
                expanded_settings['display'] = {}
            expanded_settings['display']['duration'] = settings['display_duration']
        
        # 색상 설정
        if 'text_color' in settings:
            if 'color' not in expanded_settings:
                expanded_settings['color'] = {}
            expanded_settings['color']['text'] = settings['text_color']
        
        if 'background_color' in settings:
            if 'color' not in expanded_settings:
                expanded_settings['color'] = {}
            expanded_settings['color']['background'] = settings['background_color']
        
        # 번역 설정
        if 'show_translation' in settings:
            if 'translation' not in expanded_settings:
                expanded_settings['translation'] = {}
            expanded_settings['translation']['enabled'] = settings['show_translation']
        
        # 원본 설정도 병합
        for key, value in settings.items():
            if isinstance(value, dict):
                if key not in expanded_settings:
                    expanded_settings[key] = {}
                expanded_settings[key].update(value)
        
        # 자막 오버레이에 설정 전송
        message = {"settings": expanded_settings}
        if not self._send_message(message):
            logger.warning("자막 설정 업데이트에 실패했습니다.")
            return False
        
        logger.info(f"자막 설정이 업데이트되었습니다: {expanded_settings}")
        return True
    
    def show_caption(self):
        """자막 표시"""
        response = self.send_command("show")
        return response.get("status") == "ok"
    
    def hide_caption(self):
        """자막 숨기기"""
        response = self.send_command("hide")
        return response.get("status") == "ok"
    
    def get_status(self):
        """자막 상태 확인"""
        return self.send_command("status")
    
    def toggle_caption(self):
        """자막 표시/숨김 토글"""
        status = self.get_status()
        if status.get("status") == "ok":
            if status.get("caption_visible", False):
                return self.hide_caption()
            else:
                return self.show_caption()
        return False


# 테스트 코드
if __name__ == "__main__":
    # 로그 레벨 설정
    logger.setLevel(logging.DEBUG)
    
    client = CaptionClient()
    
    print("자막 클라이언트 테스트를 시작합니다...")
    
    # 자막 오버레이 시작
    if client.start_overlay(wait_for_server=3.0):  # 서버 초기화를 위해 여유 있게 대기
        try:
            # 간단한 테스트
            print("\n1. 자막 표시 테스트")
            client.set_caption("자막 클라이언트 테스트", 3000)
            time.sleep(4)
            
            print("\n2. 계속 표시 자막 테스트")
            client.set_caption("이 자막은 계속 표시됩니다.")
            time.sleep(3)
            
            print("\n3. 숨기기/표시 테스트")
            client.hide_caption()
            time.sleep(1)
            client.show_caption()
            time.sleep(1)
            
            print("\n4. 설정 변경 테스트")
            client.update_settings({
                "font": {"size": 32},
                "color": {"background": "#88FF0000"},  # 반투명 빨간색
                "position": {"location": "top"}
            })
            
            client.set_caption("설정이 변경되었습니다!\n폰트 크기: 32pt\n배경색: 빨간색\n위치: 상단")
            time.sleep(5)
            
            print("\n테스트 완료. 종료를 시작합니다...")
            
        except KeyboardInterrupt:
            print("\n테스트가 사용자에 의해 중단되었습니다.")
        finally:
            # 종료
            client.shutdown()
    else:
        print("자막 오버레이를 시작할 수 없습니다.")
    
    print("테스트 완료")