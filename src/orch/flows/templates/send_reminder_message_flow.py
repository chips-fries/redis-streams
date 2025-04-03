import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from prefect import flow, get_run_logger

from orch.tasks.reminder_sending_tasks import build_and_publish_reminder_task
from orch.utils.targeting import get_destination_id, resolve_mention_aliases


@flow(name="Send Reminder Message Flow")
async def send_reminder_message_flow(
    targets: List[Dict[str, Any]],
    message_context: Optional[Dict[str, Any]] = None,
    trigger_source: str = "api_reminder_endpoint",
):
    """
    Flow to send reminder messages with interactive components.

    Parameters:
    - targets (List[Dict]): List of targets, each containing:
        - platform: str (e.g. 'slack', 'line')
        - template_name: str (e.g. 'SlackReminderTemplate')
        - context_data: dict with keys:
            - destination_alias: str
            - main_text: str
            - Optional: sub_text, mention_aliases, initial_delay_seconds
    - message_context (Dict): Optional logging context
    - trigger_source (str): Optional source identifier for logging/auditing
    """
    logger = get_run_logger()
    flow_run_id = getattr(logger, "flow_run_id", "N/A")
    log_prefix = f"[REMINDER FLOW] (Run ID: {flow_run_id})"

    if not targets:
        logger.warning(f"{log_prefix} No targets provided. Flow will exit.")
        return

    for i, target in enumerate(targets):
        platform = target.get("platform")
        template_name = target.get("template_name")
        context_data = target.get("context_data")

        target_log_prefix = f"{log_prefix} Target {i+1}/{len(targets)}"

        if not all([platform, template_name, context_data]):
            logger.error(
                f"{target_log_prefix} Invalid target. Skipping. Target: {target}"
            )
            continue

        destination_alias = context_data.get("destination_alias")
        main_text = context_data.get("main_text")
        sub_text = context_data.get("sub_text")
        mention_aliases = context_data.get("mention_aliases") or []
        # follow_up_policy = context_data.get("follow_up_policy")
        # initial_delay_seconds = context_data.get("initial_delay_seconds", 600)

        if not destination_alias or not main_text:
            logger.error(
                f"{target_log_prefix} Missing destination_alias or main_text. Skipping."
            )
            continue

        logger.info(
            f"{target_log_prefix} Sending to platform='{platform}', destination='{destination_alias}'"
        )

        recipient = get_destination_id(platform, destination_alias)
        if not recipient:
            logger.error(
                f"{target_log_prefix} Could not resolve destination alias '{destination_alias}'"
            )
            continue

        sub_text = sub_text + "\n時間: {{time}}" if sub_text else "時間: {{time}}"

        if mention_aliases:
            mentions = resolve_mention_aliases(platform, mention_aliases)
            context_data["mentions"] = mentions
            logger.info(f"{target_log_prefix} Resolved mentions: {mentions}")

        reminder_id = str(uuid.uuid4())
        context_data["recipient"] = recipient
        context_data["sub_text"] = sub_text
        context_data["reminder_id"] = reminder_id

        logger.info(f"{target_log_prefix} Publishing reminder message task...")
        success = await build_and_publish_reminder_task(
            channel=platform,
            template_name=template_name,
            context_data=context_data,
            message_context=message_context or {"trigger_source": trigger_source},
        )

        if not success:
            logger.error(f"{target_log_prefix} Task failed during publishing stage.")
        else:
            logger.info(f"{target_log_prefix} Reminder message successfully published.")
