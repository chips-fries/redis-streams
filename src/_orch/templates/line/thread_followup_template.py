# src/orch/templates/line/thread_followup_template.py
# -*- coding: utf-8 -*-

"""
Template for Line follow-up reminder messages. Sends a simplified plain text message
based on the follow-up policy (thread_message_template).
"""

import logging
from typing import List, Optional

try:
    from linebot.v3.messaging import TextMessage
except ImportError:

    class TextMessage:
        pass  # Fallback dummy for import errors


logger = logging.getLogger(__name__)


class LineThreadFollowupTemplate:
    def __init__(
        self,
        reminder_id: str,
        recipient: str,
        reminder_text: str,
        thread_template: Optional[str] = None,
        mentions: Optional[List[str]] = None,
        sub_text: Optional[str] = None,
        interaction_mode: Optional[str] = None,
        **kwargs,
    ):
        self.reminder_id = reminder_id
        self.recipient = recipient
        self.reminder_text = reminder_text
        self.thread_template = thread_template or "{{reminder_text}}"
        self.mentions = mentions or []
        self.sub_text = sub_text or ""
        self.interaction_mode = interaction_mode or "default"

        if not self.recipient:
            raise ValueError("LineThreadFollowupTemplate: recipient is required")

    def build_payload(self) -> List[TextMessage]:
        if TextMessage.__module__ == __name__:
            logger.error("Line SDK not loaded, cannot build payload.")
            return []

        try:
            # Generate mention placeholders (Line does not support true mentions)
            mention_str = (
                " ".join(f"@User{i+1}" for i in range(len(self.mentions)))
                if self.mentions
                else ""
            )

            # Apply template replacements
            text = self.thread_template
            text = text.replace("{{reminder_text}}", self.reminder_text)
            text = text.replace("{{mentions}}", mention_str)

            logger.debug(
                f"[LineFollowUp:{self.reminder_id[:8]}] Final follow-up text: {text}"
            )

            return [TextMessage(text=text[:5000])]  # LINE text max length is 5000 chars

        except Exception as e:
            logger.exception(
                f"LineThreadFollowupTemplate: Failed to build follow-up message: {e}"
            )
            raise
