# src/orch/templates/slack/reminder_template.py
# -*- coding: utf-8 -*-

"""Template for Slack Reminder messages with interactive elements."""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)  # orch.templates.slack.reminder_template


class SlackReminderTemplate:
    """
    Builds initial payload for Slack Reminder messages based on interaction mode.
    """

    def __init__(
        self,
        # Core data passed from task (after processing)
        reminder_id: str,
        recipient: str,  # Resolved Destination ID (Channel ID)
        reminder_text: str,  # Main text (already processed for time/mentions)
        sub_text: Optional[str] = None,  # Secondary text (already processed)
        mentions: Optional[
            List[str]
        ] = None,  # List of resolved User IDs (already formatted in main_text?)
        # Keep it if needed for other logic
        # Control parameters from params.json
        interaction_mode: str = "default",  # e.g., "todo_status_critical", "acknowledge_only"
        task_ref: Optional[str] = None,  # Example other context data
        due_date: Optional[str] = None,  # Example other context data
        # ... other fields from context_data ...
        **kwargs,  # Catch any extra data
    ):
        # Store necessary fields
        self.reminder_id = reminder_id
        self.recipient = recipient
        self.reminder_text = reminder_text
        self.sub_text = sub_text
        self.interaction_mode = interaction_mode.lower()
        self.task_ref = task_ref  # Store extra context if needed for payload
        self.due_date = due_date
        self._extra_data = kwargs  # Store unused kwargs

        # Basic validation
        if not all([self.reminder_id, self.recipient, self.reminder_text]):
            logger.error(
                f"SlackReminderTemplate RemID {self.reminder_id} missing required fields."
            )
            raise ValueError("Missing required fields for SlackReminderTemplate.")

    def _build_base_blocks(self) -> List[Dict[str, Any]]:
        """Builds the common text and context blocks."""
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": self.reminder_text or "(Reminder)"},
            }
        ]
        context_elements = []
        if self.sub_text:
            context_elements.append({"type": "mrkdwn", "text": self.sub_text})
        # Add other context like task_ref or due_date if desired
        if self.task_ref:
            if context_elements:
                context_elements.append({"type": "mrkdwn", "text": " | "})
            context_elements.append({"type": "mrkdwn", "text": f"Ref: {self.task_ref}"})
        if self.due_date:
            if context_elements:
                context_elements.append({"type": "mrkdwn", "text": " | "})
            context_elements.append({"type": "mrkdwn", "text": f"Due: {self.due_date}"})

        if context_elements:
            blocks.append({"type": "context", "elements": context_elements})
        return blocks

    def build_initial_payload(self) -> Dict[str, Any]:
        """Builds the initial message payload with buttons based on interaction_mode."""
        blocks = self._build_base_blocks()
        action_elements = []

        # --- Button Logic based on Mode ---
        if self.interaction_mode == "todo_status_critical":
            # Initial state: Red "待處理" button
            action_elements.append(
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": ":red_circle: 待處理",
                        "emoji": True,
                    },
                    "style": "danger",  # Use danger for critical/pending
                    "action_id": "reminder_toggle_status_action",  # Action ID for interactivity handler
                    # Value includes intent and reminder_id for the handler
                    "value": f"mark_complete:{self.reminder_id}",
                }
            )
            # Optionally add a "Snooze" button
            action_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "稍後提醒", "emoji": True},
                    "action_id": "reminder_snooze_action",
                    "value": f"snooze:{self.reminder_id}",
                }
            )

        elif self.interaction_mode == "acknowledge_only":
            action_elements.append(
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "知道了 :white_check_mark:",
                        "emoji": True,
                    },
                    "style": "primary",
                    "action_id": "reminder_acknowledge_action",
                    "value": f"acknowledge:{self.reminder_id}",
                }
            )

        # Add other modes here...
        elif self.interaction_mode == "yes_no_question":
            action_elements.extend(
                [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Yes"},
                        "style": "primary",
                        "action_id": "reminder_yes_action",
                        "value": f"yes:{self.reminder_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "No"},
                        "style": "danger",
                        "action_id": "reminder_no_action",
                        "value": f"no:{self.reminder_id}",
                    },
                ]
            )

        elif self.interaction_mode == "default" or self.interaction_mode == "no_action":
            # No buttons needed for these modes
            pass
        else:
            logger.warning(
                f"Unknown interaction_mode '{self.interaction_mode}' for RemID {self.reminder_id}. No buttons generated."
            )

        # Add actions block if elements were generated
        if action_elements:
            blocks.append({"type": "actions", "elements": action_elements})

        # --- Fallback Text ---
        # Include mode for easier debugging if needed
        fallback_text = f"Reminder [{self.interaction_mode}]: {self.reminder_text or '(See message)'}"
        if self.sub_text:
            fallback_text += f" / {self.sub_text}"

        return {"text": fallback_text[:3000], "blocks": blocks}

    def build_payload(self) -> Dict[str, Any]:
        """Generic build method, defaults to building the initial payload."""
        # This provides a fallback if the task doesn't specify payload_type
        logger.warning(
            f"Using generic build_payload for RemID {self.reminder_id}, defaulting to initial payload."
        )
        return self.build_initial_payload()

    # Note: build_followup_payload might be needed by the send_thread_followup_task later
    # def build_followup_payload(self) -> Dict[str, Any]:
    #     # Build simple text payload for thread follow-up using self.reminder_text etc.
    #     # May need access to the thread_message_template from policy
    #     pass
