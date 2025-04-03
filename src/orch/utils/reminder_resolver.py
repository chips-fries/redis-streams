# src/orch/utils/reminder_resolver.py

import datetime
from broker.redis_manager import get_redis_manager
from orch.tasks.reminder_sending_tasks import FOLLOWUP_SCHEDULE_ZSET_KEY


def resolve_reminder(reminder_id: str) -> bool:
    """
    Marks a reminder as resolved in Redis so follow-up messages are no longer sent.
    Also removes the reminder_id from the follow-up schedule ZSET.
    """
    redis = get_redis_manager()
    state_key = f"reminder:state:{reminder_id}"

    state = redis.get_hash(state_key)
    if not state:
        return False

    if state.get("status") != "pending":
        return False  # Already resolved or not in a valid state

    resolved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["status"] = "resolved"
    state["resolved_at"] = resolved_at
    state["last_updated"] = resolved_at

    redis.set_hash(state_key, state)
    redis.zrem(FOLLOWUP_SCHEDULE_ZSET_KEY, reminder_id)
    return True
