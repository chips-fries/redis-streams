# src/consumer/consumers/slack_sender.py
# -*- coding: utf-8 -*-

"""Consumer implementation for sending new messages/replies to Slack using chat.postMessage."""

import logging
import json
import time
from typing import Dict, Any, Optional, List

# --- SDK Imports ---
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    logging.getLogger(__name__).warning(
        "slack_sdk not found. SlackMessageSenderConsumer disabled."
    )

    class WebClient:
        pass

    class SlackApiError(Exception):
        pass


# --- Local Imports ---
try:
    # Import the correct list-based BaseConsumer from base package
    from ..base.consumer import BaseConsumer  # Relative import from sibling 'base'

    # Import custom exceptions used for signaling
    from ..base.exceptions import TransientError, UnrecoverableError

    # Import the registry decorator from sibling 'registry' file
    from ..registry import register_consumer

    # Import settings from utils package
    from utils.settings import SLACK_BOT_TOKEN

    # Import specific config error for init failures
    from broker.redis_manager import RedisConfigurationError
except ImportError as e:
    logging.getLogger(__name__).critical(
        f"Failed imports for SlackMessageSenderConsumer: {e}"
    )
    raise

logger = logging.getLogger(__name__)  # consumer.consumers.slack_sender


@register_consumer("SlackMessageSender")  # Renamed registration key
class SlackMessageSenderConsumer(BaseConsumer):
    """
    Listens on a Redis List for tasks and sends messages/replies to Slack
    using `chat.postMessage` API. Includes internal retries.
    Expected task JSON string: {"recipient": "ID", "payload": {"text": "...", "blocks": [...], "thread_ts": "..."}}
    """

    MAX_SEND_RETRIES = 2
    RETRY_DELAY_SECONDS = 3.0

    def __init__(
        self,
        listen_key: str,
        consumer_name: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        """Initializes SlackMessageSenderConsumer and Slack WebClient."""
        # Call BaseConsumer init first - it handles redis_manager etc.
        super().__init__(
            listen_key=listen_key,
            consumer_name=consumer_name,
            settings=settings,
            **kwargs,
        )

        # --- Initialize Slack Client ---
        if not SLACK_BOT_TOKEN:
            # Use specific config error if token is missing during setup
            raise RedisConfigurationError(
                f"[{self.consumer_name}] SLACK_BOT_TOKEN setting is missing."
            )
        try:
            # Check if SDK actually loaded or if we have the dummy class
            if WebClient.__module__ == __name__ or WebClient.__module__.startswith(
                "consumer."
            ):  # Check for dummy
                raise ImportError("slack_sdk missing or not installed properly.")
            # Use sync client for threading model in BaseConsumer
            self.slack_client = WebClient(token=SLACK_BOT_TOKEN)
            logger.info(
                f"[{self.consumer_name}] Slack WebClient initialized for sending."
            )
            # Optional: Test token validity (adds startup time)
            # self.slack_client.auth_test()
        except ImportError as e:
            raise RedisConfigurationError(f"[{self.consumer_name}] {e}") from e
        except Exception as e:
            # Catch other init errors like invalid token format handled by SDK
            raise RedisConfigurationError(
                f"[{self.consumer_name}] Failed Slack init: {e}"
            ) from e

        # --- Apply Retry Settings ---
        # Load from settings dict provided during init, fallback to class defaults
        self._apply_retry_settings()

    def _apply_retry_settings(self):
        """Applies retry settings from self.settings or uses class defaults."""
        if self.settings:  # Check if settings dict exists
            try:
                self.max_retries = int(
                    self.settings.get("max_send_retries", self.MAX_SEND_RETRIES)
                )
                self.retry_delay = float(
                    self.settings.get("retry_delay_seconds", self.RETRY_DELAY_SECONDS)
                )
                # Add validation for sensible values
                if self.max_retries < 0:
                    self.max_retries = self.MAX_SEND_RETRIES
                    logger.warning(
                        "max_send_retries cannot be negative, using default."
                    )
                if self.retry_delay <= 0:
                    self.retry_delay = self.RETRY_DELAY_SECONDS
                    logger.warning(
                        "retry_delay_seconds must be positive, using default."
                    )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"[{self.consumer_name}] Invalid retry settings in config: {e}. Using defaults."
                )
                self.max_retries = self.MAX_SEND_RETRIES
                self.retry_delay = self.RETRY_DELAY_SECONDS
        else:
            # Use class defaults if no settings provided
            self.max_retries = self.MAX_SEND_RETRIES
            self.retry_delay = self.RETRY_DELAY_SECONDS
        logger.info(
            f"[{self.consumer_name}] Retry policy: Max Retries={self.max_retries}, Delay={self.retry_delay}s"
        )

    # --- Override BaseConsumer's abstract method ---
    def process_task(self, task_data: str) -> bool:
        """
        Parses the task JSON string, attempts to send the message to Slack
        using chat.postMessage, and handles internal retries for transient errors.

        Args:
            task_data (str): The decoded JSON string task data from the Redis List.
                             Expected format: '{"recipient": "...", "payload": {...}}'

        Returns:
            bool: True if handled (success or unrecoverable failure after retries/DLQ),
                  False only if interrupted by stop signal during retry wait.

        Raises:
            UnrecoverableError: If the task data format is invalid or a Slack API
                                error indicates a permanent failure.
        """
        logger.debug(f"[{self.consumer_name}] Processing Slack send task...")
        try:
            # --- 1. Parse Task Data (Now receives string) ---
            data = json.loads(task_data)
            recipient = data.get("recipient")
            payload = data.get("payload")  # Payload should be a dictionary
            if not isinstance(recipient, str) or not recipient:
                raise ValueError(
                    "Task data must include a non-empty string 'recipient'."
                )
            if not isinstance(payload, dict) or (
                "text" not in payload and "blocks" not in payload
            ):
                raise ValueError(
                    "Task data must include a 'payload' object with 'text' or 'blocks'."
                )
            # Extract thread_ts from payload if present
            thread_ts = payload.get("thread_ts")
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # Invalid format received from the list. This is unrecoverable for this task.
            logger.error(
                f"[{self.consumer_name}] Invalid Slack task format: {e}. Raw data: {task_data[:500]}",
                exc_info=False,
            )
            # Raise UnrecoverableError. The BaseConsumer's run loop will catch this,
            # log it, potentially push to DLQ (if _push_to_dlq is called), and consider the task handled.
            raise UnrecoverableError(f"Invalid task format: {e}") from e

        # --- 2. Attempt Sending with Internal Retries ---
        last_exception: Optional[Exception] = None
        # Loop for max_retries + 1 total attempts (initial + retries)
        for attempt in range(self.max_retries + 1):
            # Check if stop signal received before making network call or sleeping
            if not self._running.is_set():
                logger.warning(
                    f"[{self.consumer_name}] Stop signal received during Slack send retry loop for {recipient}. Aborting."
                )
                # Indicate failure due to interruption. It wasn't fully handled.
                # Depending on exact requirements, could try to requeue task_data here.
                return False  # Signal abnormal termination

            try:
                # --- Make the API Call ---
                log_prefix = f"[{self.consumer_name}] Attempt {attempt + 1}/{self.max_retries + 1}"
                log_target = f"Slack {recipient}" + (
                    f" thread {thread_ts}" if thread_ts else ""
                )
                logger.info(f"{log_prefix} sending to {log_target}")

                # Use the initialized sync client
                response = self.slack_client.chat_postMessage(
                    channel=recipient,
                    text=payload.get("text"),  # Use text from payload
                    blocks=payload.get("blocks"),  # Use blocks from payload
                    thread_ts=thread_ts,  # Pass along if present
                )

                # --- Check Response ---
                if response and response.get("ok"):
                    ts = response.get("ts")
                    logger.info(
                        f"{log_prefix} SUCCESS sending to {log_target}. ts={ts}"
                    )
                    # Task completed successfully
                    try:
                        redis = self.redis_manager
                        state_key = f"reminder:state:{data.get('reminder_id')}"
                        redis.set_hash_field(state_key, "initial_message_ts", ts)
                        logger.debug(
                            f"{log_prefix} Saved initial_message_ts to Redis state."
                        )
                    except Exception as e:
                        logger.warning(
                            f"{log_prefix} Failed to save initial_message_ts: {e}"
                        )

                    return True  # Indicate handled

                # --- Handle API Error in Response Body (If SlackApiError not raised) ---
                error_code = (
                    response.get("error", "api_not_ok")
                    if response
                    else "empty_response"
                )
                logger.error(
                    f"{log_prefix} FAILED sending to {log_target}. Slack API response !OK. Error: {error_code}"
                )
                # Classify based on known unrecoverable error codes for chat.postMessage
                if error_code in [
                    "channel_not_found",
                    "is_archived",
                    "invalid_auth",
                    "token_revoked",
                    "not_in_channel",
                    "user_not_found",
                    "restricted_action",
                    "invalid_blocks",
                    "message_too_long",
                    "metadata_too_long",
                    "too_many_attachments",
                ]:
                    # These errors won't be fixed by retrying the same request
                    raise UnrecoverableError(f"Slack API error ({error_code})")
                else:
                    # Assume other errors might be transient (e.g., internal Slack issue, temporary glitch)
                    raise TransientError(f"Slack API error ({error_code})")

            except SlackApiError as e:
                # --- Handle Errors Raised by SDK ---
                response_data = e.response.data if e.response else {}
                error_code = response_data.get("error", "sdk_api_error")
                status_code = e.response.status_code if e.response else -1
                logger.warning(
                    f"{log_prefix} FAILED sending to {log_target}. Slack SDK Error (Code:{error_code}, Status:{status_code}): {e}",
                    exc_info=False,
                )
                last_exception = e  # Store the exception for potential DLQ

                # Classify based on error code and status code
                unrecoverable_codes = [
                    "invalid_payload",
                    "invalid_auth",
                    "token_revoked",
                    "missing_scope",
                    "channel_not_found",
                    "is_archived",
                    "not_in_channel",
                    "user_not_found",
                    "message_too_long",
                    "metadata_too_long",
                    "too_many_attachments",
                    "message_not_found",
                    "thread_not_found",
                    "cant_reply_to_message",  # Thread specific
                    "restricted_action",
                    "invalid_blocks",
                    "ekm_access_denied",
                ]
                if error_code in unrecoverable_codes or status_code in [
                    400,
                    403,
                    404,
                ]:  # Bad request, Forbidden, Not found
                    # These indicate a problem with the request or permissions that retrying won't fix
                    raise UnrecoverableError(
                        f"Unrecoverable Slack API error ({error_code}): {e}"
                    ) from e
                # Check if max retries reached for transient errors (like rate limit, server error)
                elif attempt >= self.max_retries:
                    logger.error(
                        f"[{self.consumer_name}] Max retries ({self.max_retries + 1}) reached for {log_target}. Last error: {e}"
                    )
                    break  # Exit retry loop
                else:
                    # Transient error (e.g., 429 ratelimited, 5xx server error, network issues wrapped by SDK)
                    # Wait before the next attempt
                    logger.info(
                        f"[{self.consumer_name}] Transient error for {log_target}. Waiting {self.retry_delay:.1f}s before retry..."
                    )
                    self._running.wait(timeout=self.retry_delay)
                    # Continue to the next iteration of the loop for retry

            except ConnectionError as e:  # Network errors -> Transient
                logger.warning(
                    f"{log_prefix} FAILED sending to {log_target}. Network Error: {e}",
                    exc_info=False,
                )
                last_exception = e
                if attempt >= self.max_retries:
                    break
                else:
                    logger.info(
                        f"[{self.consumer_name}] Waiting {self.retry_delay:.1f}s after network error..."
                    )
                    self._running.wait(timeout=self.retry_delay)

            except UnrecoverableError:
                # If an UnrecoverableError was raised explicitly (e.g., from non-OK response check)
                # Re-raise it to be caught by the outer try-except in the run loop
                raise

            except Exception as e:  # Catch any other unexpected errors during API call/response handling
                logger.exception(
                    f"{log_prefix} FAILED sending to {log_target}. Unexpected Error."
                )
                last_exception = e
                if attempt >= self.max_retries:
                    break
                else:
                    logger.info(
                        f"[{self.consumer_name}] Waiting {self.retry_delay:.1f}s after unexpected error..."
                    )
                    self._running.wait(timeout=self.retry_delay)

        # --- End of Retry Loop ---
        # If we exit the loop normally, it means max retries were exhausted for a transient error
        logger.error(
            f"[{self.consumer_name}] Exhausted all {self.max_retries + 1} retries sending to Slack {recipient}. "
            f"Last error: {last_exception}"
        )
        # Push to DLQ for final failure after exhausting retries
        self._push_to_dlq(
            task_data, last_exception or TransientError("Max retries reached")
        )
        # Return True because the consumer has handled this task (by failing after retries).
        # It should be removed from the queue.
        return True
