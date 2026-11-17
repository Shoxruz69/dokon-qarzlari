import urllib.request
import json

token = "9106358155:AAFkdpl8Yi3wsspZa3CdSpCeYJURlkpodqc"

# 1. Barcha oddiy foydalanuvchilar (mijozlar) uchun pastki menyu:
default_data = {
    "menu_button": {
        "type": "web_app",
        "text": "Mening qarzlarim",
        "web_app": {
            "url": "https://dokon-qarzlari-wf96.onrender.com/?role=customer&shop_id=64EB6AB2&v=2.5"
        }
    }
}
req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/setChatMenuButton",
    data=json.dumps(default_data).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
res = urllib.request.urlopen(req)
print("Default (Mijozlar) Menu Button:", json.loads(res.read().decode("utf-8")))

# 2. Faqat Admin (G'iyos - 7370403444) uchun maxsus Do'kon Paneli menyusi:
admin_data = {
    "chat_id": 7370403444,
    "menu_button": {
        "type": "web_app",
        "text": "Do'kon Paneli",
        "web_app": {
            "url": "https://dokon-qarzlari-wf96.onrender.com/?role=admin&shop_id=64EB6AB2&v=2.1"
        }
    }
}
req2 = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/setChatMenuButton",
    data=json.dumps(admin_data).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
res2 = urllib.request.urlopen(req2)
print("Admin (G'iyos) Menu Button:", json.loads(res2.read().decode("utf-8")))
