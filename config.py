import os
from pydantic_settings import BaseSettings
from typing import Optional, List, Union

def get_clean_bot_token() -> str:
    raw = os.getenv("BOT_TOKEN", "").strip()
    valid_token = "9106358155:AAHNO_Uk3IzBP4sqVdB9dgNJ0mrIPb24yec"
    if not raw or "AAFkd" in raw or not raw.startswith("9106358155:AAHNO"):
        return valid_token
    return raw

def get_clean_mini_app_url() -> str:
    raw = os.getenv("MINI_APP_URL", "").strip()
    valid_url = "https://dokon-qarzlari-wf96.onrender.com"
    if not raw or "dokon-qarzlari-bot" in raw or not raw.startswith("https://"):
        return valid_url
    return raw.rstrip("/")

class Settings(BaseSettings):
    BOT_TOKEN: str = get_clean_bot_token()
    ADMIN_TELEGRAM_ID: Union[int, str] = os.getenv("ADMIN_TELEGRAM_ID", "6876312568,7370403444")
    MINI_APP_URL: str = get_clean_mini_app_url()
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_6vTKVPerqcz2@ep-divine-dawn-b3gyv6oc-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")
    ADMIN_SECRET_CODE: str = "DOKON2025"
    TIMEZONE: str = "Asia/Tashkent"
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEB_SERVER_PORT: int = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", 8080)))

    def __init__(self, **values):
        super().__init__(**values)
        if not self.BOT_TOKEN or "AAFkd" in self.BOT_TOKEN or not self.BOT_TOKEN.startswith("9106358155:AAHNO"):
            self.BOT_TOKEN = "9106358155:AAHNO_Uk3IzBP4sqVdB9dgNJ0mrIPb24yec"
        if not self.MINI_APP_URL or "dokon-qarzlari-bot" in self.MINI_APP_URL:
            self.MINI_APP_URL = "https://dokon-qarzlari-wf96.onrender.com"

    def get_admin_ids(self) -> List[int]:
        ids = [7370403444, 6876312568]
        for part in str(self.ADMIN_TELEGRAM_ID).replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return list(set(ids))

    def is_admin_id(self, user_id: Union[int, str]) -> bool:
        try:
            uid = int(user_id)
            return uid in self.get_admin_ids()
        except Exception:
            return False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
