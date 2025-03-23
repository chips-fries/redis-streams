import time
import hmac
import hashlib
import requests
from utils.config import API_TOKEN

# BASE_URL = "https://redis-streams-1.onrender.com"
BASE_URL = "http://0.0.0.0:10000"
TOKEN = API_TOKEN
ENV = "test"

timestamp = str(int(time.time()))
signature = hmac.new(TOKEN.encode(), timestamp.encode(), hashlib.sha256).hexdigest()

headers = {
    "token": TOKEN,
    "x-timestamp": timestamp,
    "x-signature": signature,
}

print("timestamp:", timestamp)
print("signature:", signature)

response = requests.get(f"{BASE_URL}/status/{ENV}", headers=headers)
print(response.status_code)
print(response.json())
