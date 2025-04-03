# scripts/debug_reminder_queue.py

import json
from broker.redis_manager import RedisManager


def debug_reminder_queue():
    redis = RedisManager()

    print("--- Due Reminder IDs in Sorted Set ---")
    due_ids = redis.zrangebyscore("reminder:followup_schedule", "-inf", "+inf") or []
    print(f"Found {len(due_ids)} due reminder(s):")
    for i, rem_id in enumerate(due_ids):
        print(f"[{i+1}] {rem_id}")

    print("\n--- Contents of slack_message_send_queue ---")
    slack_items = redis.redis.lrange("slack_message_send_queue", 0, -1) or []
    for i, item in enumerate(slack_items):
        try:
            parsed = json.loads(item)
        except Exception:
            parsed = item
        print(f"[{i+1}] {parsed}")

    print("\n--- Contents of line_push_message_queue ---")
    line_items = redis.redis.lrange("line_push_message_queue", 0, -1) or []
    for i, item in enumerate(line_items):
        try:
            parsed = json.loads(item)
        except Exception:
            parsed = item
        print(f"[{i+1}] {parsed}")


if __name__ == "__main__":
    debug_reminder_queue()
