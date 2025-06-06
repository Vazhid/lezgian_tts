from pathlib import Path
from typing import Optional

class AudioManager:
    AUDIO_HISTORY_DIR: Path

    def __init__(self, audio_history_dir: Path):
        self.AUDIO_HISTORY_DIR = audio_history_dir
        self.AUDIO_HISTORY_DIR.mkdir(exist_ok=True)

    def save_audio(self, audio_data: bytes, filename: str) -> bool:
        try:
            file_path = self.AUDIO_HISTORY_DIR / filename
            with open(file_path, 'wb') as f:
                f.write(audio_data)
            return True
        except Exception:
            return False

    def get_audio_path(self, filename: str) -> Path:
        return self.AUDIO_HISTORY_DIR / filename

    def delete_audio(self, filename: str) -> bool:
        try:
            file_path = self.AUDIO_HISTORY_DIR / filename
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception:
            return False

    def check_access(self, filename: str, user_id: int) -> bool:
        # Заглушка: доступ всегда разрешён (реализация зависит от БД)
        return True 