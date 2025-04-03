# src/orch/flows/reminder_flow.py
# -*- coding: utf-8 -*-

"""
Prefect Flow definition for sending Reminder messages based on targets.
Triggers tasks to publish initial reminders. (Follow-up logic is in tasks/later flows)
"""
import os
import logging
import uuid  # For generating unique reminder IDs
from typing import Dict, Any, List, Optional
import asyncio  # Import asyncio for potential concurrent operations
from concurrent.futures import TimeoutError  # Import TimeoutError for result timeout

# --- Prefect Imports ---
try:
    from prefect import flow, get_run_logger
    from prefect.futures import PrefectFuture  # Import for type hinting
except ImportError:
    print("Error: 'prefect' package not found.")
    raise

# --- Local Imports ---
try:
    # Import the CORRECT reminder task
    from _orch.tasks.reminder_sending_tasks import build_and_publish_reminder_task

    # Import targeting functions and ENV
    from _orch.utils.targeting import get_destination_id, resolve_mention_aliases, ENV
except ImportError as e:
    logging.getLogger(__name__).critical(
        f"Could not import required task or targeting utils: {e}", exc_info=True
    )
    raise

logger = logging.getLogger(__name__)  # Module-level logger

# --- Flow Definition (Refactored with corrected result waiting) ---


@flow(name="Send Reminder Message v2 (Multi-Target)", retries=1, retry_delay_seconds=5)
async def send_reminder_flow(
    # Parameters matching the final reminder_params.json structure
    targets: List[Dict[str, Any]],
    message_context: Optional[Dict[str, Any]] = None,
    trigger_source: str = "unknown",
):
    """
    Builds and triggers tasks to publish initial Reminder instructions based on a list of targets.
    Each task handles message building, publishing, and potentially scheduling follow-ups.
    This flow waits for all submitted tasks to complete and fails if any task fails.

    Args:
        targets (List[Dict[str, Any]]): List where each dict contains:
            - platform (str)
            - template_name (str)
            - context_data (Dict): Must include 'destination_alias', 'reminder_text'.
                                     Can include 'mention_aliases', 'interaction_mode',
                                     'follow_up_policy', etc.
        message_context (Optional[Dict[str, Any]]): Global context for all tasks.
        trigger_source (str): Identifier for what triggered this flow.
    """
    run_logger = get_run_logger()
    flow_run_id_str = f"(FlowRun: {getattr(run_logger, 'flow_run_id', 'N/A')})"
    log_prefix = f"Reminder Flow v2 {flow_run_id_str}"

    run_logger.info(
        f"{log_prefix}: Starting for {len(targets)} target(s). Trigger='{trigger_source}'. ENV='{ENV}'. Global Context: {message_context}"
    )

    if not targets or not isinstance(targets, list):
        run_logger.warning(f"{log_prefix}: No valid targets list provided. Exiting.")
        return

    success_count = 0
    failure_count = 0
    processed_target_count = 0
    tasks_submitted: List[tuple[str, str, PrefectFuture]] = []

    # --- Process each target and submit tasks ---
    for i, target in enumerate(targets):
        processed_target_count += 1
        target_log_prefix = f"{log_prefix} Target {i+1}/{len(targets)}"
        run_logger.debug(f"{target_log_prefix}: Processing target: {target}")

        # --- Validation ---
        platform = target.get("platform")
        template_name = target.get("template_name")
        context_data = target.get("context_data")
        if not all([platform, template_name, context_data]) or not isinstance(
            context_data, dict
        ):
            run_logger.error(
                f"{target_log_prefix}: Invalid target structure. Skipping."
            )
            failure_count += 1
            continue
        dest_alias = context_data.get("destination_alias")
        reminder_text = context_data.get("reminder_text")
        if not dest_alias or not reminder_text:
            run_logger.error(
                f"{target_log_prefix}: Context missing 'destination_alias' or 'reminder_text'. Skipping."
            )
            failure_count += 1
            continue

        # --- Prepare context and Submit Task ---
        try:
            current_context = context_data.copy()
            reminder_id = str(uuid.uuid4())
            current_context["reminder_id"] = reminder_id
            local_message_context = (message_context or {}).copy()
            local_message_context["reminder_id"] = reminder_id
            run_logger.info(
                f"{target_log_prefix}: Generated reminder_id: {reminder_id}"
            )

            final_destination_id = get_destination_id(platform, dest_alias)
            if not final_destination_id:
                err_msg = f"{target_log_prefix}: Could not resolve alias '{dest_alias}' for '{platform}'. Failing Flow."
                run_logger.error(err_msg)
                failure_count += 1
                raise ValueError(err_msg)
            current_context["recipient"] = final_destination_id
            run_logger.info(
                f"{target_log_prefix}: Resolved '{dest_alias}' to recipient '{final_destination_id}'."
            )

            mention_aliases = current_context.get("mention_aliases", [])
            if mention_aliases and isinstance(mention_aliases, list):
                resolved_mention_ids = resolve_mention_aliases(
                    platform, mention_aliases
                )
                current_context["mentions"] = resolved_mention_ids
                run_logger.info(
                    f"{target_log_prefix}: Resolved mentions {mention_aliases} to {resolved_mention_ids}."
                )
            elif "mention_aliases" in current_context:
                run_logger.warning(
                    f"{target_log_prefix}: 'mention_aliases' invalid/empty. Ignored."
                )
                current_context["mentions"] = []

            run_logger.debug(
                f"{target_log_prefix}: Submitting task for platform '{platform}'."
            )
            task_future: PrefectFuture = build_and_publish_reminder_task.submit(
                channel=platform,
                template_name=template_name,
                context_data=current_context,
                message_context=local_message_context,
            )
            tasks_submitted.append((platform, reminder_id, task_future))

        except Exception as e:
            failure_count += 1
            run_logger.exception(
                f"{target_log_prefix}: Error preparing or submitting task for '{platform}'. Flow will fail."
            )
            raise e

    # --- Wait for Task Results and Handle Failures (Using future.result() without await) ---
    run_logger.info(
        f"{log_prefix}: Waiting for {len(tasks_submitted)} submitted task(s) to complete..."
    )
    any_task_failed = False

    for platform, rem_id, future in tasks_submitted:
        target_log_prefix = f"{log_prefix} TaskResult (RemID: {rem_id[:8]})"
        try:
            # --- Get result synchronously with timeout ---
            # future.result(timeout=...) blocks until result is ready or timeout/exception occurs
            # This assumes the underlying task runner handles yielding control appropriately
            # in an async flow context when blocking for the result.
            run_logger.debug(
                f"{target_log_prefix}: Waiting for result of task for platform '{platform}'..."
            )
            success = future.result(timeout=300)  # Wait up to 5 mins

            # --- Process result ---
            if success is True:
                success_count += 1
                run_logger.info(
                    f"{target_log_prefix}: Task for platform '{platform}' completed successfully."
                )
            else:
                failure_count += 1
                run_logger.error(
                    f"{target_log_prefix}: Task for platform '{platform}' completed but reported failure (returned {success}). Flow will fail."
                )
                any_task_failed = True

        except TimeoutError:
            failure_count += 1
            run_logger.error(
                f"{target_log_prefix}: Timeout waiting for task result for platform '{platform}'. Flow will fail."
            )
            any_task_failed = True
        except Exception as e:
            # Task failed with an exception, re-raised by future.result()
            failure_count += 1
            run_logger.exception(
                f"{target_log_prefix}: Task for platform '{platform}' failed with an exception. Flow will fail."
            )
            any_task_failed = True

    # --- Final Flow State Decision ---
    if any_task_failed:
        raise RuntimeError(
            f"{log_prefix}: Flow failed because {failure_count} out of {len(tasks_submitted)} reminder task(s) did not complete successfully. Check logs."
        )

    # --- Flow Completion Summary ---
    total_submitted = len(tasks_submitted)
    total_processed = processed_target_count
    if total_submitted > 0:
        run_logger.info(
            f"{log_prefix}: Successfully completed all {total_submitted} submitted task(s)."
        )
    elif failure_count > 0:  # Validation failed for all targets
        run_logger.warning(
            f"{log_prefix}: Finished, but validation failed for all {failure_count}/{total_processed} targets before task submission."
        )
    else:  # No targets
        run_logger.info(f"{log_prefix}: No valid targets were processed.")


# --- Main Execution Block (Keep as is) ---
if __name__ == "__main__":
    import sys

    # import asyncio # Already imported above
    try:
        from utils.config_loader import ConfigLoader
        from utils.settings import ENV
    except ImportError:
        print("Missing utils dependencies", file=sys.stderr)
        sys.exit(1)

    param_file_path = "orch/params/reminder_params.json"

    try:
        print(f"Loading parameters from: {param_file_path} (ENV='{ENV}')")
        loader = ConfigLoader(param_file_path)
        params = loader.config
        print(f"Loaded/Resolved params: {params}")
        if "targets" not in params:
            print("Error: Missing 'targets' key.", file=sys.stderr)
            sys.exit(1)

        print("Starting REMINDER flow execution...")
        asyncio.run(send_reminder_flow(**params))
        print("REMINDER flow execution finished successfully.")

    except FileNotFoundError:
        print(f"Error: File not found '{param_file_path}'.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"REMINDER flow execution failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
