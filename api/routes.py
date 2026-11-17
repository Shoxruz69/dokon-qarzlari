import asyncio
import json
import logging
import time
from typing import Optional, Any, Dict, List
from pathlib import Path
from aiohttp import web
from config import settings
from database.queries import (
    get_admin_by_shop_id,
    get_admin_by_telegram_id,
    get_first_active_admin,
    get_admin_stats,
    get_customers_list,
    get_customer_detail,
    get_customer_by_id,
    get_customer_by_telegram_id,
    get_customer_all_debts,
    add_customer,
    mark_debt_paid,
    record_customer_payment,
    add_debt_to_existing_customer,
    update_customer,
    delete_customer,
    resolve_admin_label,
    create_admin,
    get_shop_categories,
    add_shop_category,
    delete_shop_category,
    update_admin_card,
    get_shop_debtors_for_broadcast
)
from utils.validators import validate_phone, validate_amount, validate_date, validate_full_name
from utils.notifications import (
    notify_customer_partial_payment,
    notify_customer_debt_added,
    notify_customer_debt_paid,
    notify_customer_card_details
)

logger = logging.getLogger(__name__)

# CORS middleware
@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Shop-Id, X-Telegram-User-Id, X-Telegram-Init-Data"
    return response

# ============================================================
# SHOP RESOLVER HELPER
# ============================================================
_cached_default_shop_id: Optional[str] = "64EB6AB2"

async def resolve_shop_id(request: web.Request) -> str:
    """Har qanday manbadan do'kon kodini tezkor aniqlash (keshlangan)"""
    global _cached_default_shop_id
    # 1. URL yo'li ({shop_id})
    shop_id = request.match_info.get("shop_id", "").strip().upper()
    if shop_id:
        return "64EB6AB2" if shop_id == "F3055FC8" else shop_id
    # 2. Query parametr (?shop_id=...)
    shop_id = request.query.get("shop_id", "").strip().upper()
    if shop_id:
        return "64EB6AB2" if shop_id == "F3055FC8" else shop_id
    # 3. Header (X-Shop-Id)
    shop_id = request.headers.get("X-Shop-Id", "").strip().upper()
    if shop_id:
        return "64EB6AB2" if shop_id == "F3055FC8" else shop_id
    # 4. Keshdagi default do'kon kodi (0ms)
    if _cached_default_shop_id:
        return _cached_default_shop_id
    # 5. Asosiy admin (G'iyos) do'kon kodi
    main_admin = await get_admin_by_telegram_id(7370403444)
    if main_admin and main_admin.get("shop_id") and main_admin.get("shop_id") != "5832B1F2":
        _cached_default_shop_id = main_admin["shop_id"]
        return _cached_default_shop_id
    return "64EB6AB2"

# ============================================================
# API IN-MEMORY TEZKOR KESH (0ms javob berish uchun)
# ============================================================
_stats_memory_cache: Dict[str, Any] = {}
_customers_memory_cache: Dict[str, Any] = {}
CACHE_TTL = 30 # soniya (har qanday o'zgarishda darhol tozalanadi)

def invalidate_api_cache():
    """Qarz yoki to'lov o'zgarganda keshni bir zumda tozalash"""
    _stats_memory_cache.clear()
    _customers_memory_cache.clear()

# ============================================================
# API HANDLERS
# ============================================================

async def handle_get_stats(request: web.Request):
    """GET /api/stats yoki /api/stats/{shop_id}?date=YYYY-MM-DD"""
    shop_id = await resolve_shop_id(request)
    if not shop_id:
        return web.json_response({"detail": "Do'kon topilmadi"}, status=404)
        
    target_date = request.query.get("date") or "today"
    cache_key = f"{shop_id}:{target_date}"
    now = time.time()
    if cache_key in _stats_memory_cache:
        ts, cached_stats = _stats_memory_cache[cache_key]
        if now - ts < CACHE_TTL:
            return web.json_response(cached_stats)

    admin = await get_admin_by_shop_id(shop_id)
    if not admin:
        return web.json_response({"detail": "Do'kon topilmadi"}, status=404)
        
    stats = await get_admin_stats(shop_id, target_date=target_date if target_date != "today" else None)
    stats["shop_name"] = admin["shop_name"]
    stats["shop_id"] = admin["shop_id"]
    _stats_memory_cache[cache_key] = (now, stats)
    return web.json_response(stats)

async def handle_get_customers(request: web.Request):
    """GET /api/customers yoki /api/customers/{shop_id}"""
    shop_id = await resolve_shop_id(request)
    if not shop_id:
        return web.json_response([], status=200)

    search = request.query.get("search") or ""
    status_filter = request.query.get("status") or "all"
    cache_key = f"{shop_id}:{search}:{status_filter}"
    now = time.time()
    if cache_key in _customers_memory_cache:
        ts, cached_custs = _customers_memory_cache[cache_key]
        if now - ts < CACHE_TTL:
            return web.json_response(cached_custs)

    customers = await get_customers_list(shop_id, search=search if search else None, status_filter=status_filter)
    _customers_memory_cache[cache_key] = (now, customers)
    return web.json_response(customers)

async def handle_get_customer_detail(request: web.Request):
    """GET /api/customer/{customer_id}?shop_id=..."""
    try:
        customer_id = int(request.match_info.get("customer_id"))
    except (ValueError, TypeError):
        return web.json_response({"detail": "Noto'g'ri customer_id"}, status=400)
        
    shop_id = await resolve_shop_id(request)
    if not shop_id:
        return web.json_response({"detail": "shop_id ko'rsatilmadi"}, status=400)
        
    customer = await get_customer_detail(customer_id, shop_id)
    if not customer:
        return web.json_response({"detail": "Mijoz topilmadi"}, status=404)
        
    return web.json_response(customer)

async def handle_add_customer(request: web.Request):
    """POST /api/customers/add"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"detail": "Noto'g'ri JSON formati"}, status=400)
        
    shop_id = data.get("shop_id", "").strip().upper()
    if not shop_id:
        shop_id = await resolve_shop_id(request)
    full_name = data.get("full_name", "").strip()
    phone = data.get("phone", "").strip()
    amount = data.get("amount")
    description = data.get("description", "").strip()
    due_date = data.get("due_date", "").strip()
    notes = data.get("notes")
    category = data.get("category")

    # Validatsiyalar
    admin = await get_admin_by_shop_id(shop_id)
    if not admin:
        return web.json_response({"detail": "Do'kon topilmadi"}, status=404)

    is_name_ok, name_val = validate_full_name(full_name)
    if not is_name_ok:
        return web.json_response({"detail": name_val}, status=400)

    # Telefon raqam ixtiyoriy
    phone_val = None
    if phone and phone.strip():
        is_phone_ok, valid_phone = validate_phone(phone.strip())
        if not is_phone_ok:
            return web.json_response({"detail": valid_phone}, status=400)
        phone_val = valid_phone

    is_amt_ok, amt_val = validate_amount(amount)
    if not is_amt_ok:
        return web.json_response({"detail": amt_val}, status=400)

    is_date_ok, date_val = validate_date(due_date)
    if not is_date_ok:
        return web.json_response({"detail": date_val}, status=400)

    # Nima olingani (Mahsulot) ixtiyoriy
    if not description or len(description.strip()) == 0:
        description = "Nasiya savdo"

    admin_id_val = request.headers.get("X-Telegram-User-Id") or data.get("admin_id")
    admin_name_val = request.headers.get("X-Admin-Name") or data.get("admin_name")
    admin_id = int(admin_id_val) if admin_id_val and str(admin_id_val).isdigit() else 0

    result = await add_customer(
        shop_id=shop_id,
        full_name=name_val,
        phone=phone_val,
        amount=amt_val,
        description=description,
        due_date=date_val,
        notes=notes,
        admin_id=admin_id,
        admin_name=admin_name_val,
        category=category
    )
    invalidate_api_cache()
    return web.json_response(result)

async def handle_mark_paid(request: web.Request):
    """POST /api/debt/{debt_id}/pay"""
    try:
        debt_id = int(request.match_info.get("debt_id"))
    except (ValueError, TypeError):
        return web.json_response({"detail": "Noto'g'ri debt_id"}, status=400)
        
    try:
        data = await request.json()
    except Exception:
        data = {}
        
    shop_id = data.get("shop_id") or request.headers.get("X-Shop-Id", "").strip().upper()
    admin_id_val = request.headers.get("X-Telegram-User-Id") or data.get("admin_id")
    admin_name_val = request.headers.get("X-Admin-Name") or data.get("admin_name")
    admin_id = int(admin_id_val) if admin_id_val and str(admin_id_val).isdigit() else 0
    note = data.get("note", "Mini App orqali to'landi")
    
    if not shop_id:
        return web.json_response({"detail": "shop_id ko'rsatilmadi"}, status=400)
        
    res = await mark_debt_paid(debt_id, shop_id, admin_id, note, admin_name=admin_name_val)
    if not res:
        return web.json_response({"detail": "Qarz topilmadi yoki do'kon mos kelmadi"}, status=400)

    # Bildirishnomani fonda yuboramiz (foydalanuvchi kutib turmaydi, tez ishlaydi)
    import asyncio
    asyncio.create_task(notify_customer_debt_paid(
        customer=res["customer"],
        shop_name=res["shop_name"],
        debt_amount=res["paid_amount"],
        description=res["debt"]["description"],
        remaining_debt=res["remaining_debt"]
    ))
        
    invalidate_api_cache()
    return web.json_response({
        "success": True,
        "paid_amount": res["paid_amount"],
        "remaining_debt": res["remaining_debt"],
        "admin_name": res.get("admin_name")
    })

async def handle_customer_pay(request: web.Request):
    """POST /api/customer/{customer_id}/pay — Qarzdan ma'lum summani ayirish"""
    try:
        customer_id = int(request.match_info.get("customer_id"))
    except (ValueError, TypeError):
        return web.json_response({"detail": "Noto'g'ri customer_id"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"detail": "Noto'g'ri JSON format"}, status=400)

    shop_id = data.get("shop_id") or request.headers.get("X-Shop-Id", "").strip().upper()
    if not shop_id:
        shop_id = await resolve_shop_id(request)

    amount = data.get("amount")
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError()
    except Exception:
        return web.json_response({"detail": "To'lov summasi noto'g'ri"}, status=400)

    note = data.get("note", "Mini App orqali to'landi")
    admin_id_val = request.headers.get("X-Telegram-User-Id") or data.get("admin_id")
    admin_name_val = request.headers.get("X-Admin-Name") or data.get("admin_name")
    admin_id = int(admin_id_val) if admin_id_val and str(admin_id_val).isdigit() else 0

    try:
        result = await record_customer_payment(customer_id, shop_id, amount, admin_id, note, admin_name=admin_name_val)
    except ValueError as e:
        return web.json_response({"detail": str(e)}, status=400)

    # Bildirishnomani fonda yuborish
    import asyncio
    asyncio.create_task(notify_customer_partial_payment(
        customer=result["customer"],
        shop_name=result["shop_name"],
        paid_amount=result["paid_amount"],
        remaining_debt=result["remaining_debt"]
    ))

    invalidate_api_cache()
    return web.json_response({
        "success": True,
        "paid_amount": result["paid_amount"],
        "remaining_debt": result["remaining_debt"],
        "admin_name": result.get("admin_name")
    })

async def handle_customer_add_debt(request: web.Request):
    """POST /api/customer/{customer_id}/add-debt — Mijozga yangi qarz qo'shish"""
    try:
        customer_id = int(request.match_info.get("customer_id"))
    except (ValueError, TypeError):
        return web.json_response({"detail": "Noto'g'ri customer_id"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"detail": "Noto'g'ri JSON format"}, status=400)

    shop_id = data.get("shop_id") or request.headers.get("X-Shop-Id", "").strip().upper()
    if not shop_id:
        shop_id = await resolve_shop_id(request)

    amount = data.get("amount")
    description = (data.get("description") or "").strip()
    due_date = (data.get("due_date") or "").strip()
    notes = data.get("notes")

    is_amt_ok, amt_val = validate_amount(amount)
    if not is_amt_ok:
        return web.json_response({"detail": amt_val}, status=400)

    if not description or len(description.strip()) == 0:
        description = "Nasiya savdo"

    is_date_ok, date_val = validate_date(due_date)
    if not is_date_ok:
        return web.json_response({"detail": date_val}, status=400)

    admin_id_val = request.headers.get("X-Telegram-User-Id") or data.get("admin_id")
    admin_name_val = request.headers.get("X-Admin-Name") or data.get("admin_name")
    admin_id = int(admin_id_val) if admin_id_val and str(admin_id_val).isdigit() else 0

    try:
        result = await add_debt_to_existing_customer(customer_id, shop_id, amt_val, description, date_val, notes, admin_id=admin_id, admin_name=admin_name_val)
    except ValueError as e:
        return web.json_response({"detail": str(e)}, status=400)

    # Bildirishnomani fonda yuborish
    import asyncio
    asyncio.create_task(notify_customer_debt_added(
        customer=result["customer"],
        shop_name=result["shop_name"],
        amount=result["amount"],
        description=result["description"],
        due_date=result["due_date"],
        total_debt=result["total_debt"]
    ))

    invalidate_api_cache()
    return web.json_response({
        "success": True,
        "debt_id": result["debt_id"],
        "total_debt": result["total_debt"],
        "admin_name": result.get("created_by_admin_name")
    })

async def handle_customer_edit(request: web.Request):
    """POST /api/customer/{customer_id}/edit yoki PUT /api/customer/{customer_id}"""
    try:
        customer_id = int(request.match_info.get("customer_id"))
    except (ValueError, TypeError):
        return web.json_response({"detail": "Noto'g'ri customer_id"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"detail": "Noto'g'ri JSON formati"}, status=400)

    shop_id = await resolve_shop_id(request)
    if not shop_id:
        return web.json_response({"detail": "shop_id aniqlanmadi"}, status=400)

    full_name = data.get("full_name", "").strip()
    phone = data.get("phone", "")
    notes = data.get("notes")
    category = data.get("category")

    is_name_ok, name_val = validate_full_name(full_name)
    if not is_name_ok:
        return web.json_response({"detail": name_val}, status=400)

    phone_val = None
    if phone and str(phone).strip():
        is_phone_ok, valid_phone = validate_phone(str(phone).strip())
        if not is_phone_ok:
            return web.json_response({"detail": valid_phone}, status=400)
        phone_val = valid_phone

    try:
        updated = await update_customer(customer_id, shop_id, name_val, phone_val, notes, category)
    except ValueError as e:
        return web.json_response({"detail": str(e)}, status=400)

    if not updated:
        return web.json_response({"detail": "Mijoz topilmadi"}, status=404)

    invalidate_api_cache()
    return web.json_response({
        "success": True,
        "customer": updated
    })

async def handle_customer_delete(request: web.Request):
    """POST /api/customer/{customer_id}/delete yoki DELETE /api/customer/{customer_id}"""
    try:
        customer_id = int(request.match_info.get("customer_id"))
    except (ValueError, TypeError):
        return web.json_response({"detail": "Noto'g'ri customer_id"}, status=400)

    shop_id = await resolve_shop_id(request)
    if not shop_id:
        return web.json_response({"detail": "shop_id aniqlanmadi"}, status=400)

    success = await delete_customer(customer_id, shop_id)
    if not success:
        return web.json_response({"detail": "Mijoz topilmadi yoki o'chirishda xatolik"}, status=404)

    invalidate_api_cache()
    return web.json_response({"success": True})

async def _get_admin_bootstrap_data(admin: dict, shop_id: str) -> dict:
    """Admin uchun barcha boshlang'ich ma'lumotlarni (stats + customers) bir so'rovda parallel yig'ish (0.01s javob)"""
    if admin.get("telegram_id") == 7370403444 or shop_id in ("64EB6AB2", "F3055FC8") or not shop_id:
        shop_id = "64EB6AB2"
        admin["shop_id"] = "64EB6AB2"
        admin["shop_name"] = "Kech Harbiy Do'kon"

    now = time.time()
    cache_stats_key = f"{shop_id}:today"
    cache_custs_key = f"{shop_id}::all"
    
    stats_data = None
    if cache_stats_key in _stats_memory_cache:
        ts, s = _stats_memory_cache[cache_stats_key]
        if now - ts < CACHE_TTL:
            stats_data = s
            
    custs_data = None
    if cache_custs_key in _customers_memory_cache:
        ts, c = _customers_memory_cache[cache_custs_key]
        if now - ts < CACHE_TTL:
            custs_data = c
            
    tasks = []
    need_stats = stats_data is None
    need_custs = custs_data is None
    
    if need_stats:
        tasks.append(get_admin_stats(shop_id))
    if need_custs:
        tasks.append(get_customers_list(shop_id))
        
    if tasks:
        results = await asyncio.gather(*tasks)
        idx = 0
        if need_stats:
            stats_data = results[idx]
            stats_data["shop_name"] = admin.get("shop_name") or "Do'kon"
            stats_data["shop_id"] = shop_id
            _stats_memory_cache[cache_stats_key] = (now, stats_data)
            idx += 1
        if need_custs:
            custs_data = results[idx]
            _customers_memory_cache[cache_custs_key] = (now, custs_data)
            
    categories_data = await get_shop_categories(shop_id)

    return {
        "role": "admin",
        "admin": admin,
        "shop_id": shop_id,
        "stats": stats_data,
        "customers": custs_data,
        "categories": categories_data
    }

async def handle_get_me(request: web.Request):
    """Foydalanuvchi roli va ma'lumotlarini aniqlash (Admin yoki Mijoz)"""
    role_param = request.query.get("role", "").strip().lower()
    cust_id_param = request.query.get("customer_id")
    user_id_str = request.headers.get("X-Telegram-User-Id") or request.query.get("user_id")
    
    # 1. To'g'ridan-to'g'ri customer_id berilgan bo'lsa
    if cust_id_param and cust_id_param.isdigit():
        cust = await get_customer_by_id(int(cust_id_param))
        if cust:
            debts = await get_customer_all_debts(int(cust_id_param))
            return web.json_response({
                "role": "customer",
                "customer": cust,
                "debts": debts
            })

    # 2. Telegram user ID orqali aniqlash
    if user_id_str and user_id_str.isdigit():
        uid = int(user_id_str)
        
        # 6876312568 admin emas, har qanday holatda faqat mijoz
        if uid == 6876312568:
            admin = None
        else:
            # Admin tekshiruvi: Faqat settings.is_admin_id(uid) bo'lgan yagona admin (7370403444)
            admin = await get_admin_by_telegram_id(uid) if (settings.is_admin_id(uid) and uid != 6876312568) else None
            if not admin and settings.is_admin_id(uid) and uid != 6876312568:
                # Agar admin bazada hali mavjud bo'lmasa, avtomatik yaratamiz
                admin_name = resolve_admin_label(uid)
                admin = await create_admin(telegram_id=uid, full_name=admin_name, shop_name="Kech Harbiy Do'kon")

        if admin:
            bootstrap = await _get_admin_bootstrap_data(admin, admin["shop_id"])
            return web.json_response(bootstrap)

        # Admindan boshqa har qanday foydalanuvchi — FAQAT MIJOZ!
        custs = await get_customer_by_telegram_id(uid)
        if custs:
            cust = custs[0]
            debts = await get_customer_all_debts(cust["id"])
            return web.json_response({
                "role": "customer",
                "customer": cust,
                "debts": debts
            })

        # Agar telegram user_id admin bo'lmasa va mijoz ham topilmasa — FAQAT MIJOZ!
        return web.json_response({
            "role": "customer",
            "customer": None,
            "debts": []
        })

    # 3. Agar maxsus role=customer deb ko'rsatilgan bo'lsa — FAQAT MIJOZ KO'RINISHI!
    if role_param == "customer":
        return web.json_response({
            "role": "customer",
            "customer": None,
            "debts": []
        })

    # 4. To'g'ridan-to'g'ri havoladan kirilganda (masalan: https://dokon-qarzlari-wf96.onrender.com) — ADMIN BO'LIMI!
    shop_id = await resolve_shop_id(request)
    admin = await get_admin_by_shop_id(shop_id)
    if not admin:
        admin = await get_admin_by_telegram_id(7370403444)
    if not admin:
        admin = await get_first_active_admin()

    if admin:
        admin["full_name"] = resolve_admin_label(admin.get("telegram_id"), admin.get("full_name"))
        bootstrap = await _get_admin_bootstrap_data(admin, admin.get("shop_id", "64EB6AB2"))
        return web.json_response(bootstrap)

    return web.json_response({
        "role": "admin",
        "shop_id": "64EB6AB2",
        "admin": {
            "full_name": "G'iyos",
            "shop_name": "Kech Harbiy Do'kon",
            "shop_id": "64EB6AB2"
        },
        "stats": {
            "shop_id": "64EB6AB2",
            "total_debt": 0,
            "total_customers": 0,
            "overdue_count": 0,
            "paid_today": 0,
            "daily": {}
        },
        "customers": []
    })

async def handle_index(request: web.Request):
    """Mini App index.html faylini ko'rsatish (keshlanmaslik kafolati bilan)"""
    index_file = Path("mini_app/index.html").absolute()
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        return web.Response(
            text=content,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return web.Response(text="Mini App topilmadi", status=404)

async def handle_favicon(request: web.Request):
    """Favicon so'rovini qondirish"""
    return web.Response(text="", content_type="image/x-icon")

async def handle_health(request: web.Request):
    """GET /health va /api/health - Render 24/7 Keep-Alive va Healthcheck"""
    return web.json_response({
        "status": "ok",
        "service": "dokon-qarzlari",
        "shop_id": "64EB6AB2",
        "uptime": time.time()
    })

# ============================================================
# KATEGORIYALAR (HARBIY GURUHLAR) VA KARTA SOZLAMALARI
# ============================================================

async def handle_get_categories(request: web.Request):
    """GET /api/categories yoki /api/categories/{shop_id}"""
    shop_id = await resolve_shop_id(request)
    cats = await get_shop_categories(shop_id)
    return web.json_response(cats)

async def handle_add_category(request: web.Request):
    """POST /api/categories/add"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"detail": "Noto'g'ri JSON formati"}, status=400)
    shop_id = data.get("shop_id") or await resolve_shop_id(request)
    name = (data.get("name") or "").strip()
    if not name:
        return web.json_response({"detail": "Guruh / Kategoriya nomi kiritilmadi"}, status=400)
    cat = await add_shop_category(shop_id, name)
    invalidate_api_cache()
    cats = await get_shop_categories(shop_id)
    return web.json_response({"ok": True, "success": True, "category": cat, "categories": cats})

async def handle_delete_category(request: web.Request):
    """POST /api/categories/{id}/delete yoki DELETE /api/categories/{id}"""
    try:
        cat_id = int(request.match_info.get("id"))
    except Exception:
        return web.json_response({"detail": "Noto'g'ri kategoriya id"}, status=400)
    shop_id = await resolve_shop_id(request)
    ok = await delete_shop_category(shop_id, cat_id)
    invalidate_api_cache()
    cats = await get_shop_categories(shop_id)
    return web.json_response({"ok": ok, "success": ok, "categories": cats})

async def handle_save_card_settings(request: web.Request):
    """POST /api/settings/card - Karta ma'lumotlarini saqlash"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"detail": "Noto'g'ri JSON formati"}, status=400)
    shop_id = data.get("shop_id") or await resolve_shop_id(request)
    card_num = (data.get("card_number") or "").strip()
    card_holder = (data.get("card_holder") or "").strip()
    bank_name = (data.get("bank_name") or "").strip()

    digits_only = "".join(filter(str.isdigit, card_num))
    if len(digits_only) < 16:
        return web.json_response({"detail": "Karta raqami kamida 16 ta raqamdan iborat bo'lishi kerak"}, status=400)
    if not card_holder:
        return web.json_response({"detail": "Karta egasining ism-familiyasi kiritilishi shart"}, status=400)

    await update_admin_card(shop_id, card_num, card_holder, bank_name)
    invalidate_api_cache()
    admin = await get_admin_by_shop_id(shop_id)
    return web.json_response({
        "ok": True,
        "success": True,
        "admin": admin,
        "message": "Karta ma'lumotlari muvaffaqiyatli saqlandi!"
    })

async def handle_broadcast_card(request: web.Request):
    """POST /api/settings/broadcast-card - Barcha qarzdorlarga karta raqamini yuborish"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    shop_id = data.get("shop_id") or await resolve_shop_id(request)
    admin = await get_admin_by_shop_id(shop_id)
    if not admin:
        return web.json_response({"detail": "Do'kon topilmadi"}, status=404)

    card_num = (data.get("card_number") or admin.get("card_number") or "").strip()
    card_holder = (data.get("card_holder") or admin.get("card_holder") or "").strip()
    bank_name = (data.get("bank_name") or admin.get("bank_name") or "").strip()
    cat_filter = (data.get("category") or "").strip() or None

    cust_id = data.get("customer_id")
    cat_filter = (data.get("category") or "").strip() or None
    if cat_filter and cat_filter.lower() == "all":
        cat_filter = None

    digits_only = "".join(filter(str.isdigit, card_num))
    if len(digits_only) < 16:
        return web.json_response({"detail": "Avval to'g'ri karta raqamini kiriting va saqlang!"}, status=400)
    if not card_holder:
        card_holder = admin.get("full_name") or "Do'kon egasi"

    # Agar so'rovda yangi kelgan bo'lsa, bazaga ham saqlab qo'yamiz
    await update_admin_card(shop_id, card_num, card_holder, bank_name)

    debtors = await get_shop_debtors_for_broadcast(shop_id, category=cat_filter, customer_id=cust_id)
    sent_count = 0
    no_tg_count = 0

    shop_title = admin.get("shop_name", "Kech Harbiy Do'kon")
    for debtor in debtors:
        if debtor.get("telegram_id"):
            try:
                ok = await notify_customer_card_details(
                    debtor,
                    shop_name=shop_title,
                    card_number=card_num,
                    card_holder=card_holder,
                    bank_name=bank_name,
                    shop_id=shop_id
                )
                if ok:
                    sent_count += 1
            except Exception as e:
                logger.warning(f"Karta yuborishda xatolik ({debtor.get('id')}): {e}")
        else:
            no_tg_count += 1

    if cust_id and debtors:
        target_name = debtors[0].get("full_name", "Mijoz")
        if sent_count > 0:
            custom_msg = f"✅ {target_name} ga karta ma'lumotlari Telegram orqali yuborildi!"
        else:
            custom_msg = f"⚠️ {target_name} hali botga /start bosmagan. Karta ma'lumotlari yuborilmadi."
    elif cat_filter:
        custom_msg = f"✅ '{cat_filter}' guruhidagi {sent_count} ta qarzdor mijozga karta ma'lumotlari yuborildi!"
    else:
        custom_msg = f"✅ {sent_count} ta qarzdor mijozga karta ma'lumotlari Telegram orqali yuborildi!"

    return web.json_response({
        "ok": True,
        "success": True,
        "sent_count": sent_count,
        "total_debtors": len(debtors),
        "no_telegram_count": no_tg_count,
        "message": custom_msg
    })

def create_web_app() -> web.Application:
    """Aiohttp veb ilovasini yaratish"""
    app = web.Application(middlewares=[cors_middleware])
    
    # API endpoints
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/api/me", handle_get_me)
    app.router.add_get("/api/auth/me", handle_get_me)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_get("/api/stats/", handle_get_stats)
    app.router.add_get("/api/stats/{shop_id}", handle_get_stats)
    app.router.add_get("/api/customers", handle_get_customers)
    app.router.add_get("/api/customers/", handle_get_customers)
    app.router.add_get("/api/customers/{shop_id}", handle_get_customers)
    app.router.add_get("/api/customer/{customer_id}", handle_get_customer_detail)
    app.router.add_post("/api/customer/{customer_id}/pay", handle_customer_pay)
    app.router.add_post("/api/customer/{customer_id}/add-debt", handle_customer_add_debt)
    app.router.add_post("/api/customer/{customer_id}/edit", handle_customer_edit)
    app.router.add_put("/api/customer/{customer_id}", handle_customer_edit)
    app.router.add_post("/api/customer/{customer_id}/delete", handle_customer_delete)
    app.router.add_delete("/api/customer/{customer_id}", handle_customer_delete)
    app.router.add_post("/api/customers/add", handle_add_customer)
    app.router.add_post("/api/debt/{debt_id}/pay", handle_mark_paid)
    
    # Kategoriya va Karta sozlamalari
    app.router.add_get("/api/categories", handle_get_categories)
    app.router.add_get("/api/categories/", handle_get_categories)
    app.router.add_get("/api/categories/{shop_id}", handle_get_categories)
    app.router.add_post("/api/categories/add", handle_add_category)
    app.router.add_post("/api/categories/{id}/delete", handle_delete_category)
    app.router.add_delete("/api/categories/{id}", handle_delete_category)
    app.router.add_post("/api/settings/card", handle_save_card_settings)
    app.router.add_post("/api/settings/broadcast-card", handle_broadcast_card)
    
    # Static files & Mini App
    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    
    mini_app_dir = Path("mini_app").absolute()
    if mini_app_dir.exists():
        css_dir = mini_app_dir / "css"
        js_dir = mini_app_dir / "js"
        if css_dir.exists():
            app.router.add_static("/css/", path=css_dir)
        if js_dir.exists():
            app.router.add_static("/js/", path=js_dir)
        app.router.add_static("/static/", path=mini_app_dir)
        
    # SPA fallback: har qanday noma'lum sahifa so'ralganda 404 bermasdan index.html yuklanadi
    app.router.add_get("/{tail:.*}", handle_index)
        
    return app

