# src/consumer/consumers/slack_updater.py
# -*- coding: utf-8 -*-

"""Consumer implementation for updating existing Slack messages using chat.update."""

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
        "slack_sdk not found. SlackMessageUpdaterConsumer disabled."
    )

    class WebClient:
        pass

    class SlackApiError(Exception):
        pass


# --- Local Imports ---
try:
    # Import the correct list-based BaseConsumer
    from ..base.consumer import BaseConsumer

    # Import custom exceptions
    from ..base.exceptions import TransientError, UnrecoverableError

    # Import the registry decorator
    from ..registry import register_consumer

    # Import settings
    from utils.settings import SLACK_BOT_TOKEN

    # Import config error for init issues
    from broker.redis_manager import RedisConfigurationError
except ImportError as e:
    logging.getLogger(__name__).critical(
        f"Failed imports for SlackMessageUpdaterConsumer: {e}"
    )
    raise

logger = logging.getLogger(__name__)  # consumer.consumers.slack_updater


@register_consumer("SlackMessageUpdater")  # Name used in consumer_config.yaml
class SlackMessageUpdaterConsumer(BaseConsumer):
    """
    Listens on a Redis List for tasks and updates existing Slack messages
    using the `chat.update` API. Includes internal retries.
    Expected task JSON: {"channel": "C...", "ts": "...", "payload": {"text": ..., "blocks": ...}}
    """

    MAX_SEND_RETRIES = 1  # Updates might be less critical to retry, maybe only 1 retry (total 2 attempts)
    RETRY_DELAY_SECONDS = 5.0  # Slightly longer delay for updates?

    def __init__(
        self,
        listen_key: str,
        consumer_name: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        """Initializes SlackMessageUpdaterConsumer and Slack WebClient."""
        super().__init__(
            listen_key=listen_key,
            consumer_name=consumer_name,
            settings=settings,
            **kwargs,
        )
        if not SLACK_BOT_TOKEN:
            raise RedisConfigurationError(
                f"[{self.consumer_name}] SLACK_BOT_TOKEN missing."
            )
        try:
            # Ensure SDK loaded
            if WebClient.__module__ == __name__:
                raise ImportError("slack_sdk missing")
            self.slack_client = WebClient(token=SLACK_BOT_TOKEN)
            logger.info(
                f"[{self.consumer_name}] Slack WebClient initialized for updating."
            )
        except ImportError as e:
            raise RedisConfigurationError(f"[{self.consumer_name}] {e}") from e
        except Exception as e:
            raise RedisConfigurationError(
                f"[{self.consumer_name}] Failed Slack init: {e}"
            ) from e
        self._apply_retry_settings()

    def _apply_retry_settings(self):
        """Applies retry settings."""
        if self.settings:
            try:
                self.max_retries = int(
                    self.settings.get("max_send_retries", self.MAX_SEND_RETRIES)
                )
                self.retry_delay = float(
                    self.settings.get("retry_delay_seconds", self.RETRY_DELAY_SECONDS)
                )
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
                    f"[{self.consumer_name}] Invalid retry settings: {e}. Using defaults."
                )
                self.max_retries = self.MAX_SEND_RETRIES
                self.retry_delay = self.RETRY_DELAY_SECONDS
        else:
            self.max_retries = self.MAX_SEND_RETRIES
            self.retry_delay = self.RETRY_DELAY_SECONDS
        logger.info(
            f"[{self.consumer_name}] Retry policy: Max={self.max_retries}, Delay={self.retry_delay}s"
        )

    def process_task(self, task_data: str) -> bool:
        """Parse task JSON, update Slack message with retries."""
        logger.debug(f"[{self.consumer_name}] Processing Slack update task...")
        try:
            # --- 1. Parse Task Data ---
            data = json.loads(task_data)
            channel_id = data.get("channel")
            ts = data.get("ts")  # Timestamp of the message to update
            payload = data.get("payload")  # New content {"text": ..., "blocks": ...}

            # --- Validation ---
            if not isinstance(channel_id, str) or not channel_id:
                raise ValueError("Task data must include a non-empty string 'channel'.")
            if not isinstance(ts, str) or not ts:
                raise ValueError("Task data must include a non-empty string 'ts'.")
            if not isinstance(payload, dict) or (
                "text" not in payload and "blocks" not in payload
            ):
                # chat.update requires either text or blocks (or both)
                raise ValueError(
                    "Task data must include a 'payload' object with 'text' or 'blocks'."
                )

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # Invalid format -> Unrecoverable
            logger.error(
                f"[{self.consumer_name}] Invalid Slack update task format: {e}. Data: {task_data[:500]}",
                exc_info=False,
            )
            raise UnrecoverableError(f"Invalid task format: {e}") from e

        # --- 2. Attempt Update with Retries ---
        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            if not self._running.is_set():
                return False  # Stopped during retry

            try:
                logger.info(
                    f"[{self.consumer_name}] Attempt {attempt+1} updating Slack msg {ts} in {channel_id}"
                )
                # --- Make the API Call: chat.update ---
                response = self.slack_client.chat_update(
                    channel=channel_id,
                    ts=ts,
                    text=payload.get("text"),  # Must provide text or blocks
                    blocks=payload.get("blocks")
                    # Can add other chat.update params like link_names=True etc. if needed
                )

                # --- Check Response ---
                if response and response["ok"]:
                    logger.info(
                        f"[{self.consumer_name}] Slack update successful for {ts} in {channel_id}."
                    )
                    return True  # SUCCESS - Task handled

                # --- Handle API Error in Response Body ---
                error_code = (
                    response.get("error", "api_not_ok") if response else "empty_resp"
                )
                logger.error(
                    f"[{self.consumer_name}] Slack API !OK updating msg (Attempt {attempt+1}) {ts}. Err: {error_code}"
                )
                # Classify based on common chat.update errors
                unrecoverable_update_errors = [
                    "message_not_found",
                    "cant_update_message",
                    "edit_window_closed",
                    "invalid_auth",
                    "token_revoked",
                    "missing_scope",
                    "ekm_access_denied",
                    "channel_not_found",
                    "is_archived",
                    "action_prohibited",
                    "invalid_blocks",
                    "invalid_blocks_format",
                    "metadata_too_long",
                ]
                if error_code in unrecoverable_update_errors:
                    raise UnrecoverableError(f"Slack update API error ({error_code})")
                else:  # Assume other errors might be transient
                    raise TransientError(f"Slack update API error ({error_code})")

            except SlackApiError as e:
                # --- Handle Errors Raised by SDK ---
                response_data = e.response.data if e.response else {}
                error_code = response_data.get("error", "sdk_update_error")
                status_code = e.response.status_code if e.response else -1
                logger.warning(
                    f"[{self.consumer_name}] Slack API Error updating msg (Attempt {attempt+1}, Code:{error_code}, Status:{status_code}) {ts}: {e}",
                    exc_info=False,
                )
                last_exception = e

                # Classify based on error code and status code for chat.update
                # Combine known unrecoverable codes
                unrecoverable_codes = [
                    "message_not_found",
                    "cant_update_message",
                    "edit_window_closed",
                    "invalid_auth",
                    "token_revoked",
                    "missing_scope",
                    "ekm_access_denied",
                    "channel_not_found",
                    "is_archived",
                    "action_prohibited",
                    "invalid_blocks",
                    "invalid_blocks_format",
                    "metadata_too_long",
                    "invalid_ts",  # Invalid timestamp format
                ]
                if error_code in unrecoverable_codes or status_code in [400, 403, 404]:
                    # These indicate the update cannot succeed with the given parameters/context
                    raise UnrecoverableError(
                        f"Unrecoverable Slack update API error ({error_code}): {e}"
                    ) from e
                elif (
                    attempt >= self.max_retries
                ):  # Max retries reached for transient errors
                    break  # Exit retry loop
                else:  # Transient error (e.g., 429 rate_limited, 5xx server_error)
                    logger.info(
                        f"[{self.consumer_name}] Transient error updating Slack msg {ts}. Waiting {self.retry_delay:.1f}s..."
                    )
                    self._running.wait(timeout=self.retry_delay)

            except ConnectionError as e:  # Network errors -> Transient
                logger.warning(
                    f"[{self.consumer_name}] Network Error updating msg (Attempt {attempt+1}) {ts}: {e}",
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

            except UnrecoverableError:  # Raised explicitly above
                logger.error(
                    f"[{self.consumer_name}] Unrecoverable error updating Slack msg {ts}",
                    exc_info=True,
                )
                self._push_to_dlq(
                    task_data,
                    last_exception or UnrecoverableError("Explicit unrecoverable"),
                )
                return True  # Handled by failing unrecoverably

            except Exception as e:  # Other unexpected errors
                logger.exception(
                    f"[{self.consumer_name}] Unexpected Error updating msg (Attempt {attempt+1}) {ts}."
                )
                last_exception = e
                if attempt >= self.max_retries:
                    break
                else:
                    logger.info(
                        f"[{self.consumer_name}] Waiting {self.retry_delay:.1f}s after unexpected error..."
                    )
                    self._running.wait(timeout=self.retry_delay)

        # --- Loop Finished (Max Retries Reached) ---
        logger.error(
            f"[{self.consumer_name}] Exhausted all {self.max_retries + 1} retries updating Slack msg {ts}. Last error: {last_exception}"
        )
        self._push_to_dlq(
            task_data,
            last_exception or TransientError("Max retries reached for update"),
        )
        # Return True as task is handled (by failing after retries)
        return True
