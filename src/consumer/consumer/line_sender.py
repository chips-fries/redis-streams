# src/consumer/consumers/line_sender.py
# -*- coding: utf-8 -*-

"""Consumer implementation for sending messages via Line Push API."""

import logging
import json
import pickle
from typing import Dict, Any, Optional, List

# --- SDK Imports ---
try:
    # Import necessary V3 components
    from linebot.v3.messaging import (
        Configuration as LineConfiguration,
        ApiClient as LineApiClient,
        MessagingApi as LineMessagingApi,
        PushMessageRequest as LinePushMessageRequest,
        ApiException as LineApiException,
        Message as LineMessage,
        TextMessage as LineTextMessage,
        # --- CORRECTED IMPORT ---
        FlexMessage,  # Use FlexMessage directly
        # --- END CORRECTION ---
        QuickReply,  # Keep QuickReply if used
    )

    # Helper for parsing if needed (may not exist or work easily for complex types)
    # from linebot.v3.messaging.models.base_model import Model as LineBaseModel
except ImportError:
    logging.getLogger(__name__).warning(
        "line-bot-sdk not found. LinePushMessageConsumer disabled."
    )
    # Define dummies to allow file parsing
    class LineConfiguration:
        pass

    class LineApiClient:
        pass

    class LineMessagingApi:
        pass

    class LinePushMessageRequest:
        pass

    class LineApiException(Exception):
        pass

    class LineMessage:
        pass

    class LineTextMessage(LineMessage):
        pass

    class FlexMessage(LineMessage):
        pass


# --- Local Imports ---
try:
    from ..base.consumer import BaseConsumer
    from ..base.exceptions import TransientError, UnrecoverableError
    from ..registry import register_consumer
    from utils.settings import LINE_CHANNEL_ACCESS_TOKEN
    from broker.redis_manager import RedisConfigurationError
except ImportError as e:
    logging.getLogger(__name__).critical(
        f"Failed imports for LinePushMessageConsumer: {e}"
    )
    raise

logger = logging.getLogger(__name__)  # consumer.consumers.line_sender


@register_consumer("LinePushMessageSender")  # Use a clear name
class LinePushMessageConsumer(BaseConsumer):
    """
    Listens on a Redis List and sends messages via Line Push API.
    Expected task JSON string: {"recipient": "U...", "payload_json": "[{...message object dict...}, ...]"}
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
        """Initializes LinePushMessageConsumer and Line MessagingApi client."""
        super().__init__(
            listen_key=listen_key,
            consumer_name=consumer_name,
            settings=settings,
            **kwargs,
        )

        if not LINE_CHANNEL_ACCESS_TOKEN:
            raise RedisConfigurationError(
                f"[{self.consumer_name}] LINE_CHANNEL_ACCESS_TOKEN missing."
            )
        try:
            # Check for dummy SDK classes
            if LineConfiguration.__module__ == __name__:
                raise ImportError("line-bot-sdk missing or not installed properly.")
            self.line_config = LineConfiguration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
            # Consider adding timeout configuration for the API client
            # self.line_config.timeout = {'connect': 5, 'read': 10}
            self.line_api_client = LineApiClient(self.line_config)
            self.messaging_api = LineMessagingApi(self.line_api_client)
            logger.info(f"[{self.consumer_name}] Line MessagingApi client initialized.")
        except ImportError as e:
            raise RedisConfigurationError(f"[{self.consumer_name}] {e}") from e
        except Exception as e:
            raise RedisConfigurationError(
                f"[{self.consumer_name}] Failed Line init: {e}"
            ) from e
        self._apply_retry_settings()

    def _apply_retry_settings(self):
        """Applies retry settings from config or uses defaults."""
        # (Same logic as Slack sender)
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

    # --- Task Processing ---
    # def _parse_line_message_objects(self, payload_list_json: str) -> List[LineMessage]:
    #     """
    #     Parses the payload_list_json string into a list of Line Bot SDK Message objects
    #     using the SDK's Message.new_from_json_dict factory method.
    #     """
    #     if LineMessage.__module__ == __name__:
    #         raise ImportError("line-bot-sdk missing, cannot parse messages.")

    #     sdk_messages: List[LineMessage] = []
    #     try:
    #         # 1. Load the JSON string into a list of Python dictionaries
    #         message_dicts: List[Dict[str, Any]] = json.loads(payload_list_json)
    #         logger.info(f"payload_list loaded from JSON: {message_dicts}") # Log parsed list

    #         if not isinstance(message_dicts, list):
    #              raise ValueError("Payload is not a list of message dictionaries.")

    #         # 2. Iterate and convert each dictionary using Message.new_from_json_dict
    #         for i, msg_dict in enumerate(message_dicts):
    #             if not isinstance(msg_dict, dict):
    #                  logger.warning(f"Item at index {i} is not a dictionary, skipping.")
    #                  continue # Skip non-dict items

    #             logger.info(f"Attempting to parse msg_dict at index {i}: {msg_dict}")
    #             try:
    #                 # --- Use the SDK Factory Method ---
    #                 sdk_message = LineMessage.new_from_json_dict(msg_dict)
    #                 # ----------------------------------

    #                 if sdk_message is None:
    #                     # new_from_json_dict might return None if type is missing or unknown
    #                     logger.warning(f"Message.new_from_json_dict returned None for dict at index {i}. Dict: {msg_dict}")
    #                     continue # Skip if conversion results in None

    #                 # Optional: Log the type of the created object for confirmation
    #                 logger.info(f"Successfully parsed dict at index {i} into SDK object of type: {type(sdk_message)}")
    #                 # logger.debug(f"Parsed SDK object (repr): {repr(sdk_message)}") # Log repr if needed

    #                 sdk_messages.append(sdk_message)

    #             except Exception as conversion_e:
    #                 # If new_from_json_dict fails, the dict structure is likely invalid for the SDK
    #                 logger.error(f"Failed to convert message dictionary at index {i} via Message.new_from_json_dict: {conversion_e}", exc_info=True)
    #                 logger.debug(f"Invalid dictionary content: {msg_dict}")
    #                 # Re-raise a more informative error
    #                 raise ValueError(f"Invalid message structure at index {i} for SDK conversion using new_from_json_dict: {conversion_e}") from conversion_e

    #         # Final check if any messages were successfully parsed
    #         if not sdk_messages:
    #             raise ValueError("Payload list was empty or resulted in no valid SDK message objects after parsing.")

    #         # Truncate if necessary (Line allows up to 5 messages per push)
    #         if len(sdk_messages) > 5:
    #             logger.warning(f"[{self.consumer_name}] Too many messages ({len(sdk_messages)}), truncating to first 5.")
    #             sdk_messages = sdk_messages[:5]

    #         return sdk_messages

    #     except json.JSONDecodeError as json_e:
    #         logger.error(f"Failed to decode payload_json string: {json_e}", exc_info=True)
    #         raise ValueError(f"Invalid JSON in payload_json: {json_e}") from json_e
    #     except ValueError as val_e: # Catch ValueErrors raised within this function or by new_from_json_dict
    #         logger.error(f"Error parsing message objects: {val_e}", exc_info=True) # Log traceback for ValueErrors too
    #         raise # Re-raise the ValueError
    #     except Exception as e: # Catch any other unexpected errors
    #         logger.error(f"Unexpected error during message object parsing: {e}", exc_info=True)
    #         raise ValueError(f"Unexpected parsing error: {e}") from e

    # --- process_task method remains largely the same ---
    # It should call the revised _parse_line_message_objects above
    def process_task(self, task_data_str: str) -> bool:
        # ... (Keep the initial part: load task_data, get recipient, payload_list_json, reminder_id) ...
        logger.debug(f"[{self.consumer_name}] Processing Line push task...")
        parsed_sdk_objects: List[LineMessage] = []  # Store parsed SDK objects

        try:
            # --- 1. Parse Outer Task Data ---
            data = json.loads(task_data_str)
            recipient = data.get("recipient")
            payload_pickle_hex = data.get("payload_pickle")
            reminder_id = data.get("reminder_id", "N/A")

            # Basic validation of required fields
            if not isinstance(recipient, str) or not recipient:
                raise ValueError("'recipient' missing or invalid.")

            logger.info(
                f"Processing Line task for recipient {recipient}. RemID: {reminder_id}."
            )

            if isinstance(payload_pickle_hex, str) and payload_pickle_hex:
                try:
                    logger.info(
                        f"Using pickle-based Line payload (hex) for RemID: {reminder_id}."
                    )
                    parsed_sdk_objects = pickle.loads(bytes.fromhex(payload_pickle_hex))
                    if not isinstance(parsed_sdk_objects, list):
                        raise ValueError(
                            "Unpickled payload is not a list of Line SDK messages."
                        )
                except Exception as e:
                    logger.error(f"Failed to decode pickle payload: {e}", exc_info=True)
                    raise ValueError(f"Invalid pickle payload for Line: {e}") from e

        except (json.JSONDecodeError, ValueError) as e:
            # Errors during initial task parsing or SDK object parsing
            logger.error(
                f"[{self.consumer_name}] Invalid Line task format or payload parsing failed: {e}. Raw Task: {task_data_str[:500]}",
                exc_info=True,
            )  # Log traceback
            # Push to DLQ - Remember to fix the metadata argument issue
            # self._push_to_dlq(task_data_str, e, ...)
            raise UnrecoverableError(
                f"Invalid task format or payload parsing: {e}"
            ) from e
        except Exception as e:  # Catch unexpected errors during parsing phase
            logger.error(
                f"[{self.consumer_name}] Unexpected error during task parsing: {e}",
                exc_info=True,
            )
            raise UnrecoverableError(f"Unexpected task parsing error: {e}") from e

        logger.info(f"Parsed SDK Objects: {parsed_sdk_objects}")

        # --- 3. Attempt Sending with Retries ---
        last_exception = None
        for attempt in range(self.max_retries + 1):
            if not self._running.is_set():
                return False  # Check if consumer should stop
            try:
                log_prefix = f"[{self.consumer_name}] Attempt {attempt + 1}/{self.max_retries + 1}"
                logger.info(
                    f"{log_prefix} sending {len(parsed_sdk_objects)} message object(s) to Line {recipient} (RemID: {reminder_id})."
                )

                # Use the PARSED SDK OBJECTS list directly
                push_request = LinePushMessageRequest(
                    to=recipient,
                    messages=parsed_sdk_objects,  # Pass the list of SDK objects
                )

                # Log the request object if needed (might be large)
                # logger.debug(f"Push Request Object: {push_request}")

                # --- API Call ---
                api_response = self.messaging_api.push_message(
                    push_request
                )  # Adjust timeout if needed

                logger.info(
                    f"{log_prefix} SUCCESS sending to Line {recipient} (RemID: {reminder_id})."
                )
                return True  # Task successful

            except LineApiException as e:
                status_code = e.status
                error_body = e.body
                logger.warning(
                    f"{log_prefix} FAILED sending to Line {recipient}. LineBotApiError (Status:{status_code}): {error_body}",
                    exc_info=(status_code >= 500),
                )  # Log stack trace for server errors
                last_exception = e
                unrecoverable_status = [
                    400,
                    401,
                    403,
                ]  # Bad Request, Unauthorized, Forbidden are usually unrecoverable
                if status_code in unrecoverable_status:
                    logger.critical(
                        f"[{self.consumer_name}] Unrecoverable Line API Error {status_code}. Body: {error_body}"
                    )
                    # Push to DLQ if needed
                    # self._push_to_dlq(...)
                    raise UnrecoverableError(
                        f"Unrecoverable Line API error ({status_code}): {error_body}"
                    ) from e
                elif attempt >= self.max_retries:
                    logger.error(
                        f"[{self.consumer_name}] Max retries reached for Line {recipient}. Last error status: {status_code}"
                    )
                    break  # Exit retry loop
                else:
                    logger.info(
                        f"[{self.consumer_name}] Retrying after delay ({self.retry_delay}s) for Line {recipient}. Status: {status_code}"
                    )
                    self._running.wait(timeout=self.retry_delay)  # Wait before retry

            except ConnectionError as conn_e:  # Handle network errors specifically if needed
                logger.warning(
                    f"{log_prefix} FAILED sending to Line {recipient} due to ConnectionError: {conn_e}",
                    exc_info=True,
                )
                last_exception = conn_e
                if attempt >= self.max_retries:
                    logger.error(
                        f"[{self.consumer_name}] Max retries reached after ConnectionError for Line {recipient}."
                    )
                    break
                else:
                    logger.info(
                        f"[{self.consumer_name}] Retrying after delay ({self.retry_delay}s) due to ConnectionError."
                    )
                    self._running.wait(timeout=self.retry_delay)

            except Exception as send_e:  # Catch other unexpected errors during sending
                logger.error(
                    f"{log_prefix} FAILED sending to Line {recipient} with unexpected error.",
                    exc_info=True,
                )
                last_exception = send_e
                # Treat other unexpected errors as unrecoverable immediately
                # self._push_to_dlq(...)
                raise UnrecoverableError(
                    f"Unexpected sending error: {send_e}"
                ) from send_e

        # --- End of Retry Loop (if break was hit) ---
        logger.error(
            f"[{self.consumer_name}] Exhausted retries sending to Line {recipient}. Last error: {last_exception}"
        )
        # Push to DLQ - Remember to fix metadata argument
        # self._push_to_dlq(task_data_str, last_exception or TransientError("Max retries reached"), ...)
        # Even though retries exhausted, the task was "handled" by attempting retries
        # Return True if you want the message removed from queue, False otherwise (depends on broker acks)
        # Let's raise Unrecoverable since retries failed.
        raise UnrecoverableError(
            f"Max retries reached for Line {recipient}. Last error: {last_exception}"
        ) from last_exception
