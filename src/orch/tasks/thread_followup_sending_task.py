# src/orch/tasks/thread_followup_sending_task.py

from prefect import task, get_run_logger
from broker.redis_manager import RedisManager, get_redis_manager
import json
from typing import Optional, Dict, Any, Union, List, Type
from pydantic import ValidationError
import logging
import pickle

# Import template classes (may be None if not available)
try:
    from orch.templates.slack.thread_followup_template import (
        SlackThreadFollowupTemplate,
    )
except ImportError:
    SlackThreadFollowupTemplate = None

try:
    from orch.templates.line.thread_followup_template import LineThreadFollowupTemplate
except ImportError:
    LineThreadFollowupTemplate = None

FOLLOWUP_TEMPLATE_MAP = {
    "SlackThreadFollowupTemplate": SlackThreadFollowupTemplate,
    "LineThreadFollowupTemplate": LineThreadFollowupTemplate,
}

QUEUE_MAP = {
    "slack": "slack_message_send_queue",
    "line": "line_push_message_queue",
}


def _is_dummy_class(cls: Optional[Type]) -> bool:
    return cls is None


@task(name="Build and Publish Follow-up Reminder Message")
async def build_and_publish_followup_reminder_task(reminder_id: str) -> bool:
    logger = get_run_logger()
    log_prefix = f"[FollowUp:{reminder_id[:8]}]"

    try:
        redis = get_redis_manager()
    except Exception as e:
        logger.error(f"{log_prefix} Failed to get Redis manager: {e}", exc_info=True)
        return False

    logger.info(f"{log_prefix} Fetching reminder state from Redis")
    state = redis.get_hash(f"reminder:state:{reminder_id}")
    if not state:
        logger.error(f"{log_prefix} Reminder state not found.")
        return False

    if state.get("status") != "pending":
        logger.info(
            f"{log_prefix} Reminder {reminder_id} already handled. Skipping follow-up."
        )
        return False

    platform = state.get("platform")
    recipient = state.get("recipient")
    main_text = state.get("main_text", "")
    mentions_json = state.get("mention_ids", "[]")
    sub_text = state.get("sub_text", "")
    interaction_mode = state.get("interaction_mode", "default")
    template_name = state.get("template_name", "")
    thread_template = None
    thread_ts = state.get("initial_message_ts") if platform == "slack" else None

    try:
        mention_ids = json.loads(mentions_json)
    except Exception as e:
        logger.warning(f"{log_prefix} Failed to parse mention_ids: {e}")
        mention_ids = []

    try:
        follow_up_policy = json.loads(state.get("follow_up_policy", "{}"))
        thread_template = follow_up_policy.get("thread_message_template")
    except Exception as e:
        logger.warning(f"{log_prefix} Failed to parse follow_up_policy: {e}")

    if not platform or not recipient:
        logger.error(f"{log_prefix} Missing platform or recipient.")
        return False

    if platform == "slack":
        template_cls = FOLLOWUP_TEMPLATE_MAP.get("SlackThreadFollowupTemplate")
    elif platform == "line":
        template_cls = FOLLOWUP_TEMPLATE_MAP.get("LineThreadFollowupTemplate")
    else:
        logger.error(f"{log_prefix} Unsupported platform: {platform}")
        return False

    if not template_cls or _is_dummy_class(template_cls):
        logger.error(
            f"{log_prefix} Template class for {platform} not found or invalid."
        )
        return False

    context: Dict[str, Any] = {
        "reminder_id": reminder_id,
        "recipient": recipient,
        "main_text": main_text,
        "sub_text": sub_text,
        "mentions": mention_ids,
        "interaction_mode": interaction_mode,
        "thread_template": thread_template,
    }

    if thread_ts:
        context["thread_ts"] = thread_ts

    try:
        template = template_cls(**context)
        payload = template.build_payload()
        logger.debug(f"{log_prefix} Payload built: {payload}")
    except ValidationError as ve:
        logger.error(f"{log_prefix} Template validation error: {ve}")
        return False
    except Exception as e:
        logger.exception(f"{log_prefix} Failed to build payload: {e}")
        return False

    queue_key = QUEUE_MAP.get(platform)
    if not queue_key:
        logger.error(f"{log_prefix} No queue defined for platform: {platform}")
        return False

    task_data: Dict[str, Union[str, Dict[str, Any]]] = {
        "recipient": recipient,
        "reminder_id": reminder_id,
    }

    if platform == "slack":
        task_data["payload"] = payload
    elif platform == "line":
        try:
            payload_pickle = pickle.dumps(payload).hex()
            task_data["payload_pickle"] = payload_pickle
        except Exception as e:
            logger.error(f"{log_prefix} Failed to pickle Line payload: {e}")
            return False

    try:
        redis.lpush(queue_key, [json.dumps(task_data, default=str)])
        logger.info(f"{log_prefix} Follow-up reminder enqueued to {queue_key}.")
        return True
    except Exception as e:
        logger.exception(f"{log_prefix} Failed to enqueue follow-up reminder: {e}")
        return False
