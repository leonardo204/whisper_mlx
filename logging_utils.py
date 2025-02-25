import logging
import threading
import time
from collections import defaultdict
import sys

class DuplicateFilter(logging.Filter):
    """
    중복 로그 메시지를 필터링하고 카운팅하는 필터 클래스
    """
    def __init__(self, logger_name):
        super().__init__(logger_name)
        self.last_log = {}  # 마지막 로그 메시지 저장
        self.log_count = defaultdict(int)  # 로그 메시지별 카운트
        self.lock = threading.Lock()  # 스레드 안전성 보장을 위한 락
        self.flush_interval = 5.0  # 중복 카운트 출력 간격 (초)
        self.last_flush_time = time.time()

    def filter(self, record):
        # INFO 레벨 이상은 항상 통과
        if record.levelno >= logging.INFO:
            return True
            
        msg = record.getMessage()
        curr_time = time.time()
        
        with self.lock:
            if msg in self.last_log:
                # 중복된 로그 발견
                self.log_count[msg] += 1
                
                # 일정 간격으로 카운트 정보 출력
                if curr_time - self.last_flush_time > self.flush_interval:
                    for log_msg, count in self.log_count.items():
                        if count > 1:  # 2회 이상 반복된 로그만 표시
                            # 수정된 부분: record.logger 대신 self.logger 사용
                            logging.log(
                                record.levelno, 
                                f"반복 로그 [{count}회]: {log_msg}"
                            )
                    
                    # 카운트 초기화 및 시간 갱신
                    self.log_count.clear()
                    self.last_flush_time = curr_time
                
                return False  # 중복 로그 필터링
            else:
                # 새로운 로그 저장
                self.last_log[msg] = curr_time
                return True  # 새 로그 통과

class LogManager:
    """
    로깅 관리 클래스 - 싱글톤 패턴 적용
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, log_level=logging.DEBUG):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LogManager, cls).__new__(cls)
                cls._instance._initialize(log_level)
            return cls._instance

    def _initialize(self, log_level):
        """로거 초기화"""
        self.logger = logging.getLogger("whisper_transcriber")
        self.logger.setLevel(log_level)

        # 로그 포맷 설정
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 콘솔 핸들러 설정
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)

        # 중복 필터 적용
        duplicate_filter = DuplicateFilter("whisper_transcriber")
        self.logger.addFilter(duplicate_filter)

        # 핸들러 등록
        self.logger.addHandler(console_handler)

        # 에러 추적용 변수
        self.error_count = defaultdict(int)
        self.last_error_time = {}

        self.log_info("로깅 시스템이 초기화되었습니다.")

    def set_log_level(self, level):
        """로그 레벨 설정"""
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)
        self.log_info(f"로그 레벨이 변경되었습니다: {logging.getLevelName(level)}")

    def log_debug(self, message):
        """디버그 레벨 로그"""
        self.logger.debug(message)

    def log_info(self, message):
        """정보 레벨 로그"""
        self.logger.info(message)

    def log_warning(self, message):
        """경고 레벨 로그"""
        self.logger.warning(message)

    def log_error(self, error_type, message):
        """에러 레벨 로그 (중복 카운팅 적용)"""
        current_time = time.time()

        with self._lock:
            self.error_count[error_type] += 1

            # 동일 에러 5초 이내 반복 시 출력 생략
            if error_type in self.last_error_time and \
               current_time - self.last_error_time[error_type] < 5.0:
                return

            # 에러 출력 및 시간 갱신
            count = self.error_count[error_type]
            if count > 1:
                self.logger.error(f"[{error_type}] {message} (발생 횟수: {count})")
            else:
                self.logger.error(f"[{error_type}] {message}")

            self.last_error_time[error_type] = current_time

    def log_critical(self, message):
        """치명적 에러 레벨 로그"""
        self.logger.critical(message)
