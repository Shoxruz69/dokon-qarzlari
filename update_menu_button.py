import urllib.request
import json

token = "9106358155:AAFkdpl8Yi3wsspZa3CdSpCeYJURlkpodqc"
url = f"https://api.telegram.org/bot{token}/setChatMenuButton"
data = {
    "menu_button": {
        "type": "web_app",
        "text": "Do'kon Paneli",
        "web_app": {
            "url": "https://dokon-qarzlari-wf96.onrender.com/?v=2.1"
        }
    }
}
req = urllib.request.Request(
    url,
    data=json.dumps(data).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
res = urllib.request.urlopen(req)
print(json.loads(res.read().decode("utf-8")))
