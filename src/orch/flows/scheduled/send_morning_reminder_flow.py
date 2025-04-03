import asyncio
from prefect import flow
from datetime import datetime
from utils.settings import ENV
from orch.flows.templates.send_reminder_message_flow import send_reminder_message_flow


@flow(name="Scheduled - Morning Wake Up Reminder")
async def send_morning_reminder_flow():
    """
    This flow runs every morning (e.g. 9:00 AM) to send a wake-up reminder.
    """
    await send_reminder_message_flow(
        targets=[
            {
                "platform": "slack",
                "template_name": "SlackReminderTemplate",
                "context_data": {
                    "destination_alias": f"{ENV}_channel",
                    "mention_aliases": ["bacon"],
                    "interaction_mode": "todo_status_critical",
                    "main_text": "Good morning!.",
                    "sub_text": "Please click the button to confirm you're alive.",
                    "follow_up_policy": {
                        "initial_delay_seconds": 10,
                        "repeat_delay_seconds": 10,
                        "max_attempts": 3,
                        "thread_message_template": "{{main_text}} 尚未處理！",
                    },
                },
            },
            {
                "platform": "line",
                "template_name": "LineReminderTemplate",
                "context_data": {
                    "destination_alias": "bacon_dm",
                    "mention_aliases": ["bacon"],
                    "interaction_mode": "acknowledge_only",
                    "main_text": "早安 ☀️ 請點擊按鈕確認你醒著！",
                    "follow_up_policy": {
                        "initial_delay_seconds": 10,
                        "max_attempts": 5,
                        "thread_message_template": "報告 {{report_id}} 還沒好嗎？",
                    },
                },
            },
        ],
        message_context={"trigger": "scheduled_morning_reminder"},
        trigger_source="scheduled_morning_reminder",
    )


if __name__ == "__main__":
    asyncio.run(send_morning_reminder_flow())
