import requests
from slack.slack_template import SlackTemplate
from utils.config_loader import ConfigLoader
from utils.logger import logger
from typing import Tuple, Optional


class SlackNotifier:
    def __init__(self, env: str):
        config = ConfigLoader("config/slack_config.yaml").config
        self.env = env
        self.channel = config["slack"]["channel_mapping"][env]
        self.bot_token = config["slack"]["bot-token"]

    def send_message(self, template: SlackTemplate) -> str:
        """
        發送 Slack 主訊息（blocks），支援 text / action
        :param template: SlackTemplate 實例
        :return: thread_ts，可用於 reminder
        """
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "channel": self.channel,
            "attachments": [
                {
                    "color": self._get_color(template.status),
                    "blocks": template.to_blocks(),
                }
            ],
        }

        response = requests.post(
            "https://slack.com/api/chat.postMessage", headers=headers, json=payload
        )
        res_data = response.json()

        if not res_data.get("ok"):
            logger.error(f"❌ 發送 Slack 訊息失敗: {res_data}")
            return ""

        thread_ts = res_data["ts"]
        logger.info(f"✅ Slack 訊息已發送至 `{self.channel}`，thread_ts={thread_ts}")
        return thread_ts

    def send_reminder(self, thread_ts: str, text: str) -> Tuple[bool, Optional[str]]:
        """
        發送提醒訊息到指定 thread 下，回傳 (是否成功, 錯誤原因)
        """
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }

        payload = {"channel": self.channel, "thread_ts": thread_ts, "text": text}

        response = requests.post(
            "https://slack.com/api/chat.postMessage", headers=headers, json=payload
        )

        try:
            res_data = response.json()
        except Exception:
            logger.error(f"❌ Slack 回傳非 JSON 格式: {response.text}")
            return False, "invalid_response"

        if not res_data.get("ok"):
            error = res_data.get("error", "unknown")
            logger.error(f"❌ Slack 發送失敗: {error} | thread_ts={thread_ts}")
            return False, error

        logger.info("🔁 Reminder 已發送至 thread")
        return True, None

    def _get_color(self, status: str) -> str:
        color_map = {
            "success": "#2ECC71",  # 綠
            "error": "#E74C3C",  # 紅
            "info": "#3498DB",  # 藍
        }
        return color_map.get(status, "#CCCCCC")
