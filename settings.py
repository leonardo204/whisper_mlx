import os
import json
import logging
from typing import Dict, Any, Optional

class SettingsManager:
    """
    설정 관리 클래스
    - JSON 파일 기반 설정 관리
    - 설정 로드/저장
    - 기본 설정 제공
    """
    def __init__(self, settings_file: str = "settings.json"):
        """설정 관리자 초기화"""
        self.logger = logging.getLogger("whisper_transcriber.settings")
        self.settings_file = settings_file
        
        # 기본 설정 정의
        self.default_settings = {
            "audio": {
                "calibration_duration": 3
            },
            "transcription": {
                "model_name": "large-v3",
                "use_faster_whisper": False,
                "max_history": 1000  # 최대 기록 수 추가
            },
            "translation": {
                "enabled": True,
                "target_language": "ko"
            },
            "output": {
                "save_transcript": True,
                "output_dir": "results"
            },
            "system": {
                "log_level": "info"
            }
        }
        
        # 현재 설정 (기본 설정으로 초기화)
        self.settings = self.default_settings.copy()
        
        # 설정 파일 로드
        self.load_settings()
    
    def load_settings(self) -> Dict:
        """설정 파일 로드"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                
                # 기존 설정과 병합
                self._merge_settings(loaded_settings)
                self.logger.info(f"설정 파일 로드 완료: {self.settings_file}")
            else:
                self.logger.info(f"설정 파일이 없습니다. 기본 설정을 사용합니다.")
                # 기본 설정 파일 생성
                self.save_settings()
        except Exception as e:
            self.logger.error(f"설정 파일 로드 중 오류: {str(e)}")
        
        return self.settings
    
    def save_settings(self) -> bool:
        """현재 설정을 파일로 저장"""
        try:
            # 디렉토리 생성 (필요한 경우)
            os.makedirs(os.path.dirname(os.path.abspath(self.settings_file)), exist_ok=True)
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"설정 파일 저장 완료: {self.settings_file}")
            return True
        except Exception as e:
            self.logger.error(f"설정 파일 저장 중 오류: {str(e)}")
            return False
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """설정 값 가져오기 (점 표기법 지원)"""
        try:
            # 점 표기법 분리 (예: "transcription.model_name")
            keys = key_path.split('.')
            value = self.settings
            
            for key in keys:
                value = value.get(key, {})
            
            # 값이 없거나 중간 키가 딕셔너리가 아닌 경우
            if value == {} and len(keys) > 1:
                return default
            
            return value
        except Exception:
            return default
    
    def set(self, key_path: str, value: Any, save: bool = True) -> bool:
        """설정 값 설정 (점 표기법 지원)"""
        try:
            # 점 표기법 분리
            keys = key_path.split('.')
            
            # 중첩된 딕셔너리에 접근
            target = self.settings
            for key in keys[:-1]:
                if key not in target:
                    target[key] = {}
                target = target[key]
            
            # 최종 값 설정
            target[keys[-1]] = value
            
            # 변경사항 저장 (옵션)
            if save:
                return self.save_settings()
            
            return True
        except Exception as e:
            self.logger.error(f"설정 변경 중 오류: {str(e)}")
            return False
    
    def update_from_args(self, args_dict: Dict) -> None:
        """명령줄 인수에서 설정 업데이트"""
        # 명령줄 인수와 설정 매핑
        mapping = {
            'model': ('transcription.model_name', str),
            'faster_whisper': ('transcription.use_faster_whisper', bool),
            'no_translate': ('translation.enabled', lambda x: not x),
            'translate_to': ('translation.target_language', str),
            'no_save': ('output.save_transcript', lambda x: not x),
            'output_dir': ('output.output_dir', str),
            'debug': ('system.log_level', lambda x: 'debug' if x else 'info'),
            'calibration_duration': ('audio.calibration_duration', int)
        }
        
        for arg_name, (setting_path, converter) in mapping.items():
            if arg_name in args_dict and args_dict[arg_name] is not None:
                value = converter(args_dict[arg_name])
                self.set(setting_path, value, save=False)
        
        # 설정 파일 저장
        self.save_settings()
    
    def _merge_settings(self, new_settings: Dict) -> None:
        """새 설정을 기존 설정과 재귀적으로 병합"""
        for key, value in new_settings.items():
            if key in self.settings and isinstance(self.settings[key], dict) and isinstance(value, dict):
                self._merge_settings_recursive(self.settings[key], value)
            else:
                self.settings[key] = value
    
    def _merge_settings_recursive(self, target: Dict, source: Dict) -> None:
        """딕셔너리 재귀적 병합"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._merge_settings_recursive(target[key], value)
            else:
                target[key] = value
    
    def get_all(self) -> Dict:
        """모든 설정 반환"""
        return self.settings.copy()
    
    def reset_to_default(self) -> None:
        """설정을 기본값으로 초기화"""
        self.settings = self.default_settings.copy()
        self.save_settings()
        self.logger.info("설정이 기본값으로 초기화되었습니다.")