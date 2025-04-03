# src/orch/templates/slack/thread_followup_template.py

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class SlackThreadFollowupTemplate:
    def __init__(
        self,
        reminder_id: str,
        recipient: str,
        reminder_text: str,
        thread_template: Optional[str] = None,
        mentions: Optional[List[str]] = None,
        sub_text: Optional[str] = None,
        interaction_mode: Optional[str] = None,
        thread_ts: Optional[str] = None,
        **kwargs,
    ):
        self.reminder_id = reminder_id
        self.recipient = recipient
        self.reminder_text = reminder_text or "(Follow-up Reminder)"
        self.thread_template = thread_template or "{{reminder_text}}"
        self.mentions = mentions or []
        self.sub_text = sub_text or ""
        self.interaction_mode = interaction_mode
        self.thread_ts = thread_ts
        self.extra = kwargs

    def build_payload(self) -> Dict[str, Any]:
        mention_str = " ".join(f"<@{m}>" for m in self.mentions)

        text = self.thread_template.replace("{{reminder_text}}", self.reminder_text)

        if "{{mentions}}" in self.thread_template:
            text = text.replace("{{mentions}}", mention_str)

        payload = {
            "type": "reminder_followup",
            "text": text[:3000],  # Slack max text length safety
        }

        if self.sub_text:
            payload["sub_text"] = self.sub_text

        logger.info(f"Payload = {payload}")

        if hasattr(self, "thread_ts") and self.thread_ts:
            payload["thread_ts"] = self.thread_ts

        return payload
