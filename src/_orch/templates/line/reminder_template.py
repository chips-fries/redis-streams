# src/orch/templates/line/reminder_template.py
# -*- coding: utf-8 -*-

"""Template for Line Reminder messages, potentially using Flex Messages."""

import logging
from typing import Dict, Any, List, Optional, Union

from linebot.v3.messaging import (
    Message,  # 基類
    FlexMessage,
    FlexContainer,  # 容器基類 (雖然通常直接用 FlexBubble 或 FlexCarousel)
    FlexBubble,  # 氣泡容器 (替代 BubbleContainer)
    FlexBox,  # 排列元件 (替代 BoxComponent)
    FlexText,  # 文字元件 (替代 TextComponent)
    FlexButton,  # 按鈕元件 (替代 ButtonComponent)
    FlexSeparator,  # 分隔線元件 (替代 SeparatorComponent)
    FlexSpan,  # 文字片段 (替代 SpanComponent)
    # --- Actions ---
    PostbackAction,
    MessageAction,
    TextMessage,
    # --- 其他可能需要的 ---
    # FlexCarousel, # 如果需要輪播訊息
    # FlexImage, FlexIcon, etc.
)

logger = logging.getLogger(__name__)  # orch.templates.line.reminder_template

# --- Constants for Line Actions ---
POSTBACK_ACTION = "postback"
MESSAGE_ACTION = "message"  # Example

REMINDER_UI_CONFIG = {
    "todo_status_critical": {
        "buttons": [
            {
                "label": "待處理",
                "data_action": "mark_complete",
                "style": "primary",
                "color": "#DD4B39",
            },
            {"label": "稍後提醒", "data_action": "snooze", "style": "secondary"},
        ],
        "followup_text": "快處理一下！",
    },
    "acknowledge_only": {
        "buttons": [{"label": "知道了", "data_action": "acknowledge", "style": "primary"}],
        "followup_text": "還沒看到嗎？",
    },
}


class LineReminderTemplate:
    """
    Builds payload dictionary or list for Line Reminder messages.
    Uses Flex Messages for buttons and potential mentions.
    """

    def __init__(
        self,
        # Core data
        reminder_id: str,
        recipient: str,  # Resolved Destination ID (User ID or Group/Room ID)
        reminder_text: str,  # Already processed text
        sub_text: Optional[str] = None,
        mentions: Optional[List[str]] = None,  # List of resolved Line User IDs
        # Control parameters
        interaction_mode: str = "default",
        task_ref: Optional[str] = None,
        due_date: Optional[str] = None,
        # ... other fields ...
        **kwargs,
    ):
        self.reminder_id = reminder_id
        self.recipient = recipient
        self.reminder_text = reminder_text
        self.sub_text = sub_text
        self.mentions = mentions or []  # Ensure it's a list
        self.interaction_mode = interaction_mode.lower()
        self.task_ref = task_ref
        self.due_date = due_date
        self._extra_data = kwargs

        if not all([self.reminder_id, self.recipient, self.reminder_text]):
            raise ValueError("Missing required fields for LineReminderTemplate.")

    def _build_mention_span(
        self, user_id: str, display_text: str = "User"
    ) -> Optional[Dict[str, Any]]:
        """Helper to build a mention span for Flex Message. Requires display text."""
        # NOTE: Getting display_text requires knowing the alias or querying Line API,
        # which template shouldn't do. Using a placeholder for now.
        # In a real scenario, the calling context might need to provide alias->display name mapping.
        placeholder_text = f"@{display_text}"
        return {
            "type": "span",
            "text": placeholder_text,
            "color": "#4F81BD",  # Example mention color
            "weight": "bold",
            "decoration": "underline",
            "mentionees": [
                {"userId": user_id, "startIndex": 0, "endIndex": len(placeholder_text)}
            ],
        }

    def build_initial_payload(self) -> List[Message]:
        if FlexMessage.__module__ == __name__:
            logger.error("Line SDK not loaded, cannot build payload.")
            return []

        try:
            body_contents = []

            # --- Mentions ---
            if self.mentions:
                mentionees_list = []
                mention_placeholders = []
                current_index = 0

                for i, user_id in enumerate(self.mentions):
                    placeholder = f"@User{i+1}"
                    mention_placeholders.append(placeholder)
                    mentionees_list.append(
                        {
                            "userId": user_id,
                            "index": current_index,
                            "length": len(placeholder),
                        }
                    )
                    current_index += len(placeholder) + 1

                final_mention_text = " ".join(mention_placeholders)
                mention_text_component = FlexText(
                    text=final_mention_text, wrap=True, mentionees=mentionees_list
                )
                body_contents.append(mention_text_component)

            # --- Main Reminder Text ---
            main_text_margin = "md" if self.mentions else "none"
            main_text_component = FlexText(
                text=self.reminder_text or "(Reminder)",
                wrap=True,
                weight="bold",
                margin=main_text_margin,
            )
            body_contents.append(main_text_component)

            # --- Subtext, task_ref, due_date ---
            context_parts = []
            if self.sub_text:
                context_parts.append(self.sub_text)
            if self.task_ref:
                context_parts.append(f"Ref: {self.task_ref}")
            if self.due_date:
                context_parts.append(f"Due: {self.due_date}")

            if context_parts:
                context_text_component = FlexText(
                    text=" | ".join(context_parts),
                    size="xs",
                    color="#aaaaaa",
                    wrap=True,
                    margin="md",
                )
                body_contents.append(context_text_component)

            # --- Actions ---
            footer_contents = []
            if self.interaction_mode == "todo_status_critical":
                footer_contents.extend(
                    [
                        FlexButton(
                            style="primary",
                            color="#DD4B39",
                            height="sm",
                            action=PostbackAction(
                                label="待處理",
                                data=f"action=mark_complete&reminder_id={self.reminder_id}",
                            ),
                        ),
                        FlexSeparator(margin="sm"),
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=PostbackAction(
                                label="稍後提醒",
                                data=f"action=snooze&reminder_id={self.reminder_id}",
                            ),
                        ),
                    ]
                )
            elif self.interaction_mode == "acknowledge_only":
                footer_contents.append(
                    FlexButton(
                        style="primary",
                        height="sm",
                        action=PostbackAction(
                            label="知道了",
                            data=f"action=acknowledge&reminder_id={self.reminder_id}",
                        ),
                    )
                )

            # --- Final Flex Bubble & Message ---
            body_box = FlexBox(layout="vertical", contents=body_contents)
            footer_box = (
                FlexBox(
                    layout="vertical", spacing="sm", contents=footer_contents, flex=0
                )
                if footer_contents
                else None
            )

            bubble = FlexBubble(body=body_box, footer=footer_box)
            flex_message = FlexMessage(
                alt_text=f"Reminder: {self.reminder_text or '(See message)'}",
                contents=bubble,
            )

            return [flex_message]

        except Exception as e:
            logger.exception(f"Failed to build FlexMessage for reminder: {e}")
            raise ValueError(f"Failed to build Line reminder payload: {e}") from e

    def build_payload(self) -> List[Message]:
        """Main entrypoint for building reminder message payload (for consumer)."""
        logger.debug(f"Building reminder payload for RemID={self.reminder_id}")
        return self.build_initial_payload()

    def build_followup_reminder(self) -> List[Message]:
        text = REMINDER_UI_CONFIG.get(self.interaction_mode, {}).get(
            "followup_text", "請盡快處理此事項。"
        )
        return [TextMessage(text=text)]
