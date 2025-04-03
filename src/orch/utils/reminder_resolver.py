# src/orch/utils/reminder_resolver.py

import datetime
from typing import Optional

from broker.redis_manager import get_redis_manager
from orch.tasks.reminder_sending_tasks import FOLLOWUP_SCHEDULE_ZSET_KEY
from utils.notification_tracker import STATUS_RESOLVED
from slack.templates.reminder import SlackReminderUpdateTemplate
from broker.redis_constants import REDIS_STREAM_PREFIX


async def resolve_reminder(reminder_id: str, slack_update: Optional[dict] = None) -> bool:
    """
    Marks a reminder as resolved in Redis so follow-up messages are no longer sent.
    Optionally sends an update payload to Slack if `slack_update` is provided.
    """
    redis = get_redis_manager()
    state_key = f"reminder:state:{reminder_id}"

    state = redis.get_hash(state_key)
    if not state:
        return False

    if state.get("status") != "pending":
        return False  # Already resolved or not in a valid state

    resolved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["status"] = STATUS_RESOLVED
    state["resolved_at"] = resolved_at
    state["last_updated"] = resolved_at

    redis.set_hash(state_key, state)
    redis.zrem(FOLLOWUP_SCHEDULE_ZSET_KEY, reminder_id)

    # 🔁 發布 Slack 更新事件
    if slack_update:
        payload = SlackReminderUpdateTemplate(
            reminder_id=reminder_id,
            channel=slack_update["channel"],
            ts=slack_update["ts"],
        ).build()
        redis.publish(
            stream=f"{REDIS_STREAM_PREFIX}:slack:update",
            data=payload,
        )

    return True
