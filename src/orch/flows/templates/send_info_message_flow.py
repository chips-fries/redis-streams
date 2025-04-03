from datetime import datetime
from typing import Optional, List, Dict, Any

from prefect import flow, get_run_logger

from orch.tasks.info_sending_tasks import build_and_publish_info_task
from orch.utils.targeting import get_destination_id, resolve_mention_aliases


@flow(name="Send Info Message Flow")
async def send_info_message_flow(
    targets: List[Dict[str, Any]],
    message_context: Optional[Dict[str, Any]] = None,
    trigger_source: str = "api_info_endpoint",
):
    """
    Flow to send informational messages to multiple platforms and destinations.

    Parameters:
    - targets (List[Dict]): List of targets, each containing:
        - platform: str (e.g. 'slack', 'line')
        - template_name: str (e.g. 'SlackInfoTemplate')
        - context_data: dict with keys:
            - destination_alias: str
            - main_text: str
            - Optional: sub_text, mention_aliases
    - message_context (Dict): Optional logging context
    - trigger_source (str): Optional source identifier for logging/auditing
    """
    logger = get_run_logger()
    flow_run_id = getattr(logger, "flow_run_id", "N/A")
    log_prefix = f"[INFO FLOW] (Run ID: {flow_run_id})"

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
        sub_text = (
            context_data.get("sub_text")
            or f"Default subtext: {datetime.now().isoformat()}"
        )
        mention_aliases = context_data.get("mention_aliases") or []

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

        context = {
            "recipient": recipient,
            "main_text": main_text,
            "sub_text": sub_text,
        }

        if mention_aliases:
            mentions = resolve_mention_aliases(platform, mention_aliases)
            context["mentions"] = mentions
            logger.info(f"{target_log_prefix} Resolved mentions: {mentions}")

        logger.info(f"{target_log_prefix} Publishing info message task...")
        success = await build_and_publish_info_task(
            channel=platform,
            template_name=template_name,
            context_data=context,
            message_context=message_context or {"trigger_source": trigger_source},
        )

        if not success:
            logger.error(f"{target_log_prefix} Task failed during publishing stage.")
        else:
            logger.info(f"{target_log_prefix} Info message successfully published.")
