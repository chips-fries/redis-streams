# src/orch/templates/slack/info_template.py
# -*- coding: utf-8 -*-

"""Template for simple informational messages for Slack."""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)  # orch.templates.slack.info_template


class SlackInfoTemplate:
    """
    Builds payload dictionary for simple Slack info messages.
    Used by Prefect tasks.
    """

    def __init__(
        self,
        main_text: str,
        recipient: Optional[str] = None,  # Context only
        sub_text: Optional[str] = None,
        status: Optional[str] = "info",
        **kwargs,
    ):
        self.main_text = main_text
        self.sub_text = sub_text
        self.status = status.lower() if status else "info"
        self.recipient = recipient
        self._extra_data = kwargs
        if not self.main_text:
            logger.warning("SlackInfoTemplate initialized empty main_text.")

    def build_payload(self) -> Dict[str, Any]:
        """Builds the Slack Block Kit payload dictionary."""
        blocks: List[Dict[str, Any]] = []
        try:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": self.main_text or "(Info)"},
                }
            )
            if self.sub_text:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": self.sub_text}],
                    }
                )
            fallback_text = self.main_text or "(Info Message)"
            if self.sub_text:
                fallback_text += f" - {self.sub_text}"
            payload = {"text": fallback_text[:3000], "blocks": blocks}
            return payload
        except Exception as e:
            logger.exception(f"Error building Slack Info payload: {e}")
            raise ValueError(f"Failed to build Slack Info payload: {e}") from e
