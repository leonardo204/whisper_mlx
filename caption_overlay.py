import os
import json
import time
import platform
import threading
import queue
import socket
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                             QWidget, QDesktopWidget, QMenu, QAction, 
                             QSystemTrayIcon, QDialog, QComboBox, QPushButton,
                             QMenuBar, QActionGroup)  # QActionGroup 추가
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QPoint, QSize, QRectF, PYQT_VERSION_STR
from PyQt5.QtGui import QPainter, QColor, QFont, QPainterPath, QPen, QIcon, QKeySequence, QPixmap, QFontMetrics


# 상수 정의 (PyQt5 버전 호환성)
try:
    from PyQt5.QtWidgets import QWIDGETSIZE_MAX
except ImportError:
    QWIDGETSIZE_MAX = 16777215  # Qt 기본값

# 소켓 서버 클래스 추가
class CaptionServer:
    """
    자막 오버레이를 위한 소켓 서버
    - 메인 프로그램으로부터 명령과 자막 텍스트를 수신
    """
    def __init__(self, caption_overlay, host='127.0.0.1', port=10987):
        self.caption_overlay = caption_overlay
        self.host = host
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.running = False
        self.server_thread = None
        self.print_lock = threading.Lock()
        self.message_queue = queue.Queue()
        
        # 메인 스레드에서 메시지를 처리하기 위한 타이머
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self._process_message_queue)
        self.process_timer.start(100)  # 100ms마다 메시지 큐 확인
        
    def start(self):
        """서버 시작"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            self.running = True
            
            # 로그 출력
            self._print_msg(f"자막 서버가 시작되었습니다. {self.host}:{self.port}")
            
            # 서버 스레드 시작
            self.server_thread = threading.Thread(target=self._accept_connections)
            self.server_thread.daemon = True
            self.server_thread.start()
            return True
        except Exception as e:
            self._print_msg(f"서버 시작 중 오류 발생: {str(e)}")
            return False
            
    def stop(self):
        """서버 종료 (더 안전하게 개선)"""
        # 이미 종료된 상태면 아무것도 하지 않음
        if not self.running:
            return
            
        self.running = False
        
        # 프로세스 타이머 중지
        if hasattr(self, 'process_timer') and self.process_timer.isActive():
            self.process_timer.stop()
        
        # 클라이언트 소켓 종료
        if self.client_socket:
            try:
                # 연결 종료 메시지 전송 시도
                try:
                    goodbye_msg = json.dumps({"status": "shutdown", "message": "Server is shutting down"}) + '\n'
                    self.client_socket.sendall(goodbye_msg.encode('utf-8'))
                except:
                    pass
                    
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
            
        # 서버 소켓 종료
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None
            
        self._print_msg("자막 서버가 종료되었습니다.")

    def _accept_connections(self):
        """클라이언트 연결 수락"""
        while self.running:
            try:
                self.server_socket.settimeout(1.0)  # 1초마다 확인하여 종료 여부 체크
                client_socket, addr = self.server_socket.accept()
                self.client_socket = client_socket
                self._print_msg(f"클라이언트가 연결되었습니다: {addr}")
                
                # 클라이언트 처리 스레드 시작
                client_thread = threading.Thread(target=self._handle_client, args=(client_socket, addr))
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                # 타임아웃은 무시 (running 체크 위한 것)
                continue
            except Exception as e:
                if self.running:  # 정상 종료가 아닌 경우만 에러 출력
                    self._print_msg(f"연결 수락 중 오류 발생: {str(e)}")
                break
                
    def _handle_client(self, client_socket, addr):
        """클라이언트 요청 처리"""
        buffer = b''
        
        try:
            while self.running:
                # 데이터 수신
                data = client_socket.recv(4096)
                
                if not data:
                    # 연결 종료
                    self._print_msg(f"클라이언트 연결이 종료되었습니다: {addr}")
                    break
                    
                # 데이터 처리
                buffer += data
                
                # 완전한 메시지인지 확인 (JSON 형식 가정)
                try:
                    # UTF-8로 디코딩하고 줄바꿈으로 메시지 분할
                    messages = buffer.decode('utf-8').split('\n')
                    
                    # 마지막 메시지가 완전하지 않을 수 있으므로 버퍼에 남김
                    buffer = messages[-1].encode('utf-8')
                    
                    # 완전한 메시지 처리를 위해 큐에 추가
                    for message in messages[:-1]:
                        message = message.strip()
                        if message:
                            # 메시지 큐에 추가
                            self.message_queue.put((message, client_socket))
                except UnicodeDecodeError:
                    # 불완전한 UTF-8 시퀀스, 더 많은 데이터 대기
                    continue
                    
        except Exception as e:
            self._print_msg(f"클라이언트 처리 중 오류 발생: {str(e)}")
            
        finally:
            try:
                client_socket.close()
            except:
                pass
            
            # 현재 소켓이 종료된 소켓과 같으면 초기화
            if self.client_socket == client_socket:
                self.client_socket = None
                
    def _process_message_queue(self):
        """메인 스레드에서 메시지 큐 처리 (견고성 향상)"""
        if not hasattr(self, 'caption_overlay') or self.caption_overlay is None:
            return
            
        try:
            # 큐에 메시지가 있으면 처리
            while not self.message_queue.empty():
                try:
                    message, client_socket = self.message_queue.get_nowait()
                    try:
                        self._process_single_message(message, client_socket)
                    except Exception as e:
                        self._print_msg(f"메시지 처리 중 오류 발생: {str(e)}")
                    finally:
                        self.message_queue.task_done()
                except queue.Empty:
                    break
        except Exception as e:
            self._print_msg(f"메시지 큐 처리 중 예외 발생: {str(e)}")
    
    def _process_single_message(self, message, client_socket):
        """단일 메시지 처리 (새 접근법 버전)"""
        try:
            data = json.loads(message)
            
            # clear 명령 처리 (추가된 부분)
            if 'clear' in data and data['clear']:
                self.caption_overlay.clear_screen()
                self._print_msg("화면 지우기 명령을 받았습니다.")
                return self._send_response({"status": "ok", "message": "Screen cleared"}, client_socket)
            
            # 명령어 처리
            if 'command' in data:
                command = data['command']
                
                if command == 'show':
                    # 자막 표시
                    if not self.caption_overlay.visible:
                        self.caption_overlay.toggle_visibility()
                    self._print_msg("자막 표시 명령을 받았습니다.")
                    return self._send_response({"status": "ok", "message": "Caption shown"}, client_socket)
                    
                elif command == 'hide':
                    # 자막 숨기기
                    if self.caption_overlay.visible:
                        self.caption_overlay.toggle_visibility()
                    self._print_msg("자막 숨기기 명령을 받았습니다.")
                    return self._send_response({"status": "ok", "message": "Caption hidden"}, client_socket)
                    
                elif command == 'force_clear':
                    # 강제 화면 초기화
                    self.caption_overlay.force_clear_and_update()
                    self._print_msg("강제 화면 초기화 명령을 받았습니다.")
                    return self._send_response({"status": "ok", "message": "Screen forcibly cleared"}, client_socket)

                elif command == 'status':
                    # 상태 반환
                    status = "visible" if self.caption_overlay.visible else "hidden"
                    
                    # 현재 설정 상태도 함께 반환
                    current_settings = {
                        "position": self.caption_overlay.settings["position"]["location"],
                        "font_size": self.caption_overlay.settings["font"]["size"],
                        "display_duration": self.caption_overlay.settings["display"]["duration"],
                        "translation_enabled": self.caption_overlay.settings.get("translation", {}).get("enabled", True)
                    }
                    
                    self._print_msg(f"상태 요청 - 현재 자막: {status}, 설정: {current_settings}")
                    return self._send_response({
                        "status": "ok", 
                        "caption_visible": self.caption_overlay.visible,
                        "settings": current_settings
                    }, client_socket)
                    
                elif command == 'exit':
                    # 프로그램 종료
                    self._print_msg("종료 명령을 받았습니다.")
                    self._send_response({"status": "ok", "message": "Exiting"}, client_socket)
                    
                    # Qt 메인 스레드에서 안전하게 종료
                    QTimer.singleShot(500, self.caption_overlay.close_application)
                    return
                    
                else:
                    self._print_msg(f"알 수 없는 명령: {command}")
                    return self._send_response({"status": "error", "message": f"Unknown command: {command}"}, client_socket)
            
            # 자막 처리
            if 'text' in data:
                # 자막 텍스트 설정
                text = data['text']
                duration = data.get('duration', None)
                self.caption_overlay.set_caption(text, duration)
                
                # 로그에 자막 내용 요약 표시 (너무 길면 잘라서 표시)
                if len(text) > 50:
                    summary = text[:47] + "..."
                else:
                    summary = text
                    
                self._print_msg(f"자막 텍스트 수신: {summary}")
                return self._send_response({"status": "ok", "message": "Caption set"}, client_socket)
                
            # 설정 업데이트
            if 'settings' in data:
                # 설정 업데이트 전에 주요 설정 값 백업 (로깅용)
                old_settings = {}
                if 'font' in data['settings'] and 'size' in data['settings']['font']:
                    old_settings['font_size'] = self.caption_overlay.settings['font']['size']
                    
                if 'position' in data['settings'] and 'location' in data['settings']['position']:
                    old_settings['position'] = self.caption_overlay.settings['position']['location']
                    
                if 'display' in data['settings'] and 'duration' in data['settings']['display']:
                    old_settings['duration'] = self.caption_overlay.settings['display']['duration']
                
                # 설정 업데이트 실행
                self.caption_overlay.update_settings(data['settings'])
                
                # 설정 변경 로그 출력
                changes = []
                for key, old_value in old_settings.items():
                    if key == 'font_size' and 'font' in data['settings'] and 'size' in data['settings']['font']:
                        new_value = data['settings']['font']['size']
                        if old_value != new_value:
                            changes.append(f"글꼴 크기: {old_value}pt -> {new_value}pt")
                            
                    elif key == 'position' and 'position' in data['settings'] and 'location' in data['settings']['position']:
                        new_value = data['settings']['position']['location']
                        if old_value != new_value:
                            changes.append(f"위치: {old_value} -> {new_value}")
                            
                    elif key == 'duration' and 'display' in data['settings'] and 'duration' in data['settings']['display']:
                        new_value = data['settings']['display']['duration']
                        if old_value != new_value:
                            old_text = "계속 표시" if old_value == 0 else f"{old_value//1000}초"
                            new_text = "계속 표시" if new_value == 0 else f"{new_value//1000}초"
                            changes.append(f"표시 시간: {old_text} -> {new_text}")
                
                if changes:
                    self._print_msg(f"설정 업데이트 - 변경사항: {', '.join(changes)}")
                else:
                    self._print_msg("설정 업데이트 - 변경사항 없음")
                    
                return self._send_response({"status": "ok", "message": "Settings updated"}, client_socket)
                
        except json.JSONDecodeError:
            self._print_msg(f"잘못된 JSON 형식: {message}")
            return self._send_response({"status": "error", "message": "Invalid JSON format"}, client_socket)
            
        except Exception as e:
            self._print_msg(f"메시지 처리 중 오류 발생: {str(e)}")
            return self._send_response({"status": "error", "message": str(e)}, client_socket)

    def _send_response(self, response, client_socket):
        """응답 전송"""
        if not client_socket:
            return False
            
        try:
            response_json = json.dumps(response) + '\n'
            client_socket.sendall(response_json.encode('utf-8'))
            return True
        except Exception as e:
            self._print_msg(f"응답 전송 중 오류 발생: {str(e)}")
            return False
            
    def _print_msg(self, msg):
        """스레드 안전한 메시지 출력"""
        with self.print_lock:
            print(f"[Caption Server] {msg}")


class MonitorSelectDialog(QDialog):
    """모니터 선택 대화상자"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("모니터 선택")
        self.setFixedSize(300, 150)
        
        # 항상 위에 표시 설정
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # 레이아웃 설정
        layout = QVBoxLayout(self)
        
        # 모니터 목록 콤보박스
        self.monitor_combo = QComboBox(self)
        self.update_monitor_list()
        layout.addWidget(self.monitor_combo)
        
        # 선택 버튼
        select_button = QPushButton("선택", self)
        select_button.clicked.connect(self.accept)
        layout.addWidget(select_button)
        
        # 취소 버튼
        cancel_button = QPushButton("취소", self)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(cancel_button)
    
    def update_monitor_list(self):
        """사용 가능한 모니터 목록 업데이트"""
        desktop = QDesktopWidget()
        self.monitor_combo.clear()
        
        for i in range(desktop.screenCount()):
            screen_geometry = desktop.screenGeometry(i)
            primary = " (주 모니터)" if i == desktop.primaryScreen() else ""
            self.monitor_combo.addItem(
                f"모니터 {i+1}: {screen_geometry.width()}x{screen_geometry.height()}{primary}", 
                i
            )
    
    def get_selected_monitor(self):
        """선택된 모니터 인덱스 반환"""
        return self.monitor_combo.currentData()


class CaptionOverlay(QMainWindow):
    """
    자막 오버레이 창 클래스
    - 투명한 오버레이로 화면에 자막 표시
    - 항상 다른 창 위에 표시
    - 사용자 설정 가능한 스타일
    """
    def __init__(self, settings=None):
        """자막 오버레이 초기화 (수정된 버전)"""
        super().__init__()
        
        # Mac OS 확인
        self.is_mac = platform.system() == 'Darwin'
        
        # 기본 설정
        self.default_settings = {
            "font": {
                "family": self._get_default_font_family(),
                "size": 24,
                "bold": True,
                "italic": False
            },
            "color": {
                "text": "#FFFFFF",  # 흰색
                "stroke": "#000000",  # 검은색
                "background": "#66000000",  # 반투명 검은색 (ARGB)
                "translation_text": "#f5cc00"  # 번역 텍스트 색상 - 노란색으로 변경
            },
            "position": {
                "location": "bottom",  # top, middle, bottom
                "offset_x": 0,
                "offset_y": 0,
                "monitor": 0  # 기본 모니터(0번)
            },
            "style": {
                "stroke_width": 2,
                "line_spacing": 1.2,
                "max_width": 0.8,  # 화면 너비의 비율
                "background_padding": 10,
                "background_radius": 5
            },
            "display": {
                "duration": 0,  # 자막 표시 시간 (ms) - 0은 '계속 표시'
                "transition": 500,  # 페이드 효과 시간 (ms)
                "max_lines": 2     # 최대 표시 줄 수
            },
            "translation": {
                "enabled": True,    # 번역 텍스트 표시 여부
                "separate_color": True  # 번역 텍스트를 다른 색상으로 표시
            }
        }
        
        # 사용자 설정 적용 (UI 초기화 전에 설정만 복사)
        self.settings = self.default_settings.copy()
        if settings:
            self.update_settings(settings)
        
        # 자막 텍스트 및 상태
        self.current_text = ""
        self.text_parts = []
        self.formatted_text_lines = []
        self.history = []  # 최근 자막 기록
        self.max_history = 10
        self.visible = True
        
        # QActionGroup 객체들을 저장할 변수 추가
        self.position_action_group = None
        self.font_size_action_group = None
        self.duration_action_group = None
        self.monitor_action_group = None  # 추가된 부분

        # 로그 디렉토리 생성
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(script_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"로그 디렉토리 생성 중 오류: {str(e)}")
        
        # 타이머 설정 (자동 숨김용) - 초기화 순서 변경
        self.hide_timer = QTimer(self)
        self.hide_timer.timeout.connect(self.hide_caption)
        
        # 잔상 관련 플래그 추가
        self.clear_needed = False
        self.last_paint_time = time.time()

        # 더블 버퍼링 설정 (선택적)
        self.use_double_buffering = False

        # UI 초기화
        self.init_ui()
        
        # 메뉴바 초기화
        self.create_menu_bar()
        
        # 시스템 트레이 아이콘은 Mac에서는 필요에 따라 생성 (문제 발생 시 건너뛰기)
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.create_tray_icon()
        except Exception as e:
            print(f"트레이 아이콘 생성 중 오류 발생: {e}")
            print("트레이 아이콘 없이 계속 진행합니다.")
        
        # 투명 윈도우를 위한 추가 설정
        self.setAttribute(Qt.WA_NoSystemBackground, True)  # 시스템 배경 비활성화
        self.setAutoFillBackground(False)  # 자동 배경 채우기 비활성화

        # 투명 윈도우 스타일시트 설정
        self.setStyleSheet("background-color: transparent;")
        
        # 잔상 제거를 위한 플래그
        self.clear_needed = False

        # 단축키 설정
        self.setup_shortcuts()
        
        # 위치 조정
        self.update_position()
        
        # 소켓 서버 초기화 및 시작
        self.server = CaptionServer(self)
        self.server.start()
        
        # 설정 로드 로그
        self.log_settings_change("설정 로드", "기본값", "사용자 설정")
    
    def force_clear_and_update(self):
        """화면을 강제로 지우고 업데이트"""
        # 데이터 초기화
        self.current_text = ""
        self.text_parts = []
        self.formatted_text_lines = []
        self.text_width = 0
        self.text_height = 0
        self.bg_width = 0
        self.bg_height = 0
        
        # 화면 지우기
        self.clear_screen()
        
        # 버퍼 재초기화
        self.initialize_buffer()
        
        # 강제 갱신
        self.update()
        self.repaint()
        QApplication.processEvents()

    def change_font_family(self, family):
        """글꼴 패밀리 변경"""
        # 이전 값 저장
        old_family = self.settings["font"]["family"]
        
        # 값이 변경되지 않았으면 무시
        if old_family == family:
            return
        
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 폰트 패밀리 변경
        self.settings["font"]["family"] = family
        
        # 로깅
        self.log_settings_change("글꼴 패밀리", old_family, family)
        
        # 설정 동기화
        self.save_settings_to_main_config()
        
        # 텍스트 복원 (내용이 있었을 경우)
        if current_text:
            self.set_caption(current_text)
        
        # 메뉴 액션 상태 업데이트
        if hasattr(self, 'font_family_action_group'):
            for action in self.font_family_action_group.actions():
                if action.data() == family:
                    action.setChecked(True)

    def _get_default_font_family(self):
        """OS에 따른 기본 폰트 가져오기"""
        if platform.system() == 'Darwin':  # macOS
            return "AppleGothic"  # 맥 OS의 한글 기본 폰트
        elif platform.system() == 'Windows':
            return "맑은 고딕"
        else:  # Linux 등
            return "Sans"
    
    def change_color(self, color_type):
        """색상 변경 다이얼로그"""
        from PyQt5.QtWidgets import QColorDialog
        
        # 현재 색상 가져오기
        color_string = self.settings["color"][color_type]
        
        # ARGB 형식 처리 (#AARRGGBB)
        if len(color_string) == 9 and color_string.startswith('#'):
            alpha = int(color_string[1:3], 16)
            r = int(color_string[3:5], 16)
            g = int(color_string[5:7], 16)
            b = int(color_string[7:9], 16)
            current_color = QColor(r, g, b, alpha)
        else:
            # RGB 형식 (#RRGGBB)
            current_color = QColor(color_string)
        
        # 색상 선택 대화상자 표시
        color_dialog = QColorDialog(current_color, self)
        
        # 메인 윈도우 중앙에 표시
        color_dialog.setWindowTitle(f"색상 선택")
        
        # 투명도 선택 활성화 (배경색에만 적용)
        if color_type == 'background':
            color_dialog.setOption(QColorDialog.ShowAlphaChannel, True)
        
        # 색상 선택 실행
        if color_dialog.exec_():
            # 선택된 색상 가져오기
            selected_color = color_dialog.selectedColor()
            
            # 이전 색상 저장
            old_color = self.settings["color"][color_type]
            
            # RGBA 형식으로 변환 (배경색용)
            if color_type == 'background':
                # ARGB 형식으로 변환 (#AARRGGBB)
                color_value = f"#{selected_color.alpha():02x}{selected_color.red():02x}{selected_color.green():02x}{selected_color.blue():02x}"
            else:
                # RGB 형식으로 변환 (#RRGGBB)
                color_value = f"#{selected_color.red():02x}{selected_color.green():02x}{selected_color.blue():02x}"
            
            # 색상 변경
            self.settings["color"][color_type] = color_value
            
            # 색상 타입에 따른 한글 이름 설정
            color_name_map = {
                'text': '자막 텍스트',
                'translation_text': '번역 텍스트',
                'background': '배경'
            }
            color_name = color_name_map.get(color_type, color_type)
            
            # 로깅
            self.log_settings_change(f"{color_name} 색상", old_color, color_value)
            
            # 설정 동기화
            self.save_settings_to_main_config()
            
            # 현재 텍스트가 있으면 갱신
            if self.current_text:
                self.set_caption(self.current_text)
                
            return True
        
        return False

    def create_menu_bar(self):
        """메뉴바 생성 (개선된 버전)"""
        # 메뉴바 설정
        menubar = self.menuBar()
        
        # 파일 메뉴
        file_menu = menubar.addMenu('파일')
        
        # 종료 액션
        exit_action = QAction('종료', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close_application)
        file_menu.addAction(exit_action)
        
        # 보기 메뉴
        view_menu = menubar.addMenu('보기')
        
        # 보이기/숨기기 액션
        toggle_action = QAction('보이기/숨기기', self)
        toggle_action.setShortcut('Space')
        toggle_action.triggered.connect(self.toggle_visibility)
        view_menu.addAction(toggle_action)
        
        # 위치 메뉴
        position_menu = view_menu.addMenu('위치')
        
        # 위치 액션 그룹 (라디오 버튼 형태로 동작)
        self.position_action_group = QActionGroup(self)
        self.position_action_group.setExclusive(True)
        
        # 위치별 액션 생성 및 현재 설정에 맞게 체크 표시
        positions = [
            ('top', '상단'),
            ('middle', '중앙'),
            ('bottom', '하단')
        ]
        
        for pos_value, pos_text in positions:
            pos_action = QAction(pos_text, self)
            pos_action.setCheckable(True)
            pos_action.setChecked(self.settings["position"]["location"] == pos_value)
            pos_action.triggered.connect(lambda checked, p=pos_value: self.change_position(p))
            
            self.position_action_group.addAction(pos_action)
            position_menu.addAction(pos_action)
        
        # 모니터 선택 메뉴 (수정된 부분: 대화상자에서 선택 메뉴로 변경)
        monitor_menu = view_menu.addMenu('모니터 선택')
        
        # 모니터 액션 그룹 (라디오 버튼 형태로 동작)
        self.monitor_action_group = QActionGroup(self)
        self.monitor_action_group.setExclusive(True)
        
        # 사용 가능한 모니터 목록 가져오기
        desktop = QDesktopWidget()
        current_monitor = self.settings["position"]["monitor"]
        
        # 모니터별 액션 생성
        for i in range(desktop.screenCount()):
            screen_geometry = desktop.screenGeometry(i)
            primary = " (주 모니터)" if i == desktop.primaryScreen() else ""
            monitor_text = f"모니터 {i+1}: {screen_geometry.width()}x{screen_geometry.height()}{primary}"
            
            monitor_action = QAction(monitor_text, self)
            monitor_action.setCheckable(True)
            monitor_action.setChecked(current_monitor == i)
            monitor_action.triggered.connect(lambda checked, m=i: self.select_monitor_from_menu(m))
            
            self.monitor_action_group.addAction(monitor_action)
            monitor_menu.addAction(monitor_action)
        
        # 설정 메뉴
        settings_menu = menubar.addMenu('설정')
        
        # 글꼴 크기 메뉴
        font_size_menu = settings_menu.addMenu('글꼴 크기')
        
        # 글꼴 크기 액션 그룹
        self.font_size_action_group = QActionGroup(self)
        self.font_size_action_group.setExclusive(True)
        
        for size in [18, 24, 28, 32, 36]:
            size_action = QAction(f'{size}pt', self)
            size_action.setCheckable(True)
            size_action.setChecked(self.settings["font"]["size"] == size)
            size_action.triggered.connect(lambda checked, s=size: self.change_font_size(s))
            
            self.font_size_action_group.addAction(size_action)
            font_size_menu.addAction(size_action)
        
        # 표시 시간 메뉴
        duration_menu = settings_menu.addMenu('표시 시간')
        
        # 표시 시간 액션 그룹
        self.duration_action_group = QActionGroup(self)
        self.duration_action_group.setExclusive(True)
        
        # 표시 시간 옵션
        durations = [
            (3000, "3초"),
            (5000, "5초"),
            (7000, "7초"),
            (10000, "10초"),
            (0, "계속 표시")
        ]
        
        for duration_ms, duration_text in durations:
            duration_action = QAction(duration_text, self)
            duration_action.setCheckable(True)
            duration_action.setChecked(self.settings["display"]["duration"] == duration_ms)
            duration_action.triggered.connect(
                lambda checked, d=duration_ms: self.change_duration(d)
            )
            
            self.duration_action_group.addAction(duration_action)
            duration_menu.addAction(duration_action)
        
        # 글꼴 패밀리 메뉴 (추가)
        font_family_menu = settings_menu.addMenu('글꼴 패밀리')

        # 글꼴 패밀리 액션 그룹
        self.font_family_action_group = QActionGroup(self)
        self.font_family_action_group.setExclusive(True)

        # 운영체제별 글꼴 리스트
        if platform.system() == 'Darwin':  # macOS
            font_families = [
                ('AppleGothic', 'Apple Gothic'),
                ('AppleSDGothicNeo-Regular', '애플 SD 고딕'),
                ('NanumGothic', '나눔고딕'),
                ('NanumMyeongjo', '나눔명조'),
                ('Arial', 'Arial'),
                ('Helvetica', 'Helvetica')
            ]
        elif platform.system() == 'Windows':
            font_families = [
                ('맑은 고딕', '맑은 고딕'),
                ('굴림', '굴림'),
                ('돋움', '돋움'),
                ('바탕', '바탕'),
                ('궁서', '궁서'),
                ('Arial', 'Arial'),
                ('Helvetica', 'Helvetica')
            ]
        else:  # Linux
            font_families = [
                ('Sans', 'Sans'),
                ('Serif', 'Serif'),
                ('Monospace', 'Monospace'),
                ('Arial', 'Arial'),
                ('Helvetica', 'Helvetica')
            ]

        for family_value, family_name in font_families:
            family_action = QAction(family_name, self)
            family_action.setCheckable(True)
            family_action.setChecked(self.settings["font"]["family"] == family_value)
            family_action.setData(family_value)  # 실제 폰트 값 저장
            family_action.triggered.connect(lambda checked, f=family_value: self.change_font_family(f))
            
            self.font_family_action_group.addAction(family_action)
            font_family_menu.addAction(family_action)

        # 색상 설정 메뉴 (추가)
        color_menu = settings_menu.addMenu('색상 설정')

        # 텍스트 색상 설정
        text_color_action = QAction('자막 텍스트 색상', self)
        text_color_action.triggered.connect(lambda: self.change_color('text'))
        color_menu.addAction(text_color_action)

        # 번역 텍스트 색상 설정
        translation_color_action = QAction('번역 텍스트 색상', self)
        translation_color_action.triggered.connect(lambda: self.change_color('translation_text'))
        color_menu.addAction(translation_color_action)

        # 배경 색상 설정
        background_color_action = QAction('배경 색상', self)
        background_color_action.triggered.connect(lambda: self.change_color('background'))
        color_menu.addAction(background_color_action)

        # 도움말 메뉴
        help_menu = menubar.addMenu('도움말')
        
        # 단축키 안내 액션
        shortcut_action = QAction('단축키 안내', self)
        shortcut_action.triggered.connect(self.show_shortcut_info)
        help_menu.addAction(shortcut_action)
        
        # 메뉴바가 캡션을 가리지 않도록 스타일 조정
        if self.is_mac:
            # Mac에서는 메뉴바가 투명할 수 있음
            menubar.setNativeMenuBar(True)
        else:
            # Windows/Linux에서는 메뉴바를 최소화
            menubar.setStyleSheet("QMenuBar { background-color: rgba(0, 0, 0, 120); color: white; }")
            menubar.setFixedHeight(24)


    def create_tray_icon(self):
        """시스템 트레이 아이콘 생성"""
        # 트레이 기능 사용 가능한지 확인
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("시스템 트레이가 지원되지 않습니다.")
            return

        # 아이콘 생성
        self.tray_icon = QSystemTrayIcon(self)

        # 빈 아이콘 생성 (Mac에서 아이콘 문제 시)
        dummy_icon = QIcon()
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        dummy_icon.addPixmap(pixmap)
        self.tray_icon.setIcon(dummy_icon)
        
        # 트레이 아이콘 메뉴
        tray_menu = QMenu()
        
        # 메뉴 항목 추가
        show_action = QAction("보이기/숨기기", self)
        show_action.triggered.connect(self.toggle_visibility)
        tray_menu.addAction(show_action)
        
        select_monitor_action = QAction("모니터 선택", self)
        select_monitor_action.triggered.connect(self.select_monitor)
        tray_menu.addAction(select_monitor_action)
        
        # 구분선
        tray_menu.addSeparator()
        
        # 종료 메뉴
        exit_action = QAction("종료", self)
        exit_action.triggered.connect(self.close_application)
        tray_menu.addAction(exit_action)
        
        # 메뉴 설정
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip("자막 오버레이")
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        # 트레이 아이콘 표시
        self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        """트레이 아이콘 활성화(클릭) 처리"""
        # 좌클릭 시 보이기/숨기기 토글
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visibility()
    
    def init_ui(self):
        """UI 초기화 (더블 버퍼링 지원 추가)"""
        # 창 설정
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        
        if not self.is_mac:
            flags |= Qt.Tool
            
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 배경 투명
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # 활성화 없이 표시
        
        # 전체 화면을 덮는 중앙 위젯
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        
        # 컨텍스트 메뉴 설정
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        # 초기 크기 설정 - 화면 크기에 맞춤
        self.update_window_size()
        
        # 창 제목 설정
        self.setWindowTitle("자막 오버레이")
        
        # 더블 버퍼링을 위한 오프스크린 버퍼 초기화
        self.buffer = None
        self.initialize_buffer()
    

    def initialize_buffer(self):
        """버퍼 초기화 - 불필요한 기능 제거된 버전"""
        # 더블 버퍼링 사용 여부 플래그
        self.use_double_buffering = False
        
        # 더블 버퍼링이 필요한 경우에만 버퍼 생성
        if self.use_double_buffering:
            if hasattr(self, 'buffer') and self.buffer:
                del self.buffer
            
            self.buffer = QPixmap(self.width(), self.height())
            self.buffer.fill(Qt.transparent)

    def force_complete_clear(self):
        """완전한 화면 초기화 - 잔상 제거를 위한 강화된 함수"""
        # 모든 데이터 초기화
        self.current_text = ""
        self.text_parts = []
        self.formatted_text_lines = []
        self.text_width = 0
        self.text_height = 0
        self.bg_width = 0
        self.bg_height = 0
        
        # 화면 지우기 플래그 설정
        self.clear_needed = True
        
        # 화면 갱신 - 여러 번 호출하여 확실하게
        for _ in range(3):  # 3번 반복하여 잔상 방지 강화
            self.update()
            self.repaint()
            QApplication.processEvents()
            time.sleep(0.01)  # 짧은 지연 추가
        
        # 마지막 화면 갱신
        self.update()
        self.repaint()
        QApplication.processEvents()

    def setup_shortcuts(self):
        """단축키 설정"""
        # ESC 키로 종료
        self.exit_shortcut = QKeySequence("Esc")
        self.exit_action = QAction("종료", self)
        self.exit_action.setShortcut(self.exit_shortcut)
        self.exit_action.triggered.connect(self.close_application)
        self.addAction(self.exit_action)
        
        # Spacebar로 보이기/숨기기 토글
        self.toggle_shortcut = QKeySequence("Space")
        self.toggle_action = QAction("보이기/숨기기", self)
        self.toggle_action.setShortcut(self.toggle_shortcut)
        self.toggle_action.triggered.connect(self.toggle_visibility)
        self.addAction(self.toggle_action)
    
    def close_application(self):
        """애플리케이션 종료"""
        # 소켓 서버 종료
        if hasattr(self, 'server'):
            self.server.stop()
            
        # 종료 전 후처리 작업
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        self.close()
        QApplication.instance().quit()
    
    def update_position(self):
        """화면상의 위치 업데이트 (개선된 버전)"""
        desktop = QDesktopWidget()
        monitor_index = self.settings["position"]["monitor"]
        
        # 모니터 인덱스가 유효한지 확인 (범위 초과 시 기본 모니터 사용)
        if monitor_index >= desktop.screenCount():
            monitor_index = desktop.primaryScreen()
            self.settings["position"]["monitor"] = monitor_index
        
        # 선택한 모니터의 geometry 가져오기
        screen_rect = desktop.screenGeometry(monitor_index)
        window_size = self.size()
        
        # 위치 계산
        location = self.settings["position"]["location"]
        offset_x = self.settings["position"]["offset_x"]
        offset_y = self.settings["position"]["offset_y"]
        
        # 항상 x 위치는 화면 왼쪽 경계로 설정 (화면 전체 너비 사용)
        x = screen_rect.x()
        
        # y 위치는 설정에 따라 다르게 계산
        if location == "top":
            y = screen_rect.y() + 50 + offset_y
        elif location == "middle":
            y = screen_rect.y() + (screen_rect.height() - window_size.height()) // 2 + offset_y
        else:  # bottom (기본값)
            y = screen_rect.y() + screen_rect.height() - window_size.height() - 100 + offset_y
        
        self.move(x, y)
    
    def paintEvent(self, event):
        """완전히 개선된 페인트 이벤트 - 잔상 제거 중점"""
        # 페인터 생성
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 전체 창 영역
        window_rect = self.rect()
        
        # 항상 전체 윈도우를 투명하게 지우기 (중요!)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(window_rect, Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
        # 'clear_needed' 플래그가 설정된 경우 지우기만 하고 종료
        if self.clear_needed:
            self.clear_needed = False
            return
        
        # 텍스트가 없으면 그리지 않음
        if not self.current_text or not self.formatted_text_lines:
            return
        
        # 폰트 설정
        font = QFont(
            self.settings["font"]["family"],
            self.settings["font"]["size"]
        )
        font.setBold(self.settings["font"]["bold"])
        font.setItalic(self.settings["font"]["italic"])
        painter.setFont(font)
        
        # 화면 중앙 계산
        screen_center_x = self.width() / 2
        
        # 위치 계산
        location = self.settings["position"]["location"]
        padding = self.settings["style"]["background_padding"]
        offset_y = self.settings["position"]["offset_y"]
        
        if location == "top":
            y_pos = 50 + offset_y
        elif location == "middle":
            y_pos = (self.height() - self.bg_height) / 2 + offset_y
        else:  # bottom (기본값)
            y_pos = self.height() - self.bg_height - 100 + offset_y
        
        # 배경 사각형 위치 계산 (항상 화면 중앙)
        bg_left = screen_center_x - self.bg_width / 2
        bg_rect = QRectF(bg_left, y_pos, self.bg_width, self.bg_height)
        
        # 배경 그리기
        bg_color = QColor(self.settings["color"]["background"])
        radius = self.settings["style"]["background_radius"]
        
        bg_path = QPainterPath()
        bg_path.addRoundedRect(bg_rect, radius, radius)
        painter.fillPath(bg_path, bg_color)
        
        # 텍스트 그리기 시작 위치
        text_y = y_pos + padding
        
        # 텍스트 색상 설정
        text_color = QColor(self.settings["color"]["text"])
        translation_color = QColor(self.settings.get("color", {}).get("translation_text", "#f5cc00"))
        
        # 줄 간격
        line_spacing = int(self.font_metrics.height() * self.settings["style"]["line_spacing"])
        
        # 텍스트 그리기
        for i, lines in enumerate(self.formatted_text_lines):
            # 원본과 번역 텍스트 색상 구분
            if i == 0:
                painter.setPen(text_color)
            else:
                painter.setPen(translation_color)
            
            for line in lines:
                # 각 줄을 개별적으로 중앙 정렬
                line_width = self.font_metrics.horizontalAdvance(line)
                line_x = screen_center_x - line_width / 2
                
                # 텍스트 그리기
                painter.drawText(int(line_x), int(text_y + self.font_metrics.ascent()), line)
                text_y += line_spacing
            
            # 원본과 번역 사이 간격
            if i < len(self.formatted_text_lines) - 1:
                text_y += line_spacing / 2  # 절반의 추가 간격
    
    def format_caption_text(self, text, max_chars_per_line=60):
        """
        자막 텍스트를 포맷팅하여 자동 줄바꿈 처리 (개선된 버전)
        
        Args:
            text (str): 원본 텍스트
            max_chars_per_line (int): 한 줄의 최대 글자 수
            
        Returns:
            str: 줄바꿈이 적용된 텍스트
        """
        if not text:
            return ""
        
        # HTML 태그 처리 (텍스트에 HTML 태그가 있는 경우 보존)
        has_html = any(tag in text for tag in ['<div>', '<span>', '<p>', '<br'])
        if has_html:
            return text  # 이미 HTML 태그가 있으면 그대로 반환
        
        # 기존에 줄바꿈이 있는 경우 각 줄을 처리
        lines = text.split('\n')
        formatted_lines = []
        
        for line in lines:
            if len(line) <= max_chars_per_line:
                formatted_lines.append(line)
            else:
                # 공백 기준으로 단어 분리
                words = line.split(' ')
                current_line = ""
                
                for word in words:
                    # 현재 단어를 추가해도 최대 길이를 초과하지 않는 경우
                    if len(current_line) + len(word) + 1 <= max_chars_per_line:
                        if current_line:
                            current_line += " " + word
                        else:
                            current_line = word
                    else:
                        # 현재 줄이 비어있고 단어가 최대 길이보다 긴 경우 (긴 URL 등)
                        if not current_line and len(word) > max_chars_per_line:
                            # 최대 길이 기준으로 강제 분할
                            chunk_size = max_chars_per_line
                            for i in range(0, len(word), chunk_size):
                                chunk = word[i:i + chunk_size]
                                formatted_lines.append(chunk)
                        else:
                            # 현재 줄을 추가하고 새 줄 시작
                            formatted_lines.append(current_line)
                            current_line = word
                
                # 마지막 줄 추가
                if current_line:
                    formatted_lines.append(current_line)
        
        # HTML 이스케이프 처리 (특수 문자가 있을 경우 HTML 엔티티로 변환)
        escaped_lines = []
        for line in formatted_lines:
            escaped_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            escaped_lines.append(escaped_line)
        
        # <br> 태그로 줄바꿈 처리
        return "<br>".join(escaped_lines)
    
    def set_caption(self, text, duration=None):
        """완전히 개선된 자막 설정 메서드 - 잔상 제거 중점"""
        # 이전 자막 완전히 지우기
        self.force_complete_clear()  # 새로 추가한 함수 사용
        
        if not text:
            self.hide_caption()
            return
        
        # 원본 텍스트 저장
        self.current_text = text
        
        # 번역 텍스트 분리 (빈 줄로 구분된 경우 처리)
        self.text_parts = text.split('\n\n', 1)
        
        # 텍스트 레이아웃 미리 계산
        self.calculate_text_layout()
        
        # 화면 크기/위치 업데이트
        self.update_window_size()
        self.update_position()
        
        # 이력에 추가
        self.history.append(text)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        
        # 창 표시
        if not self.isVisible():
            self.show()
            self.visible = True
        
        # 화면 강제 갱신
        self.repaint()
        
        # 이벤트 처리 확인
        QApplication.processEvents()
        
        # 타이머 설정 (자동 숨김)
        if duration is None:
            duration = self.settings["display"]["duration"]
            
        if duration > 0:
            self.hide_timer.stop()
            self.hide_timer.start(duration)
        else:
            # 계속 표시
            self.hide_timer.stop()

    def clear_screen(self):
        """화면 완전히 지우기 - 개선된 버전"""
        # 전체 자막 데이터 초기화
        self.current_text = ""
        self.text_parts = []
        self.formatted_text_lines = []
        
        # 지우기 플래그 설정
        self.clear_needed = True
        
        # 즉시 화면 갱신
        self.repaint()
        
        # 이벤트 처리 확인 (중요)
        QApplication.processEvents()


    def calculate_text_layout(self):
        """텍스트 레이아웃 계산 (줄바꿈, 위치 등)"""
        # 화면 정보 가져오기
        desktop = QDesktopWidget()
        monitor_index = self.settings["position"]["monitor"]
        screen_rect = desktop.screenGeometry(monitor_index)
        screen_width = screen_rect.width()
        
        # 폰트 설정
        font = QFont(
            self.settings["font"]["family"],
            self.settings["font"]["size"]
        )
        font.setBold(self.settings["font"]["bold"])
        font.setItalic(self.settings["font"]["italic"])
        
        # 폰트 메트릭스 생성 (텍스트 크기 계산용)
        self.font_metrics = QFontMetrics(font)
        
        # 최대 텍스트 너비 계산 (화면 너비의 80%)
        max_text_width = int(screen_width * 0.8)
        
        # 줄바꿈 처리된 텍스트 저장
        self.formatted_text_lines = []
        
        # 원본 텍스트 처리
        if len(self.text_parts) > 0:
            original_text = self.text_parts[0]
            self.formatted_text_lines.append(
                self.wrap_text(original_text, max_text_width, self.font_metrics)
            )
        
        # 번역 텍스트 처리 (있는 경우)
        if len(self.text_parts) > 1 and self.settings.get("translation", {}).get("enabled", True):
            translation_text = self.text_parts[1]
            self.formatted_text_lines.append(
                self.wrap_text(translation_text, max_text_width, self.font_metrics)
            )
        
        # 텍스트 가로 크기 계산 (가장 긴 줄 기준)
        self.text_width = 0
        for lines in self.formatted_text_lines:
            for line in lines:
                line_width = self.font_metrics.horizontalAdvance(line)
                self.text_width = max(self.text_width, line_width)
        
        # 전체 텍스트 높이 계산
        self.text_height = 0
        line_spacing = int(self.font_metrics.height() * self.settings["style"]["line_spacing"])
        
        for i, lines in enumerate(self.formatted_text_lines):
            self.text_height += len(lines) * line_spacing
            
            # 원본과 번역 사이 간격 추가 (번역이 있는 경우)
            if i < len(self.formatted_text_lines) - 1:
                self.text_height += line_spacing
        
        # 배경 크기 계산 (여백 추가)
        padding = self.settings["style"]["background_padding"]
        self.bg_width = self.text_width + padding * 2
        self.bg_height = self.text_height + padding * 2
        
        # 최소 배경 너비 (너무 짧은 텍스트도 적절한 배경 크기 유지)
        min_bg_width = 200
        self.bg_width = max(self.bg_width, min_bg_width)

    def wrap_text(self, text, max_width, font_metrics):
        """텍스트 자동 줄바꿈 처리"""
        result_lines = []
        
        # 이미 줄바꿈이 있는 경우 각 줄을 처리
        lines = text.split('\n')
        
        for line in lines:
            if font_metrics.horizontalAdvance(line) <= max_width:
                # 짧은 줄은 그대로 추가
                result_lines.append(line)
            else:
                # 긴 줄은 단어 단위로 분할
                words = line.split(' ')
                current_line = ""
                
                for word in words:
                    # 현재 단어를 추가해도 최대 너비를 초과하지 않는 경우
                    test_line = current_line + (" " if current_line else "") + word
                    if font_metrics.horizontalAdvance(test_line) <= max_width:
                        current_line = test_line
                    else:
                        # 현재 줄이 비어있고 단어가 최대 너비보다 긴 경우
                        if not current_line:
                            # 최대한 채워서 분할
                            for char in word:
                                test_line = current_line + char
                                if font_metrics.horizontalAdvance(test_line) <= max_width:
                                    current_line = test_line
                                else:
                                    if current_line:
                                        result_lines.append(current_line)
                                    current_line = char
                            if current_line:
                                result_lines.append(current_line)
                                current_line = ""
                        else:
                            # 현재 줄을 추가하고 새 줄 시작
                            result_lines.append(current_line)
                            current_line = word
                
                # 마지막 줄 추가
                if current_line:
                    result_lines.append(current_line)
        
        return result_lines

    def update_window_size(self):
        """창 크기 업데이트 (버퍼 크기도 함께 업데이트)"""
        desktop = QDesktopWidget()
        monitor_index = self.settings["position"]["monitor"]
        
        if monitor_index < desktop.screenCount():
            screen_rect = desktop.screenGeometry(monitor_index)
        else:
            screen_rect = desktop.availableGeometry()
        
        # 창 크기는 항상 화면 전체로 설정
        self.resize(screen_rect.width(), screen_rect.height())
        
        # 창 크기 변경 시 버퍼도 재생성
        if hasattr(self, 'initialize_buffer'):
            self.initialize_buffer()

    def resizeEvent(self, event):
        """창 크기 변경 이벤트 처리 - 더 강화된 버전"""
        # 화면 완전 초기화
        self.force_complete_clear()
        
        # 필요한 경우만 버퍼 초기화
        if hasattr(self, 'use_double_buffering') and self.use_double_buffering:
            self.initialize_buffer()
        
        # 부모 클래스 메서드 호출
        super().resizeEvent(event)
        
        # 크기 변경 후 추가 화면 갱신
        self.update()
        QApplication.processEvents()

    def hide_caption(self):
        """완전히 개선된 자막 숨기기 - 잔상 제거 중점"""
        # 타이머 중지
        self.hide_timer.stop()
        
        # 자막 관련 모든 데이터 완전 초기화
        self.current_text = ""
        self.text_parts = []
        self.formatted_text_lines = []
        self.text_width = 0
        self.text_height = 0
        self.bg_width = 0
        self.bg_height = 0
        
        # 화면 지우기를 두 번 호출하여 확실하게 지우기
        self.clear_screen()
        
        # 모든 그리기 작업이 완료될 때까지 대기
        QApplication.processEvents()
        
        # 화면 갱신 후 숨기기
        self.visible = False
        self.hide()

    def showEvent(self, event):
        """창이 표시될 때 이벤트 처리 - 개선된 버전"""
        super().showEvent(event)
        
        # 화면 지우기
        self.clear_screen()
        
        # 화면 갱신
        self.repaint()
        QApplication.processEvents()

    def toggle_visibility(self):
        """자막 표시/숨김 토글 (개선된 버전)"""
        if self.visible:
            self.hide_caption()
        else:
            # 화면 완전 초기화 후 표시
            self.force_clear_and_update()
            
            if self.history:
                self.set_caption(self.history[-1])
            else:
                self.set_caption("자막 오버레이가 활성화되었습니다.")
    
    def select_monitor(self):
        """모니터 선택 대화상자 표시 (비모달 방식으로 개선)"""
        # 대화상자 생성
        self.monitor_dialog = MonitorSelectDialog(self)
        
        # 현재 선택된 모니터 설정
        current_monitor = self.settings["position"]["monitor"]
        if current_monitor < self.monitor_dialog.monitor_combo.count():
            self.monitor_dialog.monitor_combo.setCurrentIndex(current_monitor)
        
        # 대화상자 비모달로 설정
        self.monitor_dialog.setWindowModality(Qt.NonModal)
        
        # 대화상자 결과 처리를 위한 연결
        self.monitor_dialog.accepted.connect(self._handle_monitor_selection)
        
        # 대화상자 표시
        self.monitor_dialog.show()
    
    def _handle_monitor_selection(self):
        """모니터 선택 결과 처리"""
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 선택된 모니터 가져오기
        selected_monitor = self.monitor_dialog.get_selected_monitor()
        
        # 모니터가 변경되었을 경우에만 처리
        if selected_monitor != self.settings["position"]["monitor"]:
            self.settings["position"]["monitor"] = selected_monitor
            self.update_position()
            
            # 변경된 모니터로 이동했음을 알림
            desktop = QDesktopWidget()
            if selected_monitor < desktop.screenCount():
                monitor_info = desktop.screenGeometry(selected_monitor)
                
                # 모니터 변경 메시지 표시 후 원래 텍스트 복원
                if current_text:
                    # 모니터 변경 메시지와 함께 원래 텍스트 표시
                    new_text = f"모니터 {selected_monitor+1}로 이동했습니다.\n({monitor_info.width()}x{monitor_info.height()})\n\n{current_text}"
                    self.set_caption(new_text)
                else:
                    # 원래 텍스트가 없었으면 모니터 변경 메시지만 표시
                    self.set_caption(f"모니터 {selected_monitor+1}로 이동했습니다.\n({monitor_info.width()}x{monitor_info.height()})")

    def update_settings(self, settings):
        """설정 업데이트 (새 접근법 버전)"""
        # 깊은 복사를 사용하여 중첩된 설정 업데이트
        def update_nested_dict(target, source):
            for key, value in source.items():
                if isinstance(value, dict) and key in target:
                    update_nested_dict(target[key], value)
                else:
                    target[key] = value
        
        update_nested_dict(self.settings, settings)
        
        # 현재 텍스트가 있으면 갱신
        if hasattr(self, 'current_text') and self.current_text:
            self.set_caption(self.current_text)
        
        # 설정 동기화
        if hasattr(self, 'save_settings_to_main_config'):
            self.save_settings_to_main_config()
        
        return True
    
    def save_settings_to_main_config(self):
        """현재 설정을 메인 설정 파일로 저장하여 main.py와 동기화"""
        try:
            # 설정 파일 경로
            script_dir = os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(script_dir, "settings.json")
            
            if os.path.exists(settings_path):
                # 기존 설정 파일 로드
                with open(settings_path, 'r', encoding='utf-8') as f:
                    main_settings = json.load(f)
                
                # 자막 설정 업데이트
                if "caption" not in main_settings:
                    main_settings["caption"] = {}
                
                # 설정 매핑 및 변환
                caption_settings = main_settings["caption"]
                
                # font_size 설정
                caption_settings["font_size"] = self.settings["font"]["size"]
                
                # font_family 설정 (추가)
                caption_settings["font_family"] = self.settings["font"]["family"]
                
                # position 설정
                caption_settings["position"] = self.settings["position"]["location"]
                
                # monitor 설정 (추가)
                caption_settings["monitor"] = self.settings["position"]["monitor"]
                
                # display_duration 설정
                caption_settings["display_duration"] = self.settings["display"]["duration"]
                
                # 색상 설정 (추가)
                caption_settings["text_color"] = self.settings["color"]["text"]
                caption_settings["translation_color"] = self.settings["color"]["translation_text"]
                caption_settings["background_color"] = self.settings["color"]["background"]
                
                # 번역 텍스트 표시 여부 설정 (기존 값 유지)
                if "show_translation" not in caption_settings:
                    caption_settings["show_translation"] = True
                
                # 설정 파일 저장
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(main_settings, f, ensure_ascii=False, indent=2)
                
                print(f"자막 설정이 메인 설정에 동기화되었습니다: {settings_path}")
                return True
                
            else:
                print(f"메인 설정 파일을 찾을 수 없습니다: {settings_path}")
                return False
                
        except Exception as e:
            print(f"설정 동기화 중 오류 발생: {str(e)}")
            return False

    def show_context_menu(self, position):
        """컨텍스트 메뉴 표시 (개선된 버전)"""
        menu = QMenu(self)
        
        # 위치 메뉴
        position_menu = menu.addMenu("위치")
        
        # 위치 액션 그룹 (라디오 버튼 형태로 동작)
        position_action_group = QActionGroup(self)
        position_action_group.setExclusive(True)
        
        # 위치별 액션 생성 및 현재 설정에 맞게 체크 표시
        positions = [
            ('top', '상단'),
            ('middle', '중앙'),
            ('bottom', '하단')
        ]
        
        for pos_value, pos_text in positions:
            pos_action = QAction(pos_text, self)
            pos_action.setCheckable(True)
            pos_action.setChecked(self.settings["position"]["location"] == pos_value)
            pos_action.triggered.connect(lambda checked, p=pos_value: self.change_position(p))
            
            position_action_group.addAction(pos_action)
            position_menu.addAction(pos_action)
        
        # 모니터 선택 메뉴 (수정된 부분: 대화상자에서 선택 메뉴로 변경)
        monitor_menu = menu.addMenu("모니터 선택")
        
        # 모니터 액션 그룹
        monitor_action_group = QActionGroup(self)
        monitor_action_group.setExclusive(True)
        
        # 사용 가능한 모니터 목록 가져오기
        desktop = QDesktopWidget()
        current_monitor = self.settings["position"]["monitor"]
        
        # 모니터별 액션 생성
        for i in range(desktop.screenCount()):
            screen_geometry = desktop.screenGeometry(i)
            primary = " (주 모니터)" if i == desktop.primaryScreen() else ""
            monitor_text = f"모니터 {i+1}: {screen_geometry.width()}x{screen_geometry.height()}{primary}"
            
            monitor_action = QAction(monitor_text, self)
            monitor_action.setCheckable(True)
            monitor_action.setChecked(current_monitor == i)
            monitor_action.triggered.connect(lambda checked, m=i: self.select_monitor_from_menu(m))
            
            monitor_action_group.addAction(monitor_action)
            monitor_menu.addAction(monitor_action)

        # 메뉴 구분선
        menu.addSeparator()
        
        # 글꼴 크기 메뉴
        size_menu = menu.addMenu("글꼴 크기")
        
        # 글꼴 크기 액션 그룹
        font_size_action_group = QActionGroup(self)
        font_size_action_group.setExclusive(True)
        
        for size in [18, 24, 28, 32, 36]:
            size_action = QAction(f"{size}pt", self)
            size_action.setCheckable(True)
            size_action.setChecked(self.settings["font"]["size"] == size)
            size_action.triggered.connect(lambda checked, s=size: self.change_font_size(s))
            
            font_size_action_group.addAction(size_action)
            size_menu.addAction(size_action)
        
        # 표시 시간
        duration_menu = menu.addMenu("표시 시간")
        
        # 표시 시간 액션 그룹
        duration_action_group = QActionGroup(self)
        duration_action_group.setExclusive(True)
        
        durations = [
            (3000, "3초"),
            (5000, "5초"),
            (7000, "7초"),
            (10000, "10초"),
            (0, "계속 표시")
        ]
        
        for duration_ms, duration_text in durations:
            duration_action = QAction(duration_text, self)
            duration_action.setCheckable(True)
            duration_action.setChecked(self.settings["display"]["duration"] == duration_ms)
            duration_action.triggered.connect(
                lambda checked, d=duration_ms: self.change_duration(d)
            )
            
            duration_action_group.addAction(duration_action)
            duration_menu.addAction(duration_action)
                
        # 글꼴 패밀리 메뉴 (컨텍스트 메뉴에 추가)
        font_family_menu = menu.addMenu("글꼴 패밀리")

        # 글꼴 패밀리 액션 그룹
        font_family_action_group = QActionGroup(self)
        font_family_action_group.setExclusive(True)

        if platform.system() == 'Darwin':  # macOS
            font_families = [
                ('AppleGothic', 'Apple Gothic'),
                ('AppleSDGothicNeo-Regular', '애플 SD 고딕'),
                ('NanumGothic', '나눔고딕'),
                ('NanumMyeongjo', '나눔명조'),
                ('Arial', 'Arial'),
                ('Helvetica', 'Helvetica')
            ]
        elif platform.system() == 'Windows':
            font_families = [
                ('맑은 고딕', '맑은 고딕'),
                ('굴림', '굴림'),
                ('돋움', '돋움'),
                ('바탕', '바탕'),
                ('궁서', '궁서'),
                ('Arial', 'Arial'),
                ('Helvetica', 'Helvetica')
            ]
        else:  # Linux
            font_families = [
                ('Sans', 'Sans'),
                ('Serif', 'Serif'),
                ('Monospace', 'Monospace'),
                ('Arial', 'Arial'),
                ('Helvetica', 'Helvetica')
            ]

        for family_value, family_name in font_families:
            family_action = QAction(family_name, self)
            family_action.setCheckable(True)
            family_action.setChecked(self.settings["font"]["family"] == family_value)
            family_action.setData(family_value)  # 실제 폰트 값 저장
            family_action.triggered.connect(lambda checked, f=family_value: self.change_font_family(f))
            
            self.font_family_action_group.addAction(family_action)
            font_family_menu.addAction(family_action)

        # 메뉴 구분선
        menu.addSeparator()

        # 색상 설정 메뉴 (추가)
        color_menu = menu.addMenu("색상 설정")

        # 텍스트 색상 설정
        text_color_action = QAction('자막 텍스트 색상', self)
        text_color_action.triggered.connect(lambda: self.change_color('text'))
        color_menu.addAction(text_color_action)

        # 번역 텍스트 색상 설정
        translation_color_action = QAction('번역 텍스트 색상', self)
        translation_color_action.triggered.connect(lambda: self.change_color('translation_text'))
        color_menu.addAction(translation_color_action)

        # 배경 색상 설정
        background_color_action = QAction('배경 색상', self)
        background_color_action.triggered.connect(lambda: self.change_color('background'))
        color_menu.addAction(background_color_action)

        # 메뉴 구분선
        menu.addSeparator()
        
        # 숨기기/표시
        visibility_action = QAction(
            "숨기기" if self.visible else "표시", 
            self
        )
        visibility_action.triggered.connect(self.toggle_visibility)
        menu.addAction(visibility_action)
        
        # 메뉴 구분선
        menu.addSeparator()
        
        # 단축키 안내
        shortcut_info = QAction("단축키 안내", self)
        shortcut_info.triggered.connect(self.show_shortcut_info)
        menu.addAction(shortcut_info)
        
        # 종료
        exit_action = QAction("종료", self)
        exit_action.triggered.connect(self.close_application)
        menu.addAction(exit_action)
        
        # 메뉴 표시
        menu.exec_(self.mapToGlobal(position))
    
    def select_monitor_from_menu(self, monitor_index):
        """메뉴에서 모니터 선택 시 처리"""
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 모니터가 변경되었을 경우에만 처리
        if monitor_index != self.settings["position"]["monitor"]:
            # 이전 모니터 인덱스
            old_monitor = self.settings["position"]["monitor"]
            
            # 설정 업데이트
            self.settings["position"]["monitor"] = monitor_index
            
            # 로그 메시지
            self.log_settings_change("모니터", f"모니터 {old_monitor+1}", f"모니터 {monitor_index+1}")
            
            # 위치 업데이트
            self.update_position()
            
            # 사용자 피드백을 위한 화면 표시
            desktop = QDesktopWidget()
            if monitor_index < desktop.screenCount():
                monitor_info = desktop.screenGeometry(monitor_index)
                
                # 모니터 변경 메시지 표시 후 원래 텍스트 복원
                if current_text:
                    # 모니터 변경 메시지와 함께 원래 텍스트 표시
                    new_text = f"모니터 {monitor_index+1}로 이동했습니다.\n({monitor_info.width()}x{monitor_info.height()})\n\n{current_text}"
                    self.set_caption(new_text)
                else:
                    # 원래 텍스트가 없었으면 모니터 변경 메시지만 표시
                    self.set_caption(f"모니터 {monitor_index+1}로 이동했습니다.\n({monitor_info.width()}x{monitor_info.height()})")

    def show_shortcut_info(self):
        """단축키 안내 표시"""
        info_text = "[단축키 안내]\n" \
                   "ESC: 프로그램 종료\n" \
                   "Space: 자막 보이기/숨기기"
        self.set_caption(info_text, 5000)
    
    def log_settings_change(self, setting_name, old_value, new_value):
        """설정 변경 로깅"""
        # 콘솔에 로그 출력
        print(f"[설정 변경] {setting_name}: {old_value} -> {new_value}")
        
        # 로그 파일에 기록 (선택적)
        try:
            # 로그 디렉토리 생성
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(script_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            
            # 로그 파일 경로
            log_file = os.path.join(log_dir, "caption_settings.log")
            
            # 로그 메시지 생성
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log_message = f"[{timestamp}] {setting_name}: {old_value} -> {new_value}\n"
            
            # 로그 파일에 추가
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_message)
        except Exception as e:
            print(f"로그 기록 중 오류 발생: {str(e)}")

    def change_position(self, position):
        """자막 위치 변경 (새 접근법 버전)"""
        # 이전 값 저장
        old_position = self.settings["position"]["location"]
        
        # 값이 변경되지 않았으면 무시
        if old_position == position:
            return
        
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 위치 변경
        self.settings["position"]["location"] = position
        
        # 로깅
        self.log_settings_change("위치", old_position, position)
        
        # 설정 동기화
        self.save_settings_to_main_config()
        
        # 창 위치 업데이트
        self.update_position()
        
        # 화면 갱신
        self.update()
        
        # 텍스트 복원 (내용이 있었을 경우)
        if current_text:
            self.set_caption(current_text)
        
        # 메뉴 액션 상태 업데이트
        if hasattr(self, 'position_action_group'):
            for action in self.position_action_group.actions():
                if position == 'top' and action.text() == '상단':
                    action.setChecked(True)
                elif position == 'middle' and action.text() == '중앙':
                    action.setChecked(True)
                elif position == 'bottom' and action.text() == '하단':
                    action.setChecked(True)
    
    def change_font_size(self, size):
        """글꼴 크기 변경 (새 접근법 버전)"""
        # 이전 값 저장
        old_size = self.settings["font"]["size"]
        
        # 값이 변경되지 않았으면 무시
        if old_size == size:
            return
        
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 폰트 크기 변경
        self.settings["font"]["size"] = size
        
        # 로깅
        self.log_settings_change("글꼴 크기", f"{old_size}pt", f"{size}pt")
        
        # 설정 동기화
        self.save_settings_to_main_config()
        
        # 텍스트 복원 (내용이 있었을 경우)
        if current_text:
            self.set_caption(current_text)
        
        # 메뉴 액션 상태 업데이트
        if hasattr(self, 'font_size_action_group'):
            for action in self.font_size_action_group.actions():
                if action.text() == f'{size}pt':
                    action.setChecked(True)
    
    def change_duration(self, duration):
        """표시 시간 변경 (새 접근법 버전)"""
        # 이전 값 저장
        old_duration = self.settings["display"]["duration"]
        
        # 값이 변경되지 않았으면 무시
        if old_duration == duration:
            return
        
        # 설정 변경
        self.settings["display"]["duration"] = duration
        
        # 로깅
        if old_duration == 0:
            old_text = "계속 표시"
        else:
            old_text = f"{old_duration//1000}초"
            
        if duration == 0:
            new_text = "계속 표시"
        else:
            new_text = f"{duration//1000}초"
            
        self.log_settings_change("표시 시간", old_text, new_text)
        
        # 설정 동기화
        self.save_settings_to_main_config()
        
        # 타이머 설정 업데이트
        if self.current_text:
            if duration > 0:
                self.hide_timer.stop()
                self.hide_timer.start(duration)
            else:
                # 계속 표시
                self.hide_timer.stop()
        
        # 메뉴 액션 상태 업데이트
        if hasattr(self, 'duration_action_group'):
            for action in self.duration_action_group.actions():
                duration_text = ""
                if duration == 0:
                    duration_text = "계속 표시"
                else:
                    duration_text = f"{duration//1000}초"
                    
                if action.text() == duration_text:
                    action.setChecked(True)
    
    @pyqtSlot(dict)
    def receive_caption(self, data):
        """외부에서 자막 데이터 수신 (IPC 통신용)"""
        if "text" in data:
            self.set_caption(data["text"], data.get("duration"))
    
    def load_settings_from_file(self, file_path):
        """파일에서 설정 로드"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                self.update_settings(settings)
            return True
        except Exception as e:
            print(f"설정 로드 중 오류: {e}")
            return False
    
    def save_settings_to_file(self, file_path):
        """설정을 파일로 저장"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"설정 저장 중 오류: {e}")
            return False

    def keyPressEvent(self, event):
        """키 입력 이벤트 처리"""
        # ESC 키 종료 기능을 여기에도 추가 (단축키와 중복으로 두 가지 방법 제공)
        if event.key() == Qt.Key_Escape:
            self.close_application()
        elif event.key() == Qt.Key_Space:
            self.toggle_visibility()
        else:
            super().keyPressEvent(event)


class CaptionManager:
    """자막 관리 클래스 - 메인 프로그램과의 통합용"""
    def __init__(self, settings=None):
        """자막 관리자 초기화"""
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.overlay = CaptionOverlay(settings)
        
    def start(self):
        """자막 오버레이 시작"""
        self.overlay.show()
        return self.app.exec_()
    
    def stop(self):
        """자막 오버레이 중지"""
        self.overlay.close_application()
    
    def set_caption(self, text, duration=None):
        """자막 설정"""
        self.overlay.set_caption(text, duration)
    
    def update_settings(self, settings):
        """설정 업데이트"""
        self.overlay.update_settings(settings)
    
    def toggle_visibility(self):
        """자막 표시/숨김 토글"""
        self.overlay.toggle_visibility()
    
    def select_monitor(self, monitor_index):
        """모니터 선택"""
        if 0 <= monitor_index < QDesktopWidget().screenCount():
            # 현재 텍스트 백업
            current_text = self.overlay.current_text
            
            # 모니터 변경
            self.overlay.settings["position"]["monitor"] = monitor_index
            self.overlay.update_position()
            
            # 텍스트 복원
            if current_text:
                self.overlay.set_caption(current_text)
                
            return True
        return False


# 독립 실행용 코드
if __name__ == "__main__":
    # 단독 실행 시 기본 설정으로 자막 오버레이 실행
    app = QApplication(sys.argv)
    
    # Mac OS에 맞는 테스트 설정
    test_settings = {
        "font": {
            "family": "AppleGothic",  # Mac OS용 폰트
            "size": 28,
        },
        "color": {
            "text": "#FFFFFF",
            "background": "#88000000"
        },
        "position": {
            "location": "bottom",
        },
        "display": {
            "duration": 0  # 기본값을 계속 표시로 설정
        }
    }
    
    # 자막 오버레이 생성
    overlay = CaptionOverlay(test_settings)
    
    # 시작 자막 설정 (overlay.show()를 직접 호출하지 않음)
    overlay.set_caption("자막 오버레이가 시작되었습니다.\n[ESC] 키를 누르면 종료됩니다.\n메뉴바 또는 우클릭으로 설정을 변경할 수 있습니다.")
    
    sys.exit(app.exec_())