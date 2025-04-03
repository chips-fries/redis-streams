# scripts/manual_followup_test.py
# -*- coding: utf-8 -*-

# redis-cli -a $REDIS_PASSWORD zrangebyscore reminder:followup_schedule -inf $(date +%s)

import sys
import json
import asyncio
from redis import Redis
from broker.redis_manager import get_redis_manager
from _orch.flows.thread_followup_flow import thread_followup_flow


def print_error(msg):
    print(f"\033[91m[ERROR]\033[0m {msg}")


def print_ok(msg):
    print(f"\033[92m[OK]\033[0m {msg}")


def print_info(msg):
    print(f"[INFO] {msg}")


def validate_reminder_state(reminder_id: str) -> bool:
    redis = get_redis_manager()
    key = f"reminder:state:{reminder_id}"
    state = redis.get_hash(key)

    if not state:
        print_error(f"Reminder state not found for key '{key}'")
        return False

    required_fields = ["platform", "recipient", "reminder_text", "follow_up_policy"]
    for field in required_fields:
        if not state.get(field):
            print_error(f"Missing required field '{field}' in state")
            return False

    print_ok("Reminder state is valid.")

    try:
        follow_up_policy = json.loads(state.get("follow_up_policy", "{}"))
        if "thread_message_template" not in follow_up_policy:
            print_error("follow_up_policy is missing 'thread_message_template'")
            return False
        print_ok("follow_up_policy contains thread_message_template.")
    except Exception as e:
        print_error(f"Failed to parse follow_up_policy: {e}")
        return False

    return True


async def run_followup_test(reminder_id: str):
    print_info(f"Running follow-up test for reminder_id: {reminder_id}")

    if not validate_reminder_state(reminder_id):
        print_error("State validation failed. Aborting follow-up.")
        return

    print_info("Invoking thread_followup_flow...")
    try:
        result = await thread_followup_flow(reminder_id=reminder_id)
        print_ok("thread_followup_flow execution completed.")
    except Exception as e:
        print_error(f"thread_followup_flow raised exception: {e}")
        return

    redis = get_redis_manager()
    queue_map = {
        "slack": "slack_message_send_queue",
        "line": "line_push_message_queue",
    }
    platform = (
        get_redis_manager().get_hash(f"reminder:state:{reminder_id}").get("platform")
    )
    queue_key = queue_map.get(platform)

    if queue_key:
        msg = redis.lindex(queue_key, 0)
        if msg and reminder_id in msg.decode():
            print_ok(f"Message enqueued in '{queue_key}': contains reminder_id.")
        else:
            print_error(f"No message with reminder_id found in queue '{queue_key}'")
    else:
        print_error(f"Unsupported platform '{platform}' or no queue configured.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: poetry run python scripts/manual_followup_test.py <reminder_id>")
        sys.exit(1)

    reminder_id = sys.argv[1]
    asyncio.run(run_followup_test(reminder_id))
