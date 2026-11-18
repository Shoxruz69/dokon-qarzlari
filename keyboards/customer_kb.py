from typing import Optional
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
from config import settings

def get_phone_request_kb() -> ReplyKeyboardMarkup:
    """Mijoz uchun telefon raqamni yuborish tugmasi"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamimni yuborish", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_customer_main_kb(customer_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    """Mijoz uchun menyu — faqat o'z qarzlari va do'kon bilan aloqa"""
    base_url = "https://dokon-qarzlari-wf96.onrender.com"
    cid_param = f"&customer_id={customer_id}" if customer_id else ""
    url = f"{base_url}/?role=customer{cid_param}&shop_id=64EB6AB2&v=4.0"

    buttons = [
        [KeyboardButton(text="💳 Mening qarzlarim", web_app=WebAppInfo(url=url))],
        [KeyboardButton(text="📞 Do'kon bilan bog'lanish")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )

def get_customer_inline_kb(customer_id: Optional[int] = None) -> InlineKeyboardMarkup:
    """Mijoz inline yangilash va shaxsiy hisob tugmasi"""
    base_url = "https://dokon-qarzlari-wf96.onrender.com"
    cid_param = f"&customer_id={customer_id}" if customer_id else ""
    url = f"{base_url}/?role=customer{cid_param}&shop_id=64EB6AB2&v=4.0"

    rows = [
        [InlineKeyboardButton(text="📱 Shaxsiy hisob (Mini App)", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="my_debts_refresh")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
