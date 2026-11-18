import os
from pydantic_settings import BaseSettings
from typing import Optional, List, Union

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "9106358155:AAHNO_Uk3IzBP4sqVdB9dgNJ0mrIPb24yec")
    ADMIN_TELEGRAM_ID: Union[int, str] = 7370403444
    MINI_APP_URL: str = "https://dokon-qarzlari-wf96.onrender.com"
    DATABASE_URL: str = ""
    ADMIN_SECRET_CODE: str = "DOKON2025"
    TIMEZONE: str = "Asia/Tashkent"
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEB_SERVER_PORT: int = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", 8080)))

    def get_admin_ids(self) -> List[int]:
        ids = [7370403444]
        for part in str(self.ADMIN_TELEGRAM_ID).replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                aid = int(part)
                if aid != 6876312568:
                    ids.append(aid)
        return list(set(ids))

    def is_admin_id(self, user_id: Union[int, str]) -> bool:
        try:
            uid = int(user_id)
            if uid == 6876312568:
                return False
            return uid == 7370403444 or uid in self.get_admin_ids()
        except Exception:
            return False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
