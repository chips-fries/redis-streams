import time
from typing import Dict


class SlackTemplate:
    def __init__(
        self,
        notification_id: str,
        main_text: str,
        template: str,
        recipient: str = "",
        status: str = "info",
        sub_text: str = "",
    ):
        self.notification_id = notification_id
        self.main_text = main_text
        self.sub_text = sub_text or ""
        self.template = template  # "text" or "action"
        self.recipient = recipient
        self.status = status

    def to_blocks(self) -> list:
        """
        轉換為 Slack block message 格式
        """
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": self.main_text}}
        ]

        if self.sub_text:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": self.sub_text}}
            )

        if self.template == "action":
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": ":warning: 尚未處理"},
                            "action_id": "resolve",
                            "value": self.notification_id,
                        }
                    ],
                }
            )

        return blocks

    def to_redis_msg(self) -> dict:
        """
        儲存進 Redis Stream 的資料格式
        """
        return {
            "notification_id": self.notification_id,
            "main_text": self.main_text,
            "sub_text": self.sub_text,
            "template": self.template,
            "recipient": self.recipient,
            "status": self.status,
        }

    @classmethod
    def from_redis_msg(cls, data: Dict) -> "SlackTemplate":
        """
        從 Redis 讀出來的 dict 還原成 SlackTemplate
        """
        return cls(
            notification_id=data.get("notification_id", ""),
            main_text=data.get("main_text", ""),
            sub_text=data.get("sub_text", ""),
            template=data.get("template", "text"),
            recipient=data.get("recipient", ""),
            status=data.get("status", "info"),
        )

    @staticmethod
    def validate_payload(payload: dict) -> dict:
        """
        驗證 API 傳入的 payload，回傳整理後的欄位 dict。
        若欄位缺失或格式錯誤，會 raise HTTPException
        """
        from fastapi import HTTPException

        required_fields = ["main_text", "template"]
        for field in required_fields:
            if field not in payload or not isinstance(payload[field], str):
                raise HTTPException(
                    status_code=422,
                    detail=f"'{field}' is required and must be a string",
                )

        template_type = payload["template"]
        if template_type not in ["text", "action"]:
            raise HTTPException(
                status_code=422, detail="'template' must be either 'text' or 'action'"
            )

        if template_type == "action" and not payload.get("recipient"):
            raise HTTPException(
                status_code=422, detail="'recipient' is required for action template"
            )

        status = payload.get("status", "info")
        if status not in ["info", "success", "error"]:
            status = "info"  # fallback

        return {
            "notification_id": str(int(time.time() * 1000)),
            "main_text": payload["main_text"],
            "sub_text": payload.get("sub_text", ""),
            "template": template_type,
            "recipient": payload.get("recipient", ""),
            "status": status,
        }
