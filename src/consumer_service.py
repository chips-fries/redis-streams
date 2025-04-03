# src/consumer_service.py
# -*- coding: utf-8 -*-

"""
Main service entry point for starting and managing Redis List Consumers
based on the 'consumer_config.yaml' file (using the 'queues' structure).
Handles graceful shutdown.
"""

import sys
import os
import signal
import threading
import time
import logging
import yaml  # For catching YAML errors specifically
from typing import Dict, Type, List, Optional, Any

# --- Core Imports ---
try:
    from utils.config_loader import ConfigLoader
    import utils.logger  # Import to trigger setup
    from broker.redis_manager import (
        get_redis_manager,
        RedisManager,
        RedisConfigurationError,
    )
except ImportError as e:
    print(f"[CRITICAL] Failed to import core utilities: {e}", file=sys.stderr)
    sys.exit(1)

# --- Consumer Specific Imports ---
try:
    import consumer  # Trigger consumer/__init__.py
    from consumer import BaseConsumer, CONSUMER_REGISTRY
except ImportError as e:
    print(f"[CRITICAL] Failed to import 'consumer' package: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(
        f"[CRITICAL] Unexpected error importing consumer package: {e}", file=sys.stderr
    )
    sys.exit(1)


# --- Global Variables ---
logger = logging.getLogger(__name__)  # Get logger instance configured by utils.logger

running_consumer_instances: List[BaseConsumer] = []
shutdown_event = threading.Event()


# --- Signal Handling ---
def shutdown_gracefully(signum, frame):
    """Handles SIGINT and SIGTERM signals."""
    signal_name = signal.Signals(signum).name
    if shutdown_event.is_set():
        logger.warning(f"Signal ({signal_name}) received, already shutting down.")
        return
    logger.warning(f"Shutdown signal ({signal_name}) received. Initiating shutdown...")
    shutdown_event.set()
    logger.info(f"Stopping {len(running_consumer_instances)} consumer instance(s)...")
    for instance in list(running_consumer_instances):
        c_name = getattr(instance, "consumer_name", "UnknownConsumer")
        logger.debug(f"Requesting stop for consumer: {c_name}")
        try:
            instance.stop(timeout=15.0)
        except Exception as e:
            logger.error(f"Error stopping consumer {c_name}: {e}", exc_info=True)
    logger.info("All consumer stop sequences completed.")


# --- Main Service Logic ---
def main(config_file: str = "config/consumer_config.yaml"):
    """
    Loads config (queue structure), initializes Redis, starts consumers, waits for shutdown.
    """
    # --- 1. Logging setup triggered by import ---
    logger.info("Consumer Service starting up...")
    logger.info(f"Loading configuration from: {config_file}")

    # --- 2. Register Signal Handlers ---
    try:
        signal.signal(signal.SIGINT, shutdown_gracefully)
        signal.signal(signal.SIGTERM, shutdown_gracefully)
        logger.debug("Signal handlers registered.")
    except ValueError as e:
        logger.warning(f"Could not set signal handlers: {e}.")

    # --- 3. Load Configuration ---
    service_config = None
    queues_config = None  # Changed from stream_groups_config
    try:
        loader = ConfigLoader(config_file)
        service_config = loader.config.get("consumer")
        if not service_config or not isinstance(service_config, dict):
            raise ValueError(f"Missing or invalid 'consumer' key in '{config_file}'.")
        # --- MODIFIED: Read 'queues' key ---
        queues_config = service_config.get("queues")
        if not queues_config or not isinstance(queues_config, dict):
            raise ValueError(f"Missing or invalid 'queues' section in '{config_file}'.")
        logger.info("Configuration loaded successfully.")
        logger.debug(
            f"Available consumers in registry: {list(CONSUMER_REGISTRY.keys())}"
        )

    except FileNotFoundError as e:
        logger.critical(
            f"Config file not found: {config_file}. Error: {e}", exc_info=False
        )
        sys.exit(1)
    except (yaml.YAMLError, TypeError, ValueError) as e:
        logger.critical(
            f"Failed to load/parse config '{config_file}': {e}", exc_info=True
        )
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unexpected error loading config: {e}", exc_info=True)
        sys.exit(1)

    # --- 4. Initialize Redis ---
    redis_manager: Optional[RedisManager] = None
    try:
        redis_manager = get_redis_manager()
        if (
            not redis_manager
            or not redis_manager.redis
            or not redis_manager.redis.ping()
        ):
            raise RedisConfigurationError("Initial Redis ping failed via manager.")
        logger.info("Redis connection verified.")
    except RedisConfigurationError as e:
        logger.critical(f"Failed to initialize Redis: {e}. Aborting.", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.critical(
            f"Unexpected error getting Redis manager: {e}. Aborting.", exc_info=True
        )
        sys.exit(1)
    if not redis_manager:
        logger.critical("RedisManager init failed silently.")
        sys.exit(1)  # Should not happen

    # --- 5. Instantiate and Start Consumers ---
    logger.info("Initializing and starting configured list consumers...")
    successful_starts = 0
    total_configured = 0

    # --- MODIFIED: Iterate through queues config ---
    # Outer loop iterates through queue names (which are the listen_keys)
    for listen_key, queue_data in queues_config.items():
        if shutdown_event.is_set():
            break  # Allow interruption

        if not isinstance(queue_data, dict):
            logger.warning(
                f"Skipping invalid queue config for key '{listen_key}': not a dictionary."
            )
            continue

        # Get the 'workers' dictionary for this queue
        workers_config = queue_data.get("workers", {})
        if not isinstance(workers_config, dict):
            logger.warning(
                f"Skipping invalid 'workers' section under queue '{listen_key}'."
            )
            continue
        if not workers_config:
            logger.info(f"No workers configured for queue '{listen_key}'.")
            continue

        # Inner loop iterates through worker instances defined for this specific queue
        for instance_name, worker_config in workers_config.items():
            if shutdown_event.is_set():
                break
            total_configured += 1
            logger.debug(
                f"Processing config for worker '{instance_name}' on queue '{listen_key}'"
            )

            # --- Validate Worker Config ---
            if not isinstance(worker_config, dict):
                logger.error(
                    f"Skipping '{instance_name}' on '{listen_key}': Invalid config (not dict)."
                )
                continue
            consumer_type = worker_config.get("type")
            settings = worker_config.get("settings")  # Optional settings dict
            brpop_timeout_cfg = worker_config.get(
                "brpop_timeout"
            )  # Optional timeout override per worker

            # Validate type
            if not consumer_type or not isinstance(consumer_type, str):
                logger.error(
                    f"Skipping '{instance_name}' on '{listen_key}': Invalid 'type'."
                )
                continue
            # Validate settings
            if settings and not isinstance(settings, dict):
                logger.error(
                    f"Skipping '{instance_name}' on '{listen_key}': Invalid 'settings'."
                )
                continue

            # --- Determine BRPOP Timeout ---
            brpop_timeout = BaseConsumer.DEFAULT_BRPOP_TIMEOUT  # Start with default
            if brpop_timeout_cfg is not None:
                try:
                    brpop_timeout = int(brpop_timeout_cfg)
                    if brpop_timeout < 0:
                        raise ValueError(">= 0")
                    if brpop_timeout == 0:
                        logger.warning(
                            f"Worker '{instance_name}' on '{listen_key}' configured with brpop_timeout=0. Graceful shutdown might delay."
                        )
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid brpop_timeout '{brpop_timeout_cfg}' for '{instance_name}', using default {BaseConsumer.DEFAULT_BRPOP_TIMEOUT}s."
                    )
                    brpop_timeout = BaseConsumer.DEFAULT_BRPOP_TIMEOUT

            # --- Find Class and Instantiate ---
            ConsumerClass = CONSUMER_REGISTRY.get(consumer_type)
            if not ConsumerClass:
                logger.error(
                    f"Skipping '{instance_name}' on '{listen_key}': Type '{consumer_type}' not found. Available: {list(CONSUMER_REGISTRY.keys())}"
                )
                continue

            try:
                # Instantiate the specific consumer class
                # Pass listen_key obtained from the outer loop key
                instance = ConsumerClass(
                    listen_key=listen_key,
                    # Let BaseConsumer generate detailed name: consumer_name=f"{instance_name}-{listen_key}-{os.getpid()}",
                    settings=settings or {},
                    redis_manager=redis_manager,
                    brpop_timeout=brpop_timeout,
                )
                instance.start()  # Start background thread
                running_consumer_instances.append(instance)
                successful_starts += 1
                # Log the actual generated name from the instance
                logger.info(
                    f"Successfully started consumer '{instance.consumer_name}' on queue '{listen_key}'."
                )

            except RedisConfigurationError as e:
                logger.error(
                    f"Configuration error starting '{instance_name}' ({consumer_type}) on '{listen_key}': {e}",
                    exc_info=False,
                )
            except Exception as e:
                logger.error(
                    f"Failed to start consumer '{instance_name}' ({consumer_type}) on '{listen_key}': {e}",
                    exc_info=True,
                )

        if shutdown_event.is_set():
            break  # Exit outer loop too

    # --- Post-Startup Summary ---
    # (Same logic as before)
    if shutdown_event.is_set():
        logger.warning("Startup interrupted by shutdown signal.")
    elif successful_starts == 0 and total_configured > 0:
        logger.critical(
            f"No consumers started out of {total_configured} configured. Exiting."
        )
        sys.exit(1)
    elif successful_starts == 0 and total_configured == 0:
        logger.warning("No consumers configured. Service idle.")
    else:
        logger.info(
            f"Started {successful_starts}/{total_configured} consumer(s). Service operational."
        )

    # --- Keep Main Thread Alive ---
    logger.info(
        "Consumer service running. Waiting for shutdown signal (SIGINT/SIGTERM)..."
    )
    while not shutdown_event.is_set():
        try:
            shutdown_event.wait(timeout=60.0)  # Wait efficiently
        except KeyboardInterrupt:
            logger.warning("KeyboardInterrupt caught. Initiating shutdown...")
            if not shutdown_event.is_set():
                shutdown_gracefully(signal.SIGINT, None)
        except Exception as e:
            logger.error(f"Error in main wait loop: {e}", exc_info=True)
            time.sleep(5)

    # --- Final Exit ---
    logger.info("Consumer Service main thread exiting gracefully.")
    time.sleep(0.5)
    sys.exit(0)


# --- Script Entry Point ---
if __name__ == "__main__":
    # Optional: Add argparse for config path override
    main()
