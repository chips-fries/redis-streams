import requests
import yaml
import hmac
import hashlib
import time
from utils.config import API_TOKEN


def send_action_message(env: str, endpoint: str, index: int):
    payload = {
        "template": "action",
        "main_text": f"⏳ 測試提醒功能 #{index}（勿點擊按鈕）",
        "sub_text": "若 10 秒內未點擊按鈕，將收到提醒訊息",
        "recipient": "<@U08J619BW3B>",
        "status": "warning",
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
        print(f"✅ [{env}] 已送出提醒訊息 #{index}，請勿點擊按鈕，等待 Slack thread 出現提醒訊息。")
    else:
        print(f"❌ [{env}] 訊息 #{index} 發送失敗: {response.status_code} {response.text}")


def run():
    with open("test/manual/config.yaml") as f:
        env_yaml = yaml.safe_load(f)

    env = env_yaml["default_env"]
    api_base_url = env_yaml["environments"][env]["api_base_url"]
    endpoint = f"{api_base_url}/publish/slack/{env}"

    count = 3  # 🧪 要送幾筆訊息
    for i in range(1, count + 1):
        send_action_message(env, endpoint, i)
        time.sleep(5)  # ✅ 避免太快發送導致 rate-limit 或亂序


if __name__ == "__main__":
    run()
