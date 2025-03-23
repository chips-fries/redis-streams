import requests
import yaml
import hmac
import hashlib
import time
from utils.config import API_TOKEN


def run():
    with open("test/manual/config.yaml") as f:
        env_yaml = yaml.safe_load(f)

    env = env_yaml["default_env"]

    api_base_url = env_yaml["environments"][env]["api_base_url"]

    endpoint = f"{api_base_url}/publish/slack/{env}"

    payload = {
        "template": "text",
        "main_text": "📢 這是測試發送 from API",
        "sub_text": "這筆通知會放進 Redis Stream 等待 consumer 處理",
        "recipient": "<@U08J619BW3B>",
        "status": "info",
    }

    timestamp = str(int(time.time()))
    signature = hmac.new(
        API_TOKEN.encode(), timestamp.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "token": API_TOKEN,
        "x-timestamp": timestamp,
        "x-signature": signature,
        "Content-Type": "application/json",
    }

    response = requests.post(endpoint, json=payload, headers=headers)

    if response.ok:
        print(f"✅ [{env}] 基本訊息發送成功！")
    else:
        print(f"❌ [{env}] 基本訊息發送失敗: {response.status_code} {response.text}")


if __name__ == "__main__":
    run()
