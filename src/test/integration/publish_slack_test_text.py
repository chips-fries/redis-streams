import time
import hmac
import hashlib
import requests
import json
from utils.config import API_TOKEN, NGROK_URL

# BASE_URL = "http://0.0.0.0:10000"  # 或改為 Render 上線網址
BASE_URL = NGROK_URL
ENV = "test"
TOKEN = API_TOKEN

# 建立 HMAC 簽章
timestamp = str(int(time.time()))
signature = hmac.new(TOKEN.encode(), timestamp.encode(), hashlib.sha256).hexdigest()

headers = {
    "token": TOKEN,
    "x-timestamp": timestamp,
    "x-signature": signature,
    "Content-Type": "application/json",
}

# 建立 payload
payload = {
    "template": "action",
    "main_text": "📢 這是測試發送 from API",
    "sub_text": "這筆通知會放進 Redis Stream 等待 consumer 處理",
    "recipient": "@bacon",
    "status": "info",
}

url = f"{BASE_URL}/publish/slack/{ENV}"
response = requests.post(url, headers=headers, data=json.dumps(payload))

print("Status Code:", response.status_code)
print("Response:", response.json())
