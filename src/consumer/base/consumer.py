# src/consumer/base/consumer.py
# -*- coding: utf-8 -*-

"""
Base class for consumers that process tasks from a Redis List using BRPOP.
Includes decoding for raw bytes data retrieved assuming decode_responses=False.
"""

import abc
import logging
import socket
import os
import threading
import time
import json
from typing import Dict, Any, List, Optional, Union, Tuple, Type, TypeVar

# --- Dependencies ---
try:
    from redis import Redis
    from redis.exceptions import (
        RedisError,
        WatchError,
        ConnectionError as RedisConnectionError,
        AuthenticationError as RedisAuthenticationError,
    )
except ImportError:
    raise ImportError(
        "The 'redis' package is required by BaseConsumer. Please install it using 'poetry add redis'"
    )

# --- Local Imports ---
try:
    from broker.redis_manager import (
        RedisManager,
        get_redis_manager,
        RedisOperationError,
        RedisConfigurationError,
    )

    # Corrected relative path to exceptions within the same 'base' package? No, exceptions are one level up.
    from ..exceptions import (
        ConsumerError,
        UnrecoverableError,
        TransientError,
    )  # Correct relative path assumed
except ImportError as e:
    # Use logging if available, otherwise print
    _logger = logging.getLogger(__name__)
    if not _logger.hasHandlers():
        logging.basicConfig()  # Basic setup if needed early
    _logger.critical(f"Failed to import BaseConsumer dependencies: {e}", exc_info=True)
    raise ImportError(
        f"Missing required project dependencies for BaseConsumer: {e}"
    ) from e

logger = logging.getLogger(__name__)  # consumer.base.consumer


class BaseConsumer(abc.ABC):
    """
    Abstract Base Class for consumers processing tasks from Redis Lists using BRPOP.

    Handles the core loop, thread management, Redis connection via RedisManager,
    decoding of task data (assuming UTF-8), delegation via `process_task`,
    and graceful shutdown. Subclasses implement `process_task` for specific logic,
    error handling (retries/requeue), and optional DLQ pushing.
    Assumes Redis client uses decode_responses=False.
    """

    DEFAULT_BRPOP_TIMEOUT: int = 5
    DEFAULT_ERROR_PAUSE_SECONDS: float = 1.0
    DEFAULT_MAX_REDIS_ERROR_STREAK: int = 5

    def __init__(
        self,
        listen_key: str,
        consumer_name: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        redis_manager: Optional[RedisManager] = None,
        brpop_timeout: int = DEFAULT_BRPOP_TIMEOUT,
        **kwargs,  # Absorb potential extra args like template_class
    ):
        if not listen_key or not isinstance(listen_key, str):
            raise RedisConfigurationError(
                f"{self.__class__.__name__} requires 'listen_key'."
            )

        self.listen_key: str = listen_key
        self.settings: Dict[str, Any] = settings if settings is not None else {}
        self.consumer_name: str = consumer_name or self._generate_consumer_name()
        try:
            self.brpop_timeout: int = int(brpop_timeout)
            if self.brpop_timeout < 0:
                raise ValueError(">= 0")
        except (ValueError, TypeError) as e:
            raise RedisConfigurationError(f"Invalid 'brpop_timeout': {e}")

        self.redis_manager = redis_manager
        if not self.redis_manager:
            try:
                self.redis_manager = get_redis_manager()
            except RedisConfigurationError as e:
                raise e
            except Exception as e:
                raise RedisConfigurationError(f"Failed to get RedisManager: {e}") from e
        elif not isinstance(self.redis_manager, RedisManager):
            raise RedisConfigurationError("Provided redis_manager is not valid.")

        # --- REMOVED THE INCORRECT CHECK FOR decode_responses ---
        # The check `if self.redis_manager.redis and self.redis_manager.redis.decode_responses:` was here and caused AttributeError.

        self._running = threading.Event()
        self._running.set()
        self._thread: Optional[threading.Thread] = None

        logger.info(
            f"[{self.consumer_name}] Initialized. Listening Key='{self.listen_key}', "
            f"BRPOP Timeout={self.brpop_timeout}s, Settings={self.settings}"
        )

    def _generate_consumer_name(self) -> str:
        hostname = socket.gethostname()
        pid = os.getpid()
        tid = threading.get_ident()
        safe_key = "".join(
            c if c.isalnum() or c in ("-", "_", ":") else "_" for c in self.listen_key
        )
        return f"{hostname}-{pid}-{tid}-{safe_key}"

    @abc.abstractmethod
    def process_task(self, task_data: str) -> bool:
        """
        Process a single task string. Subclass implements actual work.

        Args:
            task_data (str): The decoded task data string from the Redis List.

        Returns:
            bool: True if handled (success/unrecoverable), False if transient failure.
        """
        raise NotImplementedError

    def run(self):
        """Main loop using BRPOP, includes task data decoding."""
        if not self._running.is_set():
            return
        logger.info(
            f"[{self.consumer_name}] Starting task processing loop on '{self.listen_key}'..."
        )
        redis_error_streak = 0
        max_redis_error_streak = self.settings.get(
            "max_redis_error_streak", self.DEFAULT_MAX_REDIS_ERROR_STREAK
        )

        while self._running.is_set():
            task_tuple_bytes: Optional[Tuple[bytes, bytes]] = None  # Expect bytes now
            task_data_bytes: Optional[bytes] = None
            task_data_str: Optional[str] = None
            is_task_handled: bool = False

            try:
                # --- Wait for Task (expecting bytes) ---
                task_tuple_bytes = self.redis_manager.brpop(
                    self.listen_key, timeout=self.brpop_timeout
                )  # Should return bytes tuple

                if task_tuple_bytes:
                    # --- Task Received ---
                    redis_error_streak = 0
                    _list_key_bytes, task_data_bytes = task_tuple_bytes
                    _list_key_str = _list_key_bytes.decode(
                        "utf-8", errors="ignore"
                    )  # Key is usually safe
                    logger.info(
                        f"[{self.consumer_name}] Received task from '{_list_key_str}'."
                    )

                    # --- Decode Task Data ---
                    try:
                        task_data_str = task_data_bytes.decode(
                            "utf-8"
                        )  # Decode assuming UTF-8
                    except UnicodeDecodeError as decode_err:
                        # Handle decoding failure -> Unrecoverable
                        logger.error(
                            f"[{self.consumer_name}] Unrecoverable Error: Failed to decode task data as UTF-8. Discarding. Error: {decode_err}. Raw head: {task_data_bytes[:100]}",
                            exc_info=False,
                        )
                        # Pass original bytes (lossily decoded) to DLQ if enabled
                        self._push_to_dlq(
                            task_data_bytes.decode("latin-1", errors="replace"),
                            decode_err,
                        )
                        is_task_handled = True  # Handled by discarding
                        continue  # Skip processing, go to next loop iteration

                    # --- Process Decoded Task ---
                    if (
                        task_data_str is not None
                    ):  # Should be true if decode didn't fail
                        try:
                            # Pass the *decoded string* to the subclass implementation
                            is_task_handled = self.process_task(task_data_str)

                            if is_task_handled:
                                logger.debug(
                                    f"[{self.consumer_name}] Task handled by process_task."
                                )
                            else:
                                logger.warning(
                                    f"[{self.consumer_name}] process_task indicated transient failure."
                                )
                                time.sleep(self.DEFAULT_ERROR_PAUSE_SECONDS)

                        except UnrecoverableError as ue:
                            logger.error(
                                f"[{self.consumer_name}] Unrecoverable error processing task: {ue}. Discarding.",
                                exc_info=False,
                            )
                            self._push_to_dlq(
                                task_data_str, ue
                            )  # Push decoded data to DLQ
                            is_task_handled = True  # Handled by discarding
                        except Exception as process_err:
                            logger.exception(
                                f"[{self.consumer_name}] Unexpected error during process_task."
                            )
                            is_task_handled = False  # Not handled successfully
                            # Push to DLQ on unexpected errors too? Pass decoded data.
                            self._push_to_dlq(task_data_str, process_err)
                            time.sleep(self.DEFAULT_ERROR_PAUSE_SECONDS * 2)

                else:  # BRPOP timeout
                    # logger.debug(f"[{self.consumer_name}] BRPOP timed out.") # Can be verbose
                    redis_error_streak = 0

            except RedisOperationError as e:
                # Error *during* the BRPOP call
                redis_error_streak += 1
                logger.error(
                    f"[{self.consumer_name}] Redis error during BRPOP: {e}. Streak: {redis_error_streak}",
                    exc_info=True,
                )
                if redis_error_streak >= max_redis_error_streak:
                    pause_duration = min(
                        30, 1 * (2 ** (redis_error_streak - max_redis_error_streak))
                    )
                    logger.warning(
                        f"[{self.consumer_name}] Pausing for {pause_duration:.1f}s."
                    )
                    self._running.wait(timeout=pause_duration)
                else:
                    self._running.wait(timeout=1.0)
            except Exception as loop_err:
                # Catch other errors in the loop
                logger.critical(
                    f"[{self.consumer_name}] CRITICAL error in main run loop: {loop_err}",
                    exc_info=True,
                )
                self._running.wait(timeout=5.0)

        logger.info(
            f"[{self.consumer_name}] Task processing loop stopped for '{self.listen_key}'."
        )

    def start(self):
        # (Implementation remains the same)
        if self._thread and self._thread.is_alive():
            logger.warning(
                f"[{self.consumer_name}] Start called, but worker thread exists."
            )
            return
        if not self._running.is_set():
            logger.info(f"[{self.consumer_name}] Restarting consumer...")
            self._running.set()
        self._thread = threading.Thread(
            target=self.run, name=self.consumer_name, daemon=True
        )
        self._thread.start()
        logger.info(
            f"[{self.consumer_name}] Worker thread started (ID: {self._thread.ident})."
        )

    def stop(self, timeout: Optional[float] = 10.0):
        # (Implementation remains the same)
        thread_id = self._thread.ident if self._thread else "N/A"
        if not self._running.is_set():
            logger.info(
                f"[{self.consumer_name}] Stop called, but already stopped (TID: {thread_id})."
            )
            return
        logger.info(
            f"[{self.consumer_name}] Stop requested. Signaling loop (TID: {thread_id})..."
        )
        self._running.clear()
        if (
            self._thread
            and self._thread.is_alive()
            and threading.current_thread() != self._thread
        ):
            logger.info(
                f"[{self.consumer_name}] Waiting up to {timeout}s for thread {thread_id}..."
            )
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    f"[{self.consumer_name}] Thread {thread_id} did not stop within timeout."
                )
            else:
                logger.info(f"[{self.consumer_name}] Thread {thread_id} finished.")
                self._thread = None
        elif self._thread is None:
            logger.info(f"[{self.consumer_name}] No active thread to join.")
        elif threading.current_thread() == self._thread:
            logger.debug(f"[{self.consumer_name}] Stop called from worker thread.")

    # Optional DLQ method adjusted for clarity and receiving string data
    def _push_to_dlq(self, failed_task_data: str, error: Exception):
        """Pushes failed task data (as string) to a configured Dead Letter Queue List."""
        if not self.settings.get("dlq_enabled", False):
            return
        dlq_key = self.settings.get("dlq_key", f"dlq:{self.listen_key}")
        logger.warning(
            f"[{self.consumer_name}] Pushing failed task to DLQ '{dlq_key}'. Error: {type(error).__name__}"
        )
        try:
            dlq_entry_dict = {
                "ts": time.time(),
                "consumer": self.consumer_name,
                "key": self.listen_key,
                "error": f"{type(error).__name__}: {str(error)}",
                "data": failed_task_data,  # Use the string data passed in
            }
            dlq_entry_json = json.dumps(dlq_entry_dict, default=str)
            result = self.redis_manager.lpush(dlq_key, [dlq_entry_json])
            if result is None:
                logger.error(
                    f"[{self.consumer_name}] RedisManager.lpush failed sending to DLQ '{dlq_key}'."
                )
        except Exception as e:
            logger.error(
                f"[{self.consumer_name}] Failed to push to DLQ '{dlq_key}': {e}",
                exc_info=True,
            )
