# src/orch/tasks/reminder_sending_tasks.py
# -*- coding: utf-8 -*-

"""
Prefect Task for building the initial Reminder message, publishing it,
recording state, and adding to schedule ZSET for external processing.
"""

import pickle
import logging
import json
import datetime
import uuid
import time  # Import time for timestamp score
from typing import Dict, Any, Optional, List, Union, Type
from dateutil.relativedelta import relativedelta

# --- Prefect, Redis Imports ---
try:
    from prefect import task, get_run_logger
    from redis import Redis
    from redis.exceptions import RedisError
    from pydantic import ValidationError
except ImportError:
    raise

# --- Local Imports ---
try:
    from broker.redis_manager import (
        RedisManager,
        get_redis_manager,
        RedisOperationError,
    )

    try:
        from orch.templates.slack.reminder_template import SlackReminderTemplate
    except ImportError:
        SlackReminderTemplate = None
        logging.warning("SlackReminderTemplate not found.")
    try:
        from orch.templates.line.reminder_template import LineReminderTemplate
    except ImportError:
        LineReminderTemplate = None
        logging.warning("LineReminderTemplate not found.")
    # --- ADDED: Import Base Message type for type checking ---
    try:
        from linebot.v3.messaging import (
            Message as LineMessageBase,
        )  # Import base class for check
    except ImportError:
        LineMessageBase = None  # Assign None if import fails
        logging.warning(
            "linebot.v3.messaging.Message not found. Line object serialization might fail type checks."
        )

except ImportError as e:
    print(f"Error importing dependencies for reminder tasks: {e}")
    raise

logger = logging.getLogger(__name__)

# --- Template Map ---
REMINDER_TEMPLATE_MAP: Dict[str, Optional[Type]] = {
    "SlackReminderTemplate": SlackReminderTemplate,
    "LineReminderTemplate": LineReminderTemplate,
}

# --- Redis Key Prefixes ---
STATE_HASH_PREFIX = "reminder:state:"
FOLLOWUP_SCHEDULE_ZSET_KEY = "reminder:followup_schedule"  # Key for the sorted set

# --- Helper Functions ---
def _get_redis_manager_task() -> RedisManager:
    """Gets the RedisManager instance, raising RuntimeError on failure."""
    try:
        return get_redis_manager()
    except Exception as e:
        get_run_logger().critical(f"Task failed get RedisManager: {e}", exc_info=True)
        raise RuntimeError("Failed to get RedisManager instance") from e


def _is_dummy_class(cls: Optional[Type]) -> bool:
    """Checks if a class object is likely a placeholder due to missing imports."""
    if cls is None:
        return True
    return False


# --- Build, Publish, and Record Task ---


@task(
    name="Build, Publish Initial Reminder & Record State",
    retries=1,
    retry_delay_seconds=5,
)
async def build_and_publish_reminder_task(
    channel: str,  # platform ("slack", "line")
    template_name: str,
    context_data: Dict[
        str, Any
    ],  # Includes reminder_id, resolved recipient/mentions, follow_up_policy etc.
    message_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    1. Builds the initial reminder payload using the specified template.
    2. Handles dynamic value replacement (e.g., {{TIME}}, {{task_ref}}) within the context.
    3. Formats mentions based on the platform (currently Slack prepend, Line relies on template).
    4. Publishes the message instruction (recipient, payload/payload_json, context) to the appropriate Redis queue.
    5. If publishing is successful and a valid follow_up_policy exists in the context:
       a. Records the initial state of the reminder (including processed text, policy, due time) to a Redis Hash.
       b. Adds the reminder_id to a Redis Sorted Set (schedule) based on the initial follow-up delay.
    """
    run_logger = get_run_logger()

    reminder_id = context_data.get("reminder_id")
    if not reminder_id:
        run_logger.error("Task Failed: Missing 'reminder_id' in context_data.")
        return False
    nid_str = (
        f"(RemID: {reminder_id})"  # Use reminder_id for consistent logging identifier
    )

    run_logger.debug(
        f"Task started: channel='{channel}', template='{template_name}' {nid_str}"
    )
    run_logger.debug(f"Received context keys: {list(context_data.keys())}")

    # --- 1. Prepare Final Context Data (Placeholders & Mentions) ---
    final_context = (
        context_data.copy()
    )  # Work on a copy to avoid modifying original dict
    try:
        # --- Placeholder Replacement Logic ---
        now_str = datetime.datetime.now().strftime("%m/%d %H:%M")  # Current time string
        # Define placeholders and their corresponding values from the *original* context_data
        # (using original ensures we don't use already-processed values if run multiple times)
        replacements = {
            "{{time}}": now_str,
            "{{task_ref}}": context_data.get("task_ref", "[N/A]"),
            "{{due_date}}": context_data.get("due_date", "[N/A]"),
            "{{report_id}}": context_data.get("report_id", "[N/A]"),
            # Add other common placeholders here
        }

        # --- Process Placeholders in relevant text fields ---
        fields_to_process = ["main_text", "sub_text"]
        for field in fields_to_process:
            if field in final_context and isinstance(final_context[field], str):
                temp_text = final_context[field]
                for placeholder, value in replacements.items():
                    value_str = (
                        str(value) if value is not None else ""
                    )  # Ensure value is string
                    # Mentions are handled separately below or by the Line template
                    if placeholder != "{{mentions}}":
                        temp_text = temp_text.replace(placeholder, value_str)
                final_context[field] = temp_text  # Update the working context copy
                run_logger.debug(f"Processed placeholders in '{field}' {nid_str}")

        # --- Process Placeholders in follow-up thread template (if exists) ---
        follow_up_policy = final_context.get("follow_up_policy")
        if (
            isinstance(follow_up_policy, dict)
            and "thread_message_template" in follow_up_policy
        ):
            thread_template = follow_up_policy.get("thread_message_template", "")
            if isinstance(thread_template, str):
                temp_thread_text = thread_template
                for placeholder, value in replacements.items():
                    value_str = str(value) if value is not None else ""
                    # Avoid replacing {{mentions}} here, handled later in follow-up logic
                    if placeholder != "{{mentions}}":
                        temp_thread_text = temp_thread_text.replace(
                            placeholder, value_str
                        )
                # Update the policy dictionary *within* the final_context copy
                final_context["follow_up_policy"][
                    "thread_message_template"
                ] = temp_thread_text
                run_logger.debug(
                    f"Processed placeholders in 'follow_up_policy.thread_message_template' {nid_str}"
                )

        # --- Mention Formatting (Slack Specific Prepending) ---
        mention_ids: List[str] = final_context.get(
            "mentions", []
        )  # Use resolved IDs from context
        if mention_ids and isinstance(mention_ids, list) and channel == "slack":
            # Filter for valid Slack User IDs (basic check)
            valid_slack_ids = [
                uid
                for uid in mention_ids
                if isinstance(uid, str) and uid.startswith(("U", "W"))
            ]  # Allow U and W IDs
            if len(valid_slack_ids) != len(mention_ids):
                run_logger.warning(
                    f"Some potentially invalid Slack User IDs filtered from mentions list: {mention_ids} {nid_str}"
                )
            # Create Slack mention string: <@U123> <@W456>
            formatted_mention_string = " ".join(
                [f"<@{uid}>" for uid in valid_slack_ids]
            )
            if formatted_mention_string:
                original_main = final_context.get(
                    "main_text", ""
                )  # Get the potentially placeholder-replaced text
                final_context[
                    "main_text"
                ] = f"{formatted_mention_string} {original_main}".strip()
                run_logger.debug(f"Prepended Slack mentions to main_text {nid_str}.")
        # Note: Line mentions are handled inside the LineReminderTemplate using the 'mentions' list in final_context

    except Exception as e:
        # Log warning but continue, context preparation failure might not be fatal
        run_logger.warning(
            f"Error during context preparation {nid_str}: {e}", exc_info=True
        )

    # --- 2. Build Initial Payload using Template ---
    # Payload type depends on the channel/template
    payload: Optional[Union[Dict[str, Any], List[Any]]] = None
    try:
        TemplateClass = REMINDER_TEMPLATE_MAP.get(template_name)
        if not TemplateClass or _is_dummy_class(TemplateClass):
            raise ValueError(f"Template class '{template_name}' not found or invalid.")

        # Instantiate template with the *final_context* (placeholders replaced, Slack mentions prepended)
        template_instance = TemplateClass(**final_context)

        # Determine which build method to call (prefer 'build_initial_payload')
        build_method_name = "build_initial_payload"
        if not hasattr(template_instance, build_method_name):
            build_method_name = "build_payload"  # Fallback to generic build_payload
        if not hasattr(template_instance, build_method_name) or not callable(
            getattr(template_instance, build_method_name)
        ):
            raise ValueError(
                f"Template '{template_name}' missing a callable build method ('{build_method_name}' or 'build_payload')."
            )

        # Call the build method
        payload = getattr(template_instance, build_method_name)()  # Execute the method

        if payload is None:
            raise ValueError(
                f"Template '{template_name}' method '{build_method_name}' returned None."
            )

        # --- Type Validation based on Channel ---
        if channel == "slack":
            if not isinstance(payload, dict):
                raise TypeError(
                    f"Slack template '{template_name}' did not return a dict, got {type(payload)}."
                )
        elif channel == "line":
            # Expect a list of Line SDK Message objects
            if not isinstance(payload, list):
                raise TypeError(
                    f"Line template '{template_name}' did not return a list, got {type(payload)}."
                )
            # Optional runtime check using imported base class if available
            if LineMessageBase:
                for item in payload:
                    if not isinstance(item, LineMessageBase):
                        raise TypeError(
                            f"Item in list from Line template '{template_name}' is not a Line Message object, got {type(item)}."
                        )
        # No specific check for other channels

    except ValidationError as e:  # Catch Pydantic validation errors from template init
        run_logger.error(
            f"Invalid context data for template '{template_name}' during init {nid_str}: {e.errors()}",
            exc_info=False,
        )  # Show Pydantic errors concisely
        return False  # Data error, likely unrecoverable for this task run
    except (
        ValueError,
        TypeError,
        AttributeError,
        Exception,
    ) as e:  # Catch build errors or invalid template structure
        run_logger.error(
            f"Failed to build payload using '{template_name}' {nid_str}: {e}",
            exc_info=True,
        )
        return False  # Build error, unrecoverable

    # --- 3. Prepare and Publish Initial Task Message to Redis ---
    recipient = final_context.get("recipient")
    if not recipient or not isinstance(recipient, str):
        run_logger.error(
            f"Resolved recipient missing or invalid in final_context {nid_str}."
        )
        return False  # Cannot publish without a valid recipient

    # Determine the correct Redis queue key based on the channel
    queue_key_map = {
        "slack": "slack_message_send_queue",
        "line": "line_push_message_queue"
        # Add other channels and their queues here
    }
    queue_key = queue_key_map.get(channel)
    if not queue_key:
        run_logger.error(
            f"No reminder send queue configured for channel '{channel}' {nid_str}."
        )
        return False  # Cannot publish without a target queue

    redis_publish_successful = False  # Flag to track if publish succeeded
    manager = None  # Initialize manager variable

    try:
        # --- Construct the task message dictionary ---
        # Essential fields first
        task_message_dict: Dict[str, Any] = {
            "recipient": recipient,
            "reminder_id": reminder_id,
        }
        # Add global context if provided
        if message_context:
            task_message_dict.update(message_context)
            # Ensure essential fields aren't overwritten by global context
            task_message_dict["recipient"] = recipient
            task_message_dict["reminder_id"] = reminder_id

        # --- Add platform-specific payload ---
        if channel == "slack":
            # Slack consumer expects 'payload' key with the dictionary payload
            if not isinstance(payload, dict):  # Defensive check
                run_logger.error(
                    f"Internal Error: Payload for Slack is not dict {nid_str}"
                )
                return False
            task_message_dict["payload"] = payload
            run_logger.debug(
                f"Prepared task message for Slack with 'payload' dictionary {nid_str}."
            )

        elif channel == "line":
            # Line consumer expects 'payload_json' key with a JSON string
            # representing a list of message dictionaries.
            # 'payload' should be a list of Line SDK Message objects here (e.g., [FlexMessage(...)])

            try:
                # --- START: CORRECT SERIALIZATION FOR LINE using model_dump ---
                if not isinstance(payload, list):  # Defensive check
                    run_logger.error(
                        f"Internal error: Payload for Line is not a list ({type(payload)}) before serialization {nid_str}. Task Failed."
                    )
                    return False
                run_logger.info(f"Payload: {payload}")
                payload_pickle = pickle.dumps(payload).hex()

                task_message_dict["payload_pickle"] = payload_pickle
                run_logger.debug(
                    f"Prepared task message for Line with 'payload_pickle' string {nid_str}."
                )

            except TypeError as e:  # Catch potential errors during model_dump() or json.dumps()
                run_logger.error(
                    f"Failed to serialize payload object to dictionary or JSON string for Line {nid_str}: {e}",
                    exc_info=True,
                )
                return False
            except Exception as e:  # Catch other unexpected errors
                run_logger.error(
                    f"Unexpected error during Line payload processing {nid_str}: {e}",
                    exc_info=True,
                )
                return False

        else:
            # Handle unknown channels - assume 'payload' dict for now, but log warning
            run_logger.warning(
                f"Unknown channel '{channel}' {nid_str}. Assuming 'payload' dictionary structure."
            )
            if not isinstance(payload, dict):
                run_logger.error(
                    f"Payload for unknown channel '{channel}' must be a dictionary, got {type(payload)} {nid_str}."
                )
                return False
            task_message_dict["payload"] = payload

        # --- Serialize the final task message dictionary for Redis ---
        # Use default=str as a fallback for any non-standard types in context etc.
        # The main payload (dict or JSON string) is already handled.
        task_data_json = json.dumps(task_message_dict, default=str, ensure_ascii=False)

        # --- Publish to Redis List ---
        run_logger.debug(
            f"Publishing initial reminder task to list '{queue_key}' {nid_str}."
        )
        # run_logger.debug(f"Final task_data_json for Redis: {task_data_json}") # Be cautious logging full payload

        manager = _get_redis_manager_task()  # Get Redis manager instance
        # Use LPUSH to add the task JSON string to the head of the list
        result = manager.lpush(
            queue_key, [task_data_json]
        )  # lpush expects a list of values

        if result is not None and result > 0:
            redis_publish_successful = True  # Set flag on success
            run_logger.info(
                f"Successfully published initial reminder task to '{queue_key}' {nid_str}."
            )
        else:
            # LPUSH returns the new length of the list, 0 or None might indicate an issue
            run_logger.error(
                f"Failed to publish task to '{queue_key}' (LPUSH result: {result}) {nid_str}."
            )
            # Raise an error to potentially trigger Prefect retry
            raise RedisOperationError(
                f"LPUSH to {queue_key} failed or returned unexpected result: {result}"
            )

    except (
        RedisOperationError,
        RedisError,
        RuntimeError,
    ) as e:  # Catch Redis/Manager specific errors
        run_logger.error(
            f"Redis-related error during initial publish {nid_str}: {e}", exc_info=True
        )
        # Re-raise to allow Prefect's retry mechanism to handle it
        raise
    except TypeError as e:  # Catch errors from the final json.dumps()
        run_logger.error(
            f"Failed to serialize final task message dictionary {nid_str}: {e}",
            exc_info=True,
        )
        return False  # Serialization errors are likely unrecoverable here
    except Exception as e:  # Catch any other unexpected errors during publish preparation
        run_logger.exception(
            f"Unexpected error during initial Redis publish preparation {nid_str}."
        )
        # Re-raise unexpected errors
        raise

    # --- 4. Record State & Add to Schedule ZSET (ONLY IF PUBLISH SUCCEEDED) ---
    if redis_publish_successful:
        follow_up_policy = final_context.get("follow_up_policy")
        # Check if follow_up_policy is a dict and has a valid initial delay
        if isinstance(follow_up_policy, dict):
            initial_delay = follow_up_policy.get("initial_delay_seconds")
            if isinstance(initial_delay, (int, float)) and initial_delay >= 0:
                run_logger.info(
                    f"Follow-up policy found. Recording state and scheduling next check {nid_str}."
                )
                try:
                    # Get Redis manager if not already obtained
                    if manager is None:
                        manager = _get_redis_manager_task()

                    # a) Record Initial State to Redis Hash
                    state_key = f"{STATE_HASH_PREFIX}{reminder_id}"
                    now_utc = datetime.datetime.now(
                        datetime.timezone.utc
                    )  # Use UTC for consistency
                    # Calculate the first follow-up due time based on initial delay
                    followup_due_time = now_utc + relativedelta(
                        seconds=max(0, initial_delay)
                    )

                    # Prepare the state data to save in the Hash
                    # Ensure all necessary info for follow-up checks is included
                    state_to_save = {
                        "reminder_id": reminder_id,
                        "platform": channel,
                        "recipient": recipient,
                        "destination_alias": final_context.get(
                            "destination_alias"
                        ),  # Original alias for context
                        "mention_ids": json.dumps(
                            final_context.get("mentions", [])
                        ),  # Store resolved IDs as JSON string
                        "status": "pending",  # Initial status
                        "template_name": template_name,
                        # Store the text *after* placeholder replacement and mention prepending (for Slack)
                        "main_text": final_context.get("main_text", ""),
                        "sub_text": final_context.get("sub_text", ""),
                        "interaction_mode": final_context.get("interaction_mode"),
                        # Store the *processed* policy (with time replaced in thread template) as JSON string
                        "follow_up_policy": json.dumps(
                            final_context.get("follow_up_policy", {}),
                            default=str,
                            ensure_ascii=False,
                        ),
                        "followup_attempts": 0,  # Initial attempt count
                        "created_at": now_utc.isoformat(),  # ISO 8601 format timestamp
                        "last_updated": now_utc.isoformat(),
                        "followup_due": followup_due_time.isoformat(),  # Store ISO format due time
                        "initial_message_ts": None,  # Placeholder for the actual message TS (updated by consumer maybe)
                        # Store original context data fields used in placeholders for potential re-use
                        "task_ref": context_data.get("task_ref"),
                        "report_id": context_data.get("report_id"),
                        "due_date": context_data.get("due_date"),
                    }
                    # Remove keys with None values to keep the hash cleaner (optional)
                    state_to_save = {
                        k: v for k, v in state_to_save.items() if v is not None
                    }

                    # Use RedisManager's method to set the hash
                    if not manager.set_hash(state_key, state_to_save):
                        # Handle potential failure from set_hash if it returns boolean
                        raise RedisOperationError(
                            f"Failed to save state hash using RedisManager for {nid_str}"
                        )
                    run_logger.info(
                        f"Saved initial state for {reminder_id} to Redis hash '{state_key}'."
                    )

                    # b) Add reminder_id to the Sorted Set for scheduling follow-up checks
                    followup_due_timestamp = (
                        followup_due_time.timestamp()
                    )  # Use Unix timestamp as the score
                    run_logger.info(
                        f"Adding reminder {reminder_id} to schedule ZSET '{FOLLOWUP_SCHEDULE_ZSET_KEY}' with score {followup_due_timestamp:.0f} ({followup_due_time.isoformat()})."
                    )
                    # Use RedisManager's method for ZADD
                    zadd_result = manager.zadd(
                        FOLLOWUP_SCHEDULE_ZSET_KEY,
                        {reminder_id: followup_due_timestamp},
                    )
                    # ZADD returns the number of elements added (should be 1 if new, 0 if updated score)
                    if (
                        zadd_result is None
                    ):  # Check for potential error indication from manager method
                        raise RedisOperationError(
                            f"Failed to add reminder {reminder_id} to schedule ZSET {nid_str} (ZADD result was None)"
                        )
                    run_logger.info(
                        f"Successfully added/updated {reminder_id} in schedule ZSET (ZADD returned {zadd_result})."
                    )

                except (
                    RedisOperationError,
                    RedisError,
                    RuntimeError,
                    Exception,
                ) as state_schedule_e:
                    # Catch errors during state saving or scheduling
                    run_logger.error(
                        f"Error recording state or adding to schedule ZSET {nid_str}: {state_schedule_e}",
                        exc_info=True,
                    )
                    # Even if publish succeeded, failure here means follow-up won't happen correctly.
                    # Decide if the overall task should fail. Returning False seems appropriate.
                    return False  # Fail the task if state/scheduling fails
            else:
                # No valid initial delay found in the policy
                run_logger.info(
                    f"No valid initial_delay_seconds >= 0 found in follow_up_policy. Skipping follow-up scheduling {nid_str}."
                )
        else:
            # No follow_up_policy dictionary found in the context
            run_logger.info(
                f"No follow_up_policy found in context. Skipping follow-up scheduling {nid_str}."
            )

    # If initial publish failed, redis_publish_successful is False, and we don't attempt state/scheduling.
    # The task would have already raised an exception or returned False during publish.

    # If we reach here, it means either:
    # 1. Publish succeeded, and state/scheduling succeeded (or was skipped).
    # 2. Publish succeeded, but state/scheduling failed (returned False above).
    # If publish failed, an exception was raised earlier.
    # So, returning True signifies that the initial publish was attempted (and potentially succeeded)
    # and subsequent critical steps didn't immediately fail or were skipped intentionally.
    # The actual success depends on whether state/scheduling returned False earlier.
    # Let's refine: return True only if publish succeeded AND (state/schedule succeeded OR was skipped).
    return redis_publish_successful  # Return True only if the initial publish was successful. State/Schedule errors return False above.
