import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database.queries import (
    get_customer_by_telegram_id,
    get_customer_by_id,
    get_admin_by_shop_id,
    record_customer_payment
)
from keyboards.customer_kb import get_phone_request_kb
from utils.formatters import esc
from api.routes import invalidate_api_cache

logger = logging.getLogger(__name__)

router = Router()

ADMIN_MAIN_ID = 7370403444

def format_sum(amount: float) -> str:
    return f"{int(amount):,} so'm".replace(",", " ")

@router.message(F.photo)
@router.message(F.document)
async def handle_customer_receipt_photo(message: Message, bot: Bot):
    """Mijoz to'lov chekini yuborganda adminga tasdiqlash uchun yo'naltirish"""
    # Agar document bo'lsa va u rasm bo'lmasa, e'tibor bermaymiz
    if message.document:
        mime = message.document.mime_type or ""
        if not (mime.startswith("image/") or mime == "application/pdf"):
            return

    user_id = message.from_user.id
    # Asosiy admin o'ziga o'zi chek yubormaydi
    if user_id == ADMIN_MAIN_ID:
        return

    customers = await get_customer_by_telegram_id(user_id)
    if not customers:
        text = (
            "👤 <b>Siz hali tizimda telefon raqamingizni tasdiqlamadingiz.</b>\n\n"
            "To'lov chekini qabul qilishimiz va hisobingizni tekshirishimiz uchun "
            "iltimos, pastdagi tugma orqali telefon raqamingizni yuboring:"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=get_phone_request_kb())
        return

    # Odatda bitta do'kondagi mijoz (yoki birinchi mijoz rekordi)
    cust = customers[0]
    cust_id = cust["id"]
    shop_id = cust.get("shop_id") or "64EB6AB2"
    total_debt = float(cust.get("total_debt") or 0.0)
    cust_name = cust.get("full_name") or "Mijoz"
    cust_phone = cust.get("phone") or "Raqam yo'q"
    category = cust.get("category") or "Ko'rsatilmagan"
    shop_name = cust.get("shop_name") or "Kech Harbiy Do'kon"

    # Eng sifatli rasm yoki hujjat file_id sini olish
    if message.photo:
        file_id = message.photo[-1].file_id
        is_photo = True
    else:
        file_id = message.document.file_id
        is_photo = False

    # 1. Mijozga tezkor tasdiq xabari
    await message.reply(
        "✅ <b>To'lov chekingiz qabul qilindi!</b>\n\n"
        "Do'kon ma'muriyati chekni tekshirib, qarzingizni hisobdan o'chiradi. "
        "Natija haqida sizga xabar beriladi. Rahmat! 😊",
        parse_mode="HTML"
    )

    # 2. Adminga yuboriladigan xabar matni va tugmalari
    tashkent_now = datetime.now(ZoneInfo("Asia/Tashkent")).strftime("%d.%m.%Y %H:%M")
    user_caption_text = f"\n💬 <b>Mijoz izohi:</b> <i>{esc(message.caption)}</i>\n" if message.caption else ""

    admin_caption = (
        "🧾 <b>YANGI TO'LOV CHEKI KELDI!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Mijoz:</b> {esc(cust_name)}\n"
        f"📱 <b>Tel:</b> <code>{esc(cust_phone)}</code>\n"
        f"🎖️ <b>Harbiy guruh:</b> {esc(category)}\n"
        f"💰 <b>Umumiy qarzi:</b> <b>{format_sum(total_debt)}</b>\n"
        f"🕒 <b>Vaqt:</b> {tashkent_now}\n"
        f"{user_caption_text}"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "To'lov chekini tekshirib, tasdiqlang yoki bekor qiling:"
    )

    approve_callback = f"chk_appr:{cust_id}:{int(total_debt)}"
    reject_callback = f"chk_rej:{cust_id}"

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash va qarzdan o'chirish",
                    callback_data=approve_callback
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=reject_callback
                )
            ]
        ]
    )

    # Adminni topish
    admin = await get_admin_by_shop_id(shop_id)
    admin_tg_id = (admin.get("telegram_id") if admin else None) or ADMIN_MAIN_ID

    try:
        if is_photo:
            await bot.send_photo(
                chat_id=admin_tg_id,
                photo=file_id,
                caption=admin_caption,
                parse_mode="HTML",
                reply_markup=admin_keyboard
            )
        else:
            await bot.send_document(
                chat_id=admin_tg_id,
                document=file_id,
                caption=admin_caption,
                parse_mode="HTML",
                reply_markup=admin_keyboard
            )
        logger.info(f"To'lov cheki admin {admin_tg_id} ga yuborildi (Mijoz: {cust_name})")
    except Exception as e:
        logger.error(f"Adminga chek yuborishda xatolik: {e}")


@router.callback_query(F.data.startswith("chk_appr:"))
async def on_admin_approve_receipt(callback: CallbackQuery, bot: Bot):
    """Admin 'Tasdiqlash va qarzdan o'chirish' tugmasini bosganda"""
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ma'lumotlar noto'g'ri", show_alert=True)
        return

    cust_id = int(parts[1])
    cust = await get_customer_by_id(cust_id)
    if not cust:
        await callback.answer("Mijoz topilmadi!", show_alert=True)
        return

    current_debt = float(cust.get("total_debt") or 0.0)
    shop_id = cust.get("shop_id") or "64EB6AB2"

    if current_debt <= 0:
        await callback.answer("Ushbu mijozda qarzdorlik qolmagan (0 so'm)", show_alert=True)
        try:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption or ''}\n\n⚠️ <i>Ushbu mijozning qarzi allaqachon to'langan!</i>",
                parse_mode="HTML",
                reply_markup=None
            )
        except Exception:
            pass
        return

    try:
        # Qarzni to'liq o'chirish
        res = await record_customer_payment(
            customer_id=cust_id,
            shop_id=shop_id,
            pay_amount=current_debt,
            admin_id=callback.from_user.id,
            note="Telegram orqali to'lov cheki tasdiqlandi",
            admin_name="G'iyos"
        )
        invalidate_api_cache()
    except Exception as e:
        logger.error(f"Qarzni o'chirishda xatolik: {e}")
        await callback.answer(f"Xatolik: {e}", show_alert=True)
        return

    paid_str = format_sum(res.get("paid_amount", current_debt))
    rem_str = format_sum(res.get("remaining_debt", 0.0))
    tashkent_now = datetime.now(ZoneInfo("Asia/Tashkent")).strftime("%d.%m.%Y %H:%M")

    new_caption = (
        "🧾 <b>TO'LOV CHEKI TASDIQLANDI!</b> ✅\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Mijoz:</b> {esc(cust.get('full_name', 'Mijoz'))}\n"
        f"📱 <b>Tel:</b> <code>{esc(cust.get('phone', ''))}</code>\n"
        f"🎖️ <b>Harbiy guruh:</b> {esc(cust.get('category') or 'Belgilanmagan')}\n"
        f"💰 <b>O'chirilgan qarz:</b> {paid_str}\n"
        f"💳 <b>Qolgan qarz:</b> {rem_str}\n"
        f"🕒 <b>Tasdiqlangan vaqt:</b> {tashkent_now}\n"
        f"👨‍💼 <b>Admin:</b> G'iyos\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <i>Qarzdorlik bazadan muvaffaqiyatli o'chirildi!</i>"
    )

    try:
        await callback.message.edit_caption(caption=new_caption, parse_mode="HTML", reply_markup=None)
    except Exception:
        pass

    await callback.answer("✅ To'lov tasdiqlandi va qarz o'chirildi!", show_alert=True)

    # Mijozga quvonchli xabar yuborish
    cust_tg_id = cust.get("telegram_id")
    if cust_tg_id:
        try:
            shop_title = cust.get("shop_name") or "Kech Harbiy Do'kon"
            await bot.send_message(
                chat_id=cust_tg_id,
                text=(
                    f"✅ <b>Assalomu alaykum, {esc(cust.get('full_name', 'Mijoz'))}!</b> 🎉\n\n"
                    f"Siz yuborgan to'lov cheki <b>{esc(shop_title)}</b> ma'muriyati tomonidan tekshirilib, tasdiqlandi!\n\n"
                    f"💰 <b>O'chirilgan qarz:</b> {paid_str}\n"
                    f"💳 <b>Hozirgi qarzingiz:</b> {rem_str}\n\n"
                    f"Do'konimizdan xarid qilganingiz va o'z vaqtida to'laganingiz uchun tashakkur! 😊🤝"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Mijozga tasdiq xabarini yetkazishda xatolik: {e}")


@router.callback_query(F.data.startswith("chk_rej:"))
async def on_admin_reject_receipt(callback: CallbackQuery, bot: Bot):
    """Admin 'Bekor qilish' tugmasini bosganda"""
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ma'lumotlar noto'g'ri", show_alert=True)
        return

    cust_id = int(parts[1])
    cust = await get_customer_by_id(cust_id)
    tashkent_now = datetime.now(ZoneInfo("Asia/Tashkent")).strftime("%d.%m.%Y %H:%M")

    new_caption = (
        "🧾 <b>TO'LOV CHEKI BEKOR QILINDI!</b> ❌\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Mijoz:</b> {esc(cust.get('full_name', 'Mijoz') if cust else 'Mijoz')}\n"
        f"📱 <b>Tel:</b> <code>{esc(cust.get('phone', '') if cust else '')}</code>\n"
        f"🕒 <b>Rad etilgan vaqt:</b> {tashkent_now}\n"
        f"👨‍💼 <b>Admin:</b> G'iyos\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "❌ <i>Chek rad etildi, mijoz qarzi o'zgarishsiz qoldirildi.</i>"
    )

    try:
        await callback.message.edit_caption(caption=new_caption, parse_mode="HTML", reply_markup=None)
    except Exception:
        pass

    await callback.answer("❌ Chek bekor qilindi!")

    # Mijozga xushmuomalalik bilan xabar berish
    if cust and cust.get("telegram_id"):
        try:
            shop_title = cust.get("shop_name") or "Kech Harbiy Do'kon"
            await bot.send_message(
                chat_id=cust["telegram_id"],
                text=(
                    f"⚠️ <b>Assalomu alaykum, {esc(cust.get('full_name', 'Mijoz'))}!</b>\n\n"
                    f"Siz yuborgan to'lov cheki <b>{esc(shop_title)}</b> ma'muriyati tomonidan qabul qilinmadi yoki rad etildi.\n\n"
                    f"Iltimos, chek rekvizitlarini qayta tekshirib ko'ring yoki do'kon ma'muriyati bilan bog'laning."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Mijozga rad etish xabarini yetkazishda xatolik: {e}")
