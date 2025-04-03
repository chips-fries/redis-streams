# src/orch/tasks/info_sending_tasks.py
# -*- coding: utf-8 -*-

"""
Prefect Tasks for building and publishing INFO messages to send queues.
Handles resolved IDs, dynamic value replacement, and mention formatting.
"""

import logging
import json
import pickle
import datetime  # Import datetime for timestamp
from typing import Dict, Any, Optional, List, Union, Type

# --- Prefect, Redis Imports ---
try:
    from prefect import task, get_run_logger
    from redis import Redis
    from redis.exceptions import RedisError
    from pydantic import (
        ValidationError,
    )  # Keep for template validation if templates use Pydantic
except ImportError:
    raise

# --- Local Imports ---
try:
    # Import RedisManager and error
    from broker.redis_manager import (
        RedisManager,
        get_redis_manager,
        RedisOperationError,
    )

    # --- Import ALL potential template classes ---
    # (Task needs access to the map to find the right class)
    try:
        from orch.templates.slack.info_template import SlackInfoTemplate
    except ImportError:
        SlackInfoTemplate = None
        logging.warning("SlackInfoTemplate not found.")
    try:
        from orch.templates.line.info_template import LineInfoTemplate
    except ImportError:
        LineInfoTemplate = None
        logging.warning("LineInfoTemplate not found.")
    # Add other templates here if needed
except ImportError as e:
    print(f"Error importing dependencies for info tasks: {e}")
    raise

logger = logging.getLogger(__name__)

# --- Template Map (Task uses this to find the class) ---
INFO_TEMPLATE_MAP = {
    "SlackInfoTemplate": SlackInfoTemplate,
    "LineInfoTemplate": LineInfoTemplate,
    # Add other template names and classes here
}

# --- Helper Functions ---


def _get_redis_manager_task() -> RedisManager:
    """Gets the RedisManager instance, raising RuntimeError on failure."""
    try:
        return get_redis_manager()
    except Exception as e:
        get_run_logger().critical(f"Task failed get RedisManager: {e}", exc_info=True)
        # Raise a runtime error to make it clear initialization failed
        raise RuntimeError("Failed to get RedisManager instance") from e


# --- ADDED: Definition for _is_dummy_class ---
def _is_dummy_class(cls: Optional[Type]) -> bool:
    """
    Checks if a class object is likely a placeholder due to missing imports.
    Currently simplified to primarily rely on the None check before this call.
    """
    if cls is None:
        # This case is handled by 'if not TemplateClass:' before calling this helper.
        # If called with None, it's technically a "dummy".
        return True
    # Add more sophisticated checks here if needed, e.g., checking module path
    # module_path = getattr(cls, '__module__', '')
    # if module_path.startswith(('unwanted_module.', 'placeholder_module.')):
    #     return True
    return False  # Assume valid if it's not None


# --- Build and Publish Task (Updated) ---


@task(name="Build and Publish Info Message", retries=1, retry_delay_seconds=3)
async def build_and_publish_info_task(
    # Parameters received from the Flow
    channel: str,  # The platform ("slack", "line")
    template_name: str,  # Name matching a template in INFO_TEMPLATE_MAP
    context_data: Dict[str, Any],  # Context containing resolved IDs and raw data
    message_context: Optional[Dict[str, Any]] = None,  # Global context
) -> bool:
    """
    Builds platform-specific payload using the template, handles dynamic values (like {{TIME}}),
    formats mentions, and publishes the instruction to the Redis queue.

    Expects context_data to contain:
    - recipient (str): The resolved destination ID (Channel, User, Group ID).
    - main_text (str): Primary text content.
    - Optional: sub_text (str): Secondary text, may contain placeholders like {{TIME}}.
    - Optional: mentions (List[str]): List of resolved User IDs to mention.
    - ... other data needed by the specific template class ...
    """
    run_logger = get_run_logger()  # Use specific name for run logger
    nid_str = (
        f"(Context: {message_context.get('notification_id', 'N/A')})"
        if message_context
        else ""
    )
    run_logger.debug(
        f"Task received: channel='{channel}', template='{template_name}' {nid_str}"
    )
    run_logger.debug(f"Received context keys: {list(context_data.keys())}")

    # --- 1. Prepare Final Context Data (Dynamic Values & Mentions) ---
    final_context = context_data.copy()  # Work on a copy

    # a) Replace {{TIME}} placeholder
    try:
        now_str = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )  # Or your preferred format
        if "sub_text" in final_context and isinstance(final_context["sub_text"], str):
            final_context["sub_text"] = final_context["sub_text"].replace(
                "{{TIME}}", now_str
            )
        if "main_text" in final_context and isinstance(final_context["main_text"], str):
            final_context["main_text"] = final_context["main_text"].replace(
                "{{TIME}}", now_str
            )  # Also check main_text
    except Exception as e:
        run_logger.warning(f"Error during placeholder replacement: {e}", exc_info=True)
        # Decide if this error is critical. Probably not, continue with original text.

    logger.info(f"Final context: {final_context}")

    # b) Format Mentions
    mention_ids: List[str] = final_context.get("mentions", [])  # Get resolved IDs
    formatted_mention_string = ""
    if mention_ids and isinstance(mention_ids, list):  # Check if it's a non-empty list
        try:
            if channel == "slack":
                # Format for Slack: <@U123> <@U456>
                valid_slack_ids = [
                    uid
                    for uid in mention_ids
                    if isinstance(uid, str) and uid.startswith("U")
                ]  # Basic validation
                if len(valid_slack_ids) != len(mention_ids):
                    run_logger.warning(
                        f"Some invalid Slack User IDs found in mentions list: {mention_ids}"
                    )
                formatted_mention_string = " ".join(
                    [f"<@{uid}>" for uid in valid_slack_ids]
                )
            elif channel == "line":
                # Line mentions are handled within the template via Flex Message structure.
                # Pass the raw valid IDs. Template needs 'mentions' key.
                valid_line_ids = [
                    uid
                    for uid in mention_ids
                    if isinstance(uid, str) and uid.startswith("U")
                ]  # Basic validation
                if len(valid_line_ids) != len(mention_ids):
                    run_logger.warning(
                        f"Some invalid Line User IDs found in mentions list: {mention_ids}"
                    )
                # The template class will receive final_context['mentions'] = valid_line_ids
                pass  # No string formatting needed here for Line if template handles it
            else:
                run_logger.warning(
                    f"Mention formatting not implemented for channel: {channel}"
                )

            # Decide how to use the formatted string (only applicable if formatted_mention_string is created)
            if formatted_mention_string:
                # Option 1: Add to context for template (less common for simple string)
                # final_context["formatted_mentions"] = formatted_mention_string
                # Option 2: Prepend to main_text (chosen here for Slack)
                if channel == "slack":
                    original_main = final_context.get("main_text", "")
                    final_context[
                        "main_text"
                    ] = f"{formatted_mention_string} {original_main}".strip()
                    run_logger.debug(f"Prepended Slack mentions to main_text.")

        except Exception as e:
            run_logger.warning(f"Error during mention formatting: {e}", exc_info=True)
            # Continue without formatted mentions if error occurs

    # --- 2. Build Payload using Template ---
    run_logger.debug(
        f"Building payload for '{channel}' using template '{template_name}' {nid_str}..."
    )
    TemplateClass = INFO_TEMPLATE_MAP.get(template_name)

    # --- Check if TemplateClass is valid ---
    if not TemplateClass or _is_dummy_class(TemplateClass):  # Use the helper function
        run_logger.error(
            f"Template class '{template_name}' not found or invalid {nid_str}. Task Failed."
        )
        return False  # Explicitly return False for failure

    payload: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    try:
        # Instantiate template with the *final*, processed context
        template_instance = TemplateClass(**final_context)

        if not hasattr(template_instance, "build_payload"):
            run_logger.error(
                f"Template '{template_name}' missing 'build_payload' method {nid_str}. Task Failed."
            )
            return False  # Explicitly return False

        # Build the actual payload structure
        payload = (
            template_instance.build_payload()
        )  # Template uses final_context data internally

        if payload is None:
            run_logger.error(
                f"Template '{template_name}' build_payload returned None {nid_str}. Task Failed."
            )
            return False  # Explicitly return False

        # Basic type check
        if channel == "slack" and not isinstance(payload, dict):
            run_logger.error(
                f"Slack template {template_name} did not return dict {nid_str}. Task Failed."
            )
            return False
        if channel == "line" and not isinstance(
            payload, (list, dict)
        ):  # Allow list or dict for Line
            run_logger.error(
                f"Line template {template_name} did not return list or dict {nid_str}. Task Failed."
            )
            return False

    except ValidationError as e:  # Catch Pydantic validation errors from template init
        run_logger.error(
            f"Invalid data for template '{template_name}' during init {nid_str}: {e.errors()}",
            exc_info=False,
        )
        return False  # Data error, unrecoverable
    except Exception as e:  # Catch errors during build_payload
        run_logger.exception(
            f"Failed to build payload using '{template_name}' {nid_str}. Task Failed."
        )
        return False  # Build error, unrecoverable

    # If payload is still None after checks (shouldn't happen if checks are right)
    if payload is None:
        run_logger.error(
            f"Payload is unexpectedly None after build for {channel} {nid_str}. Task Failed."
        )
        return False

    # --- 3. Prepare and Publish Task to Redis ---
    recipient = final_context.get("recipient")  # Get the resolved ID from final_context

    # --- Add Debugging Log Here ---
    run_logger.debug(
        f"Checking recipient for channel '{channel}': Value='{recipient}', Type={type(recipient)}"
    )
    # --- End Debugging Log ---

    if not recipient or not isinstance(recipient, str):
        run_logger.error(
            f"Resolved recipient missing or invalid in final_context for {channel} {nid_str}. Task Failed."
        )
        return False  # Cannot publish without a recipient

    # Determine target queue key
    queue_key_map = {
        "slack": "slack_message_send_queue",
        "line": "line_push_message_queue",
    }
    queue_key = queue_key_map.get(channel)
    if not queue_key:
        run_logger.error(
            f"No send queue configured for channel '{channel}' {nid_str}. Task Failed."
        )
        return False  # Cannot publish without a queue

    try:
        # --- Platform-Specific Task Message Structure ---
        task_message_dict = {"recipient": recipient}  # Start with recipient

        if channel == "slack":
            # Slack consumer expects 'payload' as a dictionary
            if not isinstance(payload, dict):
                run_logger.error(
                    f"Payload for Slack must be a dictionary, got {type(payload)}. Task Failed."
                )
                return False
            task_message_dict["payload"] = payload
            run_logger.debug(
                "Prepared task message for Slack with 'payload' dictionary."
            )
        elif channel == "line":
            if isinstance(payload, list) and all(
                isinstance(m, dict) and not m.get("text", "").strip() for m in payload
            ):
                run_logger.error(
                    "All Line messages have empty text. Will not publish task."
                )
                return False

            try:
                logger.info(f"Payload: {payload}")
                payload_pickle = pickle.dumps(payload).hex()
                task_message_dict["payload_pickle"] = payload_pickle
                run_logger.debug(
                    "Prepared task message for Line with 'payload_pickle'."
                )
            except Exception as e:
                run_logger.error(
                    f"Failed to pickle payload for Line: {e}", exc_info=True
                )
                return False
        else:
            # Handle other potential channels or default structure
            run_logger.warning(
                f"Unknown channel '{channel}'. Assuming 'payload' dictionary structure."
            )
            if not isinstance(payload, dict):  # Default assumption might be wrong
                run_logger.error(
                    f"Payload for unknown channel '{channel}' must be a dictionary, got {type(payload)}. Task Failed."
                )
                return False
            task_message_dict["payload"] = payload

        if message_context:  # Merge global context
            task_message_dict.update(message_context)

        # Serialize the final task message dictionary for Redis
        task_data_json = json.dumps(task_message_dict, default=str)

        run_logger.info(f"Task Data JSON: {task_data_json}")

        run_logger.debug(
            f"Publishing task to list '{queue_key}' for recipient '{recipient}' {nid_str}."
        )
        # logger.debug(f"Final task_data_json: {task_data_json}")

        manager = _get_redis_manager_task()
        result = manager.lpush(queue_key, [task_data_json])

        if result is not None and result > 0:
            run_logger.info(f"Successfully published task to '{queue_key}' {nid_str}.")
            return True
        else:
            run_logger.error(
                f"Failed publish task to '{queue_key}' (LPUSH result: {result}) {nid_str}."
            )
            raise RedisOperationError(
                f"LPUSH to {queue_key} failed or returned {result}"
            )

    # Keep the same exception handling as before
    except TypeError as e:  # Catch errors from final json.dumps
        run_logger.error(
            f"Failed to serialize final task message: {e} {nid_str}", exc_info=True
        )
        return False
    except (RedisOperationError, RedisError, RuntimeError) as e:
        run_logger.error(
            f"Redis-related error publishing task: {e} {nid_str}", exc_info=True
        )
        raise
    except Exception as e:
        run_logger.exception(f"Unexpected error publishing task: {e} {nid_str}.")
        raise
