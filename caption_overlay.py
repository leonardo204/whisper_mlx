import sys
import json
import socket
import threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                             QWidget, QDesktopWidget, QMenu, QAction, 
                             QSystemTrayIcon, QDialog, QComboBox, QPushButton,
                             QMenuBar)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QPoint, QSize, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPainterPath, QPen, QIcon, QKeySequence, QPixmap
import platform
import queue

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
        """서버 종료"""
        self.running = False
        
        # 프로세스 타이머 중지
        self.process_timer.stop()
        
        # 클라이언트 소켓 종료
        if self.client_socket:
            try:
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
        """
        메인 스레드에서 메시지 큐 처리
        이 메서드는 QTimer를 통해 메인 스레드에서 주기적으로 호출됨
        """
        try:
            # 큐에 메시지가 있으면 처리
            while not self.message_queue.empty():
                message, client_socket = self.message_queue.get_nowait()
                try:
                    self._process_single_message(message, client_socket)
                except Exception as e:
                    self._print_msg(f"메시지 처리 중 오류 발생: {str(e)}")
                finally:
                    self.message_queue.task_done()
        except:
            # 큐 처리 중 오류 무시
            pass
    
    def _process_single_message(self, message, client_socket):
        """단일 메시지 처리 (메인 스레드에서 호출)"""
        try:
            data = json.loads(message)
            
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
                    
                elif command == 'status':
                    # 상태 반환
                    status = "visible" if self.caption_overlay.visible else "hidden"
                    self._print_msg(f"상태 요청 - 현재 자막: {status}")
                    return self._send_response({
                        "status": "ok", 
                        "caption_visible": self.caption_overlay.visible
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
                return self._send_response({"status": "ok", "message": "Caption set"}, client_socket)
                
            # 설정 업데이트
            if 'settings' in data:
                self.caption_overlay.update_settings(data['settings'])
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
        """자막 오버레이 초기화"""
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
                "background": "#66000000"  # 반투명 검은색 (ARGB)
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
            }
        }
        
        # 사용자 설정 적용 (UI 초기화 전에 설정만 복사)
        self.settings = self.default_settings.copy()
        if settings:
            self.update_settings(settings)
        
        # 자막 텍스트 및 상태
        self.current_text = ""
        self.history = []  # 최근 자막 기록
        self.max_history = 10
        self.visible = True
        
        # 타이머 설정 (자동 숨김용) - 초기화 순서 변경
        self.hide_timer = QTimer(self)
        self.hide_timer.timeout.connect(self.hide_caption)
        
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
        
        # 단축키 설정
        self.setup_shortcuts()
        
        # 위치 조정
        self.update_position()
        
        # 소켓 서버 초기화 및 시작
        self.server = CaptionServer(self)
        self.server.start()
    
    def _get_default_font_family(self):
        """OS에 따른 기본 폰트 가져오기"""
        if platform.system() == 'Darwin':  # macOS
            return "AppleGothic"  # 맥 OS의 한글 기본 폰트
        elif platform.system() == 'Windows':
            return "맑은 고딕"
        else:  # Linux 등
            return "Sans"
    
    def create_menu_bar(self):
        """메뉴바 생성"""
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
        
        top_action = QAction('상단', self)
        top_action.triggered.connect(lambda: self.change_position('top'))
        position_menu.addAction(top_action)
        
        middle_action = QAction('중앙', self)
        middle_action.triggered.connect(lambda: self.change_position('middle'))
        position_menu.addAction(middle_action)
        
        bottom_action = QAction('하단', self)
        bottom_action.triggered.connect(lambda: self.change_position('bottom'))
        position_menu.addAction(bottom_action)
        
        # 모니터 선택 액션
        monitor_action = QAction('모니터 선택...', self)
        monitor_action.triggered.connect(self.select_monitor)
        view_menu.addAction(monitor_action)
        
        # 설정 메뉴
        settings_menu = menubar.addMenu('설정')
        
        # 글꼴 크기 메뉴
        font_size_menu = settings_menu.addMenu('글꼴 크기')
        
        for size in [18, 24, 28, 32, 36]:
            size_action = QAction(f'{size}pt', self)
            size_action.triggered.connect(lambda checked, s=size: self.change_font_size(s))
            font_size_menu.addAction(size_action)
        
        # 표시 시간 메뉴
        duration_menu = settings_menu.addMenu('표시 시간')
        
        for seconds in [3, 5, 7, 10, 0]:
            duration_text = f"{seconds}초" if seconds > 0 else "계속 표시"
            duration_action = QAction(duration_text, self)
            duration_action.setCheckable(True)
            duration_action.setChecked(self.settings["display"]["duration"] == seconds * 1000)
            duration_action.triggered.connect(
                lambda checked, s=seconds: self.change_duration(s * 1000)
            )
            duration_menu.addAction(duration_action)
        
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
        """UI 초기화"""
        # 창 설정
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        
        # Mac OS에서는 Qt.Tool 플래그가 약간 다르게 동작할 수 있음
        if not self.is_mac:
            flags |= Qt.Tool
            
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 배경 투명
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # 활성화 없이 표시
        
        # 중앙 위젯 및 레이아웃
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        
        # 자막 라벨
        self.caption_label = QLabel(self)
        self.caption_label.setAlignment(Qt.AlignCenter)
        self.update_label_style()
        
        # 레이아웃
        layout = QVBoxLayout(self.central_widget)
        layout.addWidget(self.caption_label)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 컨텍스트 메뉴 설정
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        # 초기 크기 설정
        screen_size = QDesktopWidget().availableGeometry().size()
        self.resize(int(screen_size.width() * 0.8), 200)
        
        # 창 제목 설정
        self.setWindowTitle("자막 오버레이")
    
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
    
    def update_label_style(self):
        """자막 라벨 스타일 업데이트"""
        # 폰트 설정
        font = QFont(
            self.settings["font"]["family"],
            self.settings["font"]["size"]
        )
        font.setBold(self.settings["font"]["bold"])
        font.setItalic(self.settings["font"]["italic"])
        self.caption_label.setFont(font)
        
        # 스타일시트 설정
        self.caption_label.setStyleSheet(f"""
            QLabel {{
                color: {self.settings["color"]["text"]};
                background-color: transparent;
                padding: {self.settings["style"]["background_padding"]}px;
            }}
        """)
    
    def update_position(self):
        """화면상의 위치 업데이트"""
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
        
        if location == "top":
            x = screen_rect.x() + (screen_rect.width() - window_size.width()) // 2 + offset_x
            y = screen_rect.y() + 50 + offset_y
        elif location == "middle":
            x = screen_rect.x() + (screen_rect.width() - window_size.width()) // 2 + offset_x
            y = screen_rect.y() + (screen_rect.height() - window_size.height()) // 2 + offset_y
        else:  # bottom (기본값)
            x = screen_rect.x() + (screen_rect.width() - window_size.width()) // 2 + offset_x
            y = screen_rect.y() + screen_rect.height() - window_size.height() - 100 + offset_y
        
        self.move(x, y)
    
    def paintEvent(self, event):
        """커스텀 배경 및 테두리 그리기"""
        if not self.current_text:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 텍스트 경계 계산
        text_rect = self.caption_label.contentsRect()
        padding = self.settings["style"]["background_padding"]
        
        # 배경 그리기
        bg_color = QColor(self.settings["color"]["background"])
        radius = self.settings["style"]["background_radius"]
        
        # 배경 경로 설정
        bg_path = QPainterPath()
        bg_rect = text_rect.adjusted(
            -padding, -padding, 
            padding, padding
        )
        # QRect를 QRectF로 변환
        bg_rectf = QRectF(bg_rect)
        bg_path.addRoundedRect(bg_rectf, radius, radius)
        
        # 배경 그리기
        painter.fillPath(bg_path, bg_color)
    
    def set_caption(self, text, duration=None):
        """자막 텍스트 설정"""
        if not text:
            return
            
        self.current_text = text
        self.caption_label.setText(text)
        
        # 이력에 추가
        self.history.append(text)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        
        # 창 크기 조정
        self.adjust_window_size()
        
        # 표시
        if not self.isVisible():
            self.show()
            self.visible = True
        
        # 타이머 설정 (자동 숨김)
        if duration is None:
            duration = self.settings["display"]["duration"]
            
        if duration > 0:
            self.hide_timer.stop()
            self.hide_timer.start(duration)
        else:
            # 계속 표시
            self.hide_timer.stop()
    
    def hide_caption(self):
        """자막 숨기기"""
        self.hide_timer.stop()
        self.hide()
        self.visible = False
        self.current_text = ""
    
    def toggle_visibility(self):
        """자막 표시/숨김 토글"""
        if self.visible:
            self.hide_caption()
        else:
            if self.history:
                self.set_caption(self.history[-1])
            else:
                self.set_caption("자막 오버레이가 활성화되었습니다.")
    
    def select_monitor(self):
        """모니터 선택 대화상자 표시"""
        dialog = MonitorSelectDialog(self)
        
        # 현재 선택된 모니터 설정
        current_monitor = self.settings["position"]["monitor"]
        if current_monitor < dialog.monitor_combo.count():
            dialog.monitor_combo.setCurrentIndex(current_monitor)
        
        # 현재 텍스트 백업 (모니터 변경 후 복원용)
        current_text = self.current_text
        
        # 대화상자 표시 및 결과 처리
        if dialog.exec_() == QDialog.Accepted:
            selected_monitor = dialog.get_selected_monitor()
            
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
    
    def adjust_window_size(self):
        """창 크기를 텍스트에 맞게 조정"""
        text_size = self.caption_label.sizeHint()
        padding = self.settings["style"]["background_padding"] * 2
        
        # 창 크기 설정
        desktop = QDesktopWidget()
        monitor_index = self.settings["position"]["monitor"]
        
        # 선택한 모니터의 geometry 가져오기
        if monitor_index < desktop.screenCount():
            screen_width = desktop.screenGeometry(monitor_index).width()
        else:
            screen_width = desktop.availableGeometry().width()
            
        max_width = int(screen_width * self.settings["style"]["max_width"])
        
        # 최소 너비/높이 설정
        width = min(max(text_size.width() + padding, 200), max_width)
        height = text_size.height() + padding
        
        # 창 크기 업데이트
        self.resize(width, height)
        
        # 위치 업데이트
        self.update_position()
    
    def update_settings(self, settings):
        """설정 업데이트"""
        # 깊은 복사를 사용하여 중첩된 설정 업데이트
        def update_nested_dict(target, source):
            for key, value in source.items():
                if isinstance(value, dict) and key in target:
                    update_nested_dict(target[key], value)
                else:
                    target[key] = value
        
        update_nested_dict(self.settings, settings)
        
        # caption_label이 초기화된 경우에만 스타일 업데이트
        if hasattr(self, 'caption_label'):
            # 스타일 업데이트
            self.update_label_style()
            
            # 위치 업데이트
            self.update_position()
            
            # 크기 업데이트
            if self.current_text:
                self.adjust_window_size()
    
    def show_context_menu(self, position):
        """컨텍스트 메뉴 표시"""
        menu = QMenu(self)
        
        # 위치 메뉴
        position_menu = menu.addMenu("위치")
        
        top_action = QAction("상단", self)
        top_action.triggered.connect(lambda: self.change_position("top"))
        position_menu.addAction(top_action)
        
        middle_action = QAction("중앙", self)
        middle_action.triggered.connect(lambda: self.change_position("middle"))
        position_menu.addAction(middle_action)
        
        bottom_action = QAction("하단", self)
        bottom_action.triggered.connect(lambda: self.change_position("bottom"))
        position_menu.addAction(bottom_action)
        
        # 모니터 선택 메뉴 추가
        monitor_action = QAction("모니터 선택", self)
        monitor_action.triggered.connect(self.select_monitor)
        menu.addAction(monitor_action)
        
        # 글꼴 크기 메뉴
        size_menu = menu.addMenu("글꼴 크기")
        
        for size in [18, 24, 28, 32, 36]:
            size_action = QAction(f"{size}pt", self)
            size_action.triggered.connect(lambda checked, s=size: self.change_font_size(s))
            size_menu.addAction(size_action)
        
        # 표시 시간
        duration_menu = menu.addMenu("표시 시간")
        
        for seconds in [3, 5, 7, 10, 0]:
            duration_text = f"{seconds}초" if seconds > 0 else "계속 표시"
            duration_action = QAction(duration_text, self)
            duration_action.setCheckable(True)
            duration_action.setChecked(self.settings["display"]["duration"] == seconds * 1000)
            duration_action.triggered.connect(
                lambda checked, s=seconds: self.change_duration(s * 1000)
            )
            duration_menu.addAction(duration_action)
        
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
    
    def show_shortcut_info(self):
        """단축키 안내 표시"""
        info_text = "[단축키 안내]\n" \
                   "ESC: 프로그램 종료\n" \
                   "Space: 자막 보이기/숨기기"
        self.set_caption(info_text, 5000)
    
    def change_position(self, position):
        """자막 위치 변경"""
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 위치 변경
        self.settings["position"]["location"] = position
        self.update_position()
        
        # 텍스트 복원 (내용이 있었을 경우)
        if current_text:
            self.set_caption(current_text)
    
    def change_font_size(self, size):
        """글꼴 크기 변경"""
        # 현재 텍스트 백업
        current_text = self.current_text
        
        # 폰트 크기 변경
        self.settings["font"]["size"] = size
        self.update_label_style()
        self.adjust_window_size()
        
        # 텍스트 복원 (내용이 있었을 경우)
        if current_text:
            self.set_caption(current_text)
    
    def change_duration(self, duration):
        """표시 시간 변경"""
        self.settings["display"]["duration"] = duration
        
        # 타이머 설정 업데이트
        if self.current_text:
            if duration > 0:
                self.hide_timer.stop()
                self.hide_timer.start(duration)
            else:
                # 계속 표시
                self.hide_timer.stop()
    
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