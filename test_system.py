import asyncio
import os
import sys
from database.db import init_db, DB_PATH
from database.queries import (
    create_admin,
    get_admin_by_telegram_id,
    add_customer,
    get_customers_list,
    get_customer_detail,
    mark_debt_paid,
    get_admin_stats,
    update_overdue_statuses,
    get_customer_by_phone
)
from utils.validators import validate_phone, validate_amount, validate_date, validate_full_name
from api.routes import create_web_app
from aiohttp.test_utils import TestClient, TestServer

async def run_tests():
    print("=" * 60)
    print("🧪 DOKON HISOBI — TIZIMNI TEKSHIRISH (UNIT & INTEGRATION TESTS)")
    print("=" * 60)

    # 1. Validators tekshiruvi
    print("\n1. Validatsiya funksiyalarini tekshirish...")
    # Telefon
    ok, phone = validate_phone("+998 90 123 45 67")
    assert ok and phone == "+998901234567", f"Phone val xato: {phone}"
    ok, phone88 = validate_phone("+998 88 732 55 15")
    assert ok and phone88 == "+998887325515", f"Phone 88 xato: {phone88}"
    ok, phone88_loc = validate_phone("887325515")
    assert ok and phone88_loc == "+998887325515", f"Phone 88 local xato: {phone88_loc}"
    ok, phone_ru = validate_phone("+7 916 123 45 67")
    assert ok and phone_ru == "+79161234567", f"Phone RU xato: {phone_ru}"
    ok, phone_kz = validate_phone("+7 701 123 45 67")
    assert ok and phone_kz == "+77011234567", f"Phone KZ xato: {phone_kz}"
    ok, phone_kg = validate_phone("+996 555 123 456")
    assert ok and phone_kg == "+996555123456", f"Phone KG xato: {phone_kg}"
    ok, phone_any = validate_phone("+1 202 555 0123")
    assert ok and phone_any == "+12025550123", f"Phone Any xato: {phone_any}"
    ok, err = validate_phone("12345")
    assert not ok, "Noto'g'ri telefon qabul qilindi!"

    # Summa
    ok, amt = validate_amount("150 000")
    assert ok and amt == 150000.0, f"Amount val xato: {amt}"
    ok, err = validate_amount("-50")
    assert not ok, "Manfiy summa qabul qilindi!"

    # Sana
    ok, dt = validate_date("2026-11-25")
    assert ok and dt == "2026-11-25", f"Date val xato: {dt}"

    # Ism
    ok, nm = validate_full_name("Aliyev Bobur")
    assert ok and nm == "Aliyev Bobur", f"Name val xato: {nm}"
    print("✅ Barcha validatorlar to'g'ri ishladi!")

    # 2. Ma'lumotlar bazasi initsializatsiyasi
    print("\n2. Ma'lumotlar bazasi va jadvallarni tekshirish...")
    await init_db()
    print("✅ Ma'lumotlar bazasi jadvallari yaratildi!")

    # 3. Admin yaratish
    print("\n3. Admin yaratish...")
    test_tid = 7370403444
    admin_res = await create_admin(
        telegram_id=test_tid,
        full_name="G'iyos",
        shop_name="Kech Harbiy Do'koni",
        username="giyos_test",
        phone="+998901112233"
    )
    shop_id = admin_res["shop_id"]
    print(f"✅ Admin yaratildi: {admin_res['shop_name']}, Shop ID: {shop_id}")

    admin = await get_admin_by_telegram_id(test_tid)
    assert admin is not None and admin["shop_id"] == shop_id

    # 4. Mijoz va qarz qo'shish
    print("\n4. Mijoz va qarz qo'shish...")
    add_res = await add_customer(
        shop_id=shop_id,
        full_name="Karimov Jamshid",
        phone="+998909876543",
        amount=250000.0,
        description="Un 50kg, Yog' 5L",
        due_date="2026-11-20",
        notes="Qo'shni ko'chada yashaydi"
    )
    cust_id = add_res["customer_id"]
    print(f"✅ Mijoz yaratildi: ID = {cust_id}, is_new = {add_res['is_new']}")

    # 5. Mijozlar ro'yxati va qidiruv
    print("\n5. Mijozlar ro'yxati va qidiruv...")
    customers = await get_customers_list(shop_id)
    assert len(customers) >= 1, "Mijozlar ro'yxati bo'sh!"
    found = await get_customers_list(shop_id, search="Jamshid")
    assert len(found) >= 1, "Qidiruv ishlamadi!"
    print(f"✅ Ro'yxatdan {len(customers)} ta mijoz topildi!")

    # 6. Mijoz kartochkasi
    print("\n6. Mijoz kartochkasi va qarzlari...")
    detail = await get_customer_detail(cust_id, shop_id)
    assert detail is not None
    assert len(detail["debts"]) >= 1
    debt_id = detail["debts"][0]["id"]
    assert detail["debts"][0]["amount"] == 250000.0
    print(f"✅ Mijoz qarzi tasdiqlandi: {debt_id} - {detail['debts'][0]['description']}")

    # 7. Statistika tekshirish
    print("\n7. Statistika tekshirish...")
    stats = await get_admin_stats(shop_id)
    assert stats["total_customers"] >= 1
    assert stats["total_debt_sum"] >= 250000.0
    print(f"✅ Statistika: Jami qarz = {stats['total_debt_sum']}, Mijozlar = {stats['total_customers']}")

    # 8. Qarzni to'langan deb belgilash
    print("\n8. Qarzni to'lash...")
    paid_ok = await mark_debt_paid(debt_id, shop_id, 999888777, "Kassaga naqd berdi")
    assert paid_ok, "Qarz to'lanmadi!"
    stats_after = await get_admin_stats(shop_id)
    assert stats_after["total_debt_sum"] <= stats["total_debt_sum"] - 250000.0, "To'langandan keyin umumiy qarz kamaymadi!"
    assert stats_after["month_paid_sum"] >= 250000.0, "Oxirgi 30 kunda to'langan summa hisoblanmadi!"
    print("✅ Qarz to'landi va statistika yangilandi!")

    # 9. Web App & REST API Test
    print("\n9. REST API va Mini App static fayllarini tekshirish...")
    app = create_web_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    # GET /
    res_index = await client.get("/")
    assert res_index.status == 200, f"Mini App index.html yuklanmadi: {res_index.status}"
    index_text = await res_index.text()
    assert "Dokon Hisobi" in index_text, "index.html ichida Dokon Hisobi topilmadi!"
    print("✅ Mini App index.html muvaffaqiyatli uzatildi!")

    # GET /api/stats/{shop_id}
    res_stats = await client.get(f"/api/stats/{shop_id}")
    assert res_stats.status == 200
    stats_json = await res_stats.json()
    assert stats_json["shop_id"] == shop_id
    print(f"✅ REST API: /api/stats/{shop_id} muvaffaqiyatli javob berdi!")

    # GET /api/me (Ultra-tezkor All-In-One bootstrap)
    res_me = await client.get(f"/api/me?user_id={test_tid}")
    assert res_me.status == 200
    me_json = await res_me.json()
    assert me_json["role"] == "admin"
    assert me_json["stats"] is not None
    assert "daily" in me_json["stats"]
    assert isinstance(me_json["customers"], list)
    print("✅ REST API: /api/me all-in-one bootstrap muvaffaqiyatli javob berdi!")

    # 6876312568 foydalanuvchi faqat mijoz bo'lishini tekshirish
    res_6876 = await client.get("/api/me?user_id=6876312568")
    assert res_6876.status == 200
    me_6876 = await res_6876.json()
    assert me_6876["role"] == "customer", f"Xato: 6876312568 admin bo'lib qoldi: {me_6876}"
    print("✅ REST API: 6876312568 faqat customer bo'lishi tasdiqlandi!")

    # To'g'ridan-to'g'ri havoladan kirilganda (/api/me paramsiz) -> ADMIN BO'LIMI!
    res_direct = await client.get("/api/me")
    assert res_direct.status == 200
    direct_json = await res_direct.json()
    assert direct_json["role"] == "admin", f"Xato: to'g'ridan-to'g'ri havolada admin chiqmadi: {direct_json}"
    assert direct_json["shop_id"] == "64EB6AB2"
    print("✅ REST API: To'g'ridan-to'g'ri havoladan (/api/me) admin huquqlari berilishi tasdiqlandi!")

    # role=customer bo'lganda -> MIJOZ BO'LIMI!
    res_cust_param = await client.get("/api/me?role=customer")
    assert res_cust_param.status == 200
    cust_param_json = await res_cust_param.json()
    assert cust_param_json["role"] == "customer"
    print("✅ REST API: role=customer bo'lganda faqat mijoz bo'limi tasdiqlandi!")

    # GET /api/customers/{shop_id}
    res_cust = await client.get(f"/api/customers/{shop_id}")
    assert res_cust.status == 200
    custs_json = await res_cust.json()
    assert len(custs_json) >= 1
    print(f"✅ REST API: /api/customers/{shop_id} muvaffaqiyatli javob berdi!")

    # POST /api/customers/add
    res_add = await client.post("/api/customers/add", json={
        "shop_id": shop_id,
        "full_name": "Rahimov Sardor",
        "phone": "+998931234567",
        "amount": 120000,
        "description": "Shakar 10kg",
        "due_date": "2026-11-28"
    })
    assert res_add.status == 200
    add_json = await res_add.json()
    new_cust_id = add_json["customer_id"]
    print("✅ REST API: /api/customers/add yangi mijoz qo'shdi!")

    # GET /api/customer/{customer_id}
    res_det = await client.get(f"/api/customer/{new_cust_id}?shop_id={shop_id}")
    assert res_det.status == 200
    det_json = await res_det.json()
    new_debt_id = det_json["debts"][0]["id"]
    print("✅ REST API: /api/customer/{id} tafsilotlarni qaytardi!")

    # POST /api/debt/{debt_id}/pay
    res_pay = await client.post(f"/api/debt/{new_debt_id}/pay", json={
        "shop_id": shop_id
    })
    assert res_pay.status == 200
    print("✅ REST API: /api/debt/{debt_id}/pay qarzni to'ladi!")

    # 10. Kategoriya (Harbiy Guruh) va Karta Sozlamalarini tekshirish
    print("\n10. Harbiy guruhlar (kategoriyalar) va karta sozlamalarini tekshirish...")
    # POST /api/categories/add
    res_cat_add = await client.post("/api/categories/add", json={
        "shop_id": shop_id,
        "name": "1-rota"
    })
    assert res_cat_add.status == 200
    cat_add_json = await res_cat_add.json()
    assert cat_add_json["ok"] is True
    print("✅ REST API: /api/categories/add harbiy guruh qo'shdi!")

    # GET /api/categories
    res_cats = await client.get(f"/api/categories?shop_id={shop_id}")
    assert res_cats.status == 200
    cats_json = await res_cats.json()
    cat_names = [c["name"] for c in (cats_json if isinstance(cats_json, list) else cats_json.get("categories", []))]
    assert "1-rota" in cat_names
    print(f"✅ REST API: /api/categories ro'yxatni qaytardi: {cat_names}")

    # Mijozni kategoriya bilan qo'shish
    res_cust_cat = await client.post("/api/customers/add", json={
        "shop_id": shop_id,
        "full_name": "Serjant Rustam",
        "phone": "+998901239988",
        "category": "1-rota",
        "amount": 80000,
        "description": "Choy va shirinliklar",
        "due_date": "2026-11-25"
    })
    assert res_cust_cat.status == 200
    cust_cat_json = await res_cust_cat.json()
    cat_cust_id = cust_cat_json["customer_id"]

    # Mijoz tafsilotida kategoriya borligini tekshirish
    res_cat_cust_det = await client.get(f"/api/customer/{cat_cust_id}?shop_id={shop_id}")
    assert res_cat_cust_det.status == 200
    cat_cust_det_json = await res_cat_cust_det.json()
    assert cat_cust_det_json["category"] == "1-rota", f"Category xato: {cat_cust_det_json.get('category')}"
    print("✅ REST API: Mijoz harbiy guruh (kategoriya) bilan saqlandi va ko'rsatildi!")

    # POST /api/settings/card (Admin karta ma'lumotlarini saqlash)
    res_card = await client.post("/api/settings/card", json={
        "shop_id": shop_id,
        "card_number": "8600123456789012",
        "card_holder": "G'iyos Rahmonov",
        "bank_name": "TBC Bank"
    })
    assert res_card.status == 200
    card_json = await res_card.json()
    assert card_json["ok"] is True
    print("✅ REST API: /api/settings/card karta sozlamalarini saqladi!")

    # GET /api/me ichida admin karta va kategoriyalar qaytishini tekshirish
    res_me_settings = await client.get(f"/api/me?user_id={test_tid}")
    assert res_me_settings.status == 200
    me_settings_json = await res_me_settings.json()
    assert me_settings_json["admin"]["card_number"] == "8600123456789012"
    assert me_settings_json["admin"]["card_holder"] == "G'iyos Rahmonov"
    assert len(me_settings_json.get("categories", [])) >= 1
    print("✅ REST API: /api/me karta va guruhlar bootstrap ma'lumotlarini qaytardi!")

    # POST /api/settings/broadcast-card (Qarzdorlarga karta yuborish)
    res_broadcast = await client.post("/api/settings/broadcast-card", json={
        "shop_id": shop_id
    })
    assert res_broadcast.status == 200
    bc_json = await res_broadcast.json()
    assert bc_json["ok"] is True
    print(f"✅ REST API: /api/settings/broadcast-card xabarnoma yubordi (sent: {bc_json.get('sent_count', 0)})!")

    await client.close()
    print("\n" + "=" * 60)
    print("🎉 BARCHA TEKSHIRUVLAR 100% MUVAFFAQIYATLI O'TDI!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_tests())

