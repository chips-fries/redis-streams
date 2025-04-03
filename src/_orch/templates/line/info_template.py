# src/orch/templates/line/info_template.py
# -*- coding: utf-8 -*-

"""Template for basic Line informational messages."""

import logging
from typing import Dict, Any, List, Optional, Union

# --- SDK Imports ---
try:
    from linebot.v3.messaging import (
        Message as LineMessage,
        TextMessage as LineTextMessage,
    )
except ImportError:
    logging.getLogger(__name__).warning(
        "line-bot-sdk not found. LineInfoTemplate disabled."
    )

    class LineMessage:
        pass

    class LineTextMessage(LineMessage):
        pass


logger = logging.getLogger(__name__)  # orch.templates.line.info_template


class LineInfoTemplate:
    """Builds payloads for simple Line info messages."""

    def __init__(
        self,
        main_text: str,
        recipient: str,  # Needed for sending context
        sub_text: Optional[str] = None,
        **kwargs,
    ):
        self.main_text = main_text
        self.recipient = recipient
        self.sub_text = sub_text
        self._extra_data = kwargs
        if not self.main_text:
            logger.warning("LineInfoTemplate init with empty main_text.")
        if not self.recipient:
            raise ValueError("Recipient required for LineInfoTemplate.")

    def build_payload(self) -> Optional[List[LineTextMessage]]:
        if LineTextMessage.__module__ == __name__:
            logger.error("Line SDK not loaded, cannot build payload.")
            return None
        try:
            full_text = (self.main_text or "").strip()
            if self.sub_text:
                full_text += f"\n{self.sub_text.strip()}"

            # 防呆：text 不可為空
            if not full_text.strip():
                raise ValueError("LineInfoTemplate generated empty message text.")

            logger.info(
                f"LineInfoTemplate full_text for Line message: {repr(full_text)}"
            )

            line_message = LineTextMessage(text=full_text[:5000])  # LINE 最長 5000 字
            return [line_message]  # ✅ 直接回傳 SDK 實例，不要轉 dict！

        except Exception as e:
            logger.exception(f"Error building Line Info payload: {e}")
            raise ValueError(f"Failed to build Line Info payload: {e}") from e
