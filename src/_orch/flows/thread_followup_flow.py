# src/orch/flows/thread_followup_flow.py

from prefect import flow, get_run_logger
from _orch.tasks.thread_followup_sending_task import (
    build_and_publish_followup_reminder_task,
)


@flow(name="Send Follow-up Reminder")
def thread_followup_flow(reminder_id: str) -> bool:
    """
    Flow to trigger a follow-up message based on a reminder ID.
    Reads state from Redis, rebuilds payload from template,
    and publishes follow-up reminder to the appropriate platform queue.
    """
    logger = get_run_logger()
    logger.info(f"Starting follow-up flow for reminder_id: {reminder_id}")

    try:
        result = build_and_publish_followup_reminder_task(reminder_id)
        return result
    except Exception as e:
        logger.exception(f"Follow-up flow failed for {reminder_id}: {e}")
        return False


if __name__ == "__main__":
    import sys
    import asyncio

    if len(sys.argv) < 2:
        print("Usage: python thread_followup_flow.py <reminder_id>")
        sys.exit(1)

    reminder_id = sys.argv[1]
    asyncio.run(thread_followup_flow(reminder_id))
