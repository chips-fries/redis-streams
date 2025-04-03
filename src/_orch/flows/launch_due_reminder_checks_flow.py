# src/orch/flows/launch_due_reminder_checks_flow.py

import logging
import time
from typing import List
from prefect import flow, get_run_logger
from broker.redis_manager import RedisManager
from _orch.flows.thread_followup_flow import thread_followup_flow

logger = logging.getLogger(__name__)

FOLLOWUP_ZSET_KEY = "reminder:followup_schedule"


@flow(name="Example - Send Reminder Message", retries=0)
def launch_due_reminder_checks_flow() -> None:
    run_logger = get_run_logger()
    redis = RedisManager()

    # Fetch all reminders that are due now or in the past
    try:
        now_ts = time.time()
        due_ids: List[bytes] = redis.zrangebyscore(FOLLOWUP_ZSET_KEY, 0, now_ts)
        if not due_ids:
            run_logger.info("No due reminders found in ZSET.")
            return

        run_logger.info(
            f"Found {len(due_ids)} due reminder(s). Launching follow-up flows..."
        )
        for raw_id in due_ids:
            reminder_id = raw_id.decode()
            try:
                thread_followup_flow(reminder_id=reminder_id)
                run_logger.info(f"Triggered follow-up flow for reminder {reminder_id}.")
            except Exception as e:
                run_logger.exception(
                    f"Failed to trigger follow-up flow for {reminder_id}: {e}"
                )

    except Exception as e:
        run_logger.exception(f"Failed to check or launch due reminders: {e}")
