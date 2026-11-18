import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonWebApp, WebAppInfo

from config import settings
from database.db import init_db
from middlewares.auth import AuthMiddleware
from handlers import (
    start_router,
    common_router,
    admin_customers_router,
    admin_debts_router,
    admin_stats_router,
    customer_debts_router,
    customer_receipt_router
)
from utils.scheduler import setup_scheduler
from api.routes import create_web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("DokonHisobi")

_cloudflared_process: Optional[subprocess.Popen] = None

async def start_cloudflare_tunnel(port: int) -> Optional[str]:
    """Cloudflare bepul HTTPS tunnelini ishga tushirish va URL ni aniqlash"""
    global _cloudflared_process
    cf_bin = Path("cloudflared.exe").absolute()
    if not cf_bin.exists():
        which_cf = shutil.which("cloudflared")
        if which_cf:
            cf_bin = Path(which_cf)

    if not cf_bin.exists():
        logger.info("ℹ️ cloudflared.exe topilmadi. .env dagi MINI_APP_URL ishlatiladi.")
        return None

    # Allaqachon ishlab turgan cloudflared bormi tekshiramiz
    already_running = False
    try:
        out = subprocess.check_output('tasklist /fi "imagename eq cloudflared.exe"', shell=True).decode(errors="ignore")
        if "cloudflared.exe" in out.lower():
            already_running = True
    except Exception:
        pass

    log_file = Path("cloudflare.log").absolute()
    if not already_running:
        logger.info("📡 Cloudflare HTTPS tunnel ishga tushirilmoqda...")
        try:
            if log_file.exists():
                log_file.unlink()
        except Exception:
            pass

        try:
            _cloudflared_process = subprocess.Popen(
                [str(cf_bin), "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=open(log_file, "a", encoding="utf-8", errors="ignore"),
                stderr=subprocess.STDOUT
            )
        except Exception as e:
            logger.warning(f"⚠️ Cloudflare tunnelni ishga tushirishda xatolik: {e}")
            return None

    # Log faylidan HTTPS URL ni kutib olish (maks 15 soniya)
    for _ in range(30):
        await asyncio.sleep(0.5)
        if log_file.exists():
            try:
                content = log_file.read_text(encoding="utf-8", errors="ignore")
                matches = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.trycloudflare\.com", content)
                if matches:
                    url = matches[-1].strip()
                    logger.info(f"🌐 Cloudflare HTTPS tunnel muvaffaqiyatli ulandi: {url}")
                    return url
            except Exception:
                pass

    logger.warning("⚠️ Cloudflare HTTPS tunnel URL aniqlanmadi, .env dagi URL ishlatiladi.")
    return None

async def setup_bot_commands(bot: Bot):
    """Telegram menyusidagi komandalar va Menu tugmasini sozlash"""
    commands = [
        BotCommand(command="start", description="Tizimni ishga tushirish"),
        BotCommand(command="help", description="Yordam va ma'lumot"),
        BotCommand(command="eslatma", description="Qarzdorlarga eslatma yuborish (Admin)")
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        
        # 1. Barcha mijozlar uchun default pastki menyu
        customer_url = "https://dokon-qarzlari-wf96.onrender.com/?role=customer&shop_id=64EB6AB2&v=2.5"
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Mening qarzlarim",
                web_app=WebAppInfo(url=customer_url)
            )
        )

        # 2. Asosiy Admin (7370403444) uchun Do'kon Paneli
        admin_url = "https://dokon-qarzlari-wf96.onrender.com/?role=admin&shop_id=64EB6AB2&v=2.6"
        for aid in settings.get_admin_ids():
            try:
                await bot.set_chat_menu_button(
                    chat_id=aid,
                    menu_button=MenuButtonWebApp(
                        text="Do'kon Paneli",
                        web_app=WebAppInfo(url=admin_url)
                    )
                )
            except Exception:
                pass

        logger.info("✅ Bot komandalari va Menu tugmalari (Admin va Mijoz) muvaffaqiyatli o'rnatildi")
    except Exception as e:
        logger.warning(f"⚠️ Bot komandalarini o'rnatishda xatolik: {e}")

async def keep_alive_task():
    """Render bepul tarifida server uxlab qolmasligi uchun har 3 daqiqada o'zini ping qilish (24/7 rejim)"""
    await asyncio.sleep(15)  # Dastlabki 15 soniya server to'liq ko'tarilishini kutish
    targets = [
        "https://dokon-qarzlari-wf96.onrender.com/health",
        "https://dokon-qarzlari-wf96.onrender.com/api/health",
        "https://dokon-qarzlari-wf96.onrender.com/"
    ]
    headers = {"User-Agent": "DokonHisobi-KeepAlive/2.0"}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        while True:
            for url in targets:
                try:
                    async with session.get(url) as resp:
                        logger.info(f"⚡ 24/7 Keep-alive ping: {url} -> HTTP {resp.status}")
                except Exception as e:
                    logger.debug(f"Keep-alive ping xatosi ({url}): {e}")
            await asyncio.sleep(180)  # Har 3 daqiqada ping (Render 15 daqiqada uxlaydi, 3 daqiqa 100% kafolatlaydi)

async def main():
    logger.info("🚀 'Dokon Hisobi' tizimi ishga tushirilmoqda...")

    # 1. Ma'lumotlar bazasini initsializatsiya qilish
    await init_db()

    # 2. Aiogram Bot va Dispatcher yaratish
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # 3. Middleware ulash
    auth_middleware = AuthMiddleware()
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)

    # 4. Routerlarni ro'yxatdan o'tkazish
    dp.include_routers(
        start_router,
        common_router,
        admin_customers_router,
        admin_debts_router,
        admin_stats_router,
        customer_debts_router,
        customer_receipt_router
    )

    # 5. Mini App va REST API uchun aiohttp veb serverini ishga tushirish
    web_app = create_web_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_SERVER_HOST, port=settings.WEB_SERVER_PORT)
    await site.start()
    logger.info(f"🌐 Mini App va REST API serveri ishga tushdi: http://localhost:{settings.WEB_SERVER_PORT}")

    # 6. Cloudflare HTTPS tunnelni tekshirish / faollashtirish (Mini App Telegramda ishlashi uchun)
    tunnel_url = await start_cloudflare_tunnel(settings.WEB_SERVER_PORT)
    if tunnel_url:
        settings.MINI_APP_URL = tunnel_url

    # 7. Komandalarni Telegramga yozish
    await setup_bot_commands(bot)

    # 8. Eslatmalar schedulerini ishga tushirish
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("⏰ Kunlik eslatmalar scheduleri faollashtirildi (19:00)")

    # 9. Bot pollingni boshlash
    asyncio.create_task(keep_alive_task())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🤖 Bot xabarlarni qabul qilishga tayyor!")

    try:
        await dp.start_polling(bot)
    finally:
        logger.info("🛑 Tizim to'xtatilmoqda...")
        scheduler.shutdown()
        await runner.cleanup()
        await bot.session.close()
        if _cloudflared_process:
            try:
                _cloudflared_process.terminate()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
