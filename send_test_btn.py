import urllib.request
import json

token = "9106358155:AAFkdpl8Yi3wsspZa3CdSpCeYJURlkpodqc"
for chat_id in [7370403444, 6876312568]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🏪 <b>Kech Harbiy Do'kon</b> boshqaruv paneli (kod: <code>64EB6AB2</code>) tayyor!\n\nPastdagi tugmani bosing:",
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "🏪 Do'kon Paneli (Mini App)",
                        "web_app": {"url": "https://dokon-qarzlari-wf96.onrender.com/?shop_id=64EB6AB2&v=2.1"}
                    }
                ]
            ]
        }
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        res = urllib.request.urlopen(req)
        print(f"Sent to {chat_id}: SUCCESS")
    except Exception as e:
        print(f"Failed to send to {chat_id}: {e}")
