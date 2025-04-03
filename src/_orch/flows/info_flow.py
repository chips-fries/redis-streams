# src/orch/flows/info_flow.py
# -*- coding: utf-8 -*-

"""
Prefect Flow definition for sending simple informational messages.
Accepts a list of targets for multi-platform, multi-destination dispatch.
"""
import os
import logging
from typing import Dict, Any, List, Optional

# --- Prefect Imports ---
try:
    from prefect import flow, task, get_run_logger
except ImportError:
    print("Error: 'prefect' package not found.")
    raise

# --- Local Imports ---
try:
    from _orch.tasks.info_sending_tasks import build_and_publish_info_task

    # Import targeting functions and ENV
    from _orch.utils.targeting import get_destination_id, resolve_mention_aliases, ENV
except ImportError as e:
    logging.getLogger(__name__).critical(
        f"Could not import required task or targeting utils: {e}", exc_info=True
    )
    raise  # Cannot proceed without these

logger = logging.getLogger(__name__)  # Logger name: orch.flows.info_flow

# --- Flow Definition ---


@flow(name="Example - Send Info Message", retries=0)  # Updated name
async def send_info_flow(
    # --- Updated Parameters ---
    targets: List[Dict[str, Any]],  # List of target specifications
    # Optional global context
    message_context: Optional[Dict[str, Any]] = None,
    trigger_source: str = "unknown",
):
    """
    Builds and publishes instructions to send informational messages based on a list of targets.
    Each target specifies the platform, template, and context (including destination alias).

    Args:
        targets (List[Dict[str, Any]]): A list where each dict represents a target.
            Each dict should contain:
            - platform (str): Target platform (e.g., "slack", "line").
            - template_name (str): Name of the template class to use.
            - context_data (Dict[str, Any]): Data for the template, must include:
                - destination_alias (str): User-friendly alias for the target destination.
                - main_text (str): The primary message content.
                - Optional: mention_aliases (List[str]): Aliases of users to mention.
                - Optional: sub_text (str): Secondary text.
                - ... other template-specific data ...
        message_context (Optional[Dict[str, Any]]): Global context for logging/tracing.
        trigger_source (str): Identifier for what triggered this flow.
    """
    run_logger = get_run_logger()
    flow_run_id_str = f"(FlowRun: {getattr(run_logger, 'flow_run_id', 'N/A')})"
    log_prefix = f"Info Flow v2 {flow_run_id_str}"

    run_logger.info(
        f"{log_prefix}: Starting for {len(targets)} target(s). Trigger='{trigger_source}'. ENV='{ENV}'. Global Context: {message_context}"
    )

    # --- Input Validation ---
    if not targets:
        run_logger.warning(f"{log_prefix}: No targets specified. Flow will exit.")
        return
    if not isinstance(targets, list):
        run_logger.error(f"{log_prefix}: 'targets' parameter must be a list. Aborting.")
        raise TypeError("'targets' must be a list.")

    # --- Iterate through targets and publish send tasks ---
    publish_success_count = 0
    publish_failure_count = 0
    processed_count = 0

    for i, target in enumerate(targets):
        processed_count += 1
        target_log_prefix = f"{log_prefix} Target {i+1}/{len(targets)}"
        run_logger.debug(f"{target_log_prefix}: Processing target: {target}")

        # Validate individual target structure
        platform = target.get("platform")
        template_name = target.get("template_name")
        context_data = target.get("context_data")

        if not all([platform, template_name, context_data]) or not isinstance(
            context_data, dict
        ):
            run_logger.error(
                f"{target_log_prefix}: Invalid target structure. Skipping. Target: {target}"
            )
            publish_failure_count += 1
            continue  # Skip invalid target

        # Validate required context_data keys
        dest_alias = context_data.get("destination_alias")
        main_text = context_data.get("main_text")  # Assuming main_text is always needed
        if not dest_alias or not main_text:
            run_logger.error(
                f"{target_log_prefix}: Target context_data missing 'destination_alias' or 'main_text'. Skipping. Context: {context_data}"
            )
            publish_failure_count += 1
            continue

        try:
            current_context = context_data.copy()  # Work with a copy

            # --- Resolve Destination ID ---
            final_destination_id = get_destination_id(platform, dest_alias)
            if not final_destination_id:
                run_logger.error(
                    f"{target_log_prefix}: Could not resolve destination alias '{dest_alias}' for platform '{platform}'. Skipping."
                )
                publish_failure_count += 1
                continue
            # Update context with the resolved ID, which the task will use
            current_context["recipient"] = final_destination_id
            run_logger.info(
                f"{target_log_prefix}: Resolved '{dest_alias}' to recipient ID '{final_destination_id}' for platform '{platform}'."
            )

            # --- Resolve Mention Aliases ---
            mention_aliases = current_context.get("mention_aliases", [])
            if mention_aliases and isinstance(mention_aliases, list):
                resolved_mention_ids = resolve_mention_aliases(
                    platform, mention_aliases
                )
                # Add resolved IDs to context for the task/template
                current_context[
                    "mentions"
                ] = resolved_mention_ids  # Task/Template will use 'mentions' with IDs
                run_logger.info(
                    f"{target_log_prefix}: Resolved mention aliases {mention_aliases} to IDs {resolved_mention_ids} for platform '{platform}'."
                )
            elif (
                "mention_aliases" in current_context
            ):  # If key exists but is invalid type or empty
                run_logger.warning(
                    f"{target_log_prefix}: 'mention_aliases' key present but invalid or empty in context. Ignored."
                )
                current_context[
                    "mentions"
                ] = (
                    []
                )  # Ensure 'mentions' key exists as empty list if alias key was present

            # --- Call the Task ---
            run_logger.debug(
                f"{target_log_prefix}: Submitting task for platform '{platform}', template '{template_name}'."
            )
            # Use .submit for potential parallelism, or await for sequential execution
            # Using await here for simplicity in demonstrating the logic flow
            success = await build_and_publish_info_task(
                channel=platform,  # Pass platform as 'channel' to the task
                template_name=template_name,
                context_data=current_context,  # Pass context with resolved IDs
                message_context=message_context,  # Pass global context
            )

            if success:
                publish_success_count += 1
                run_logger.info(
                    f"{target_log_prefix}: Task succeeded for platform '{platform}'."
                )
            else:
                # Task itself indicated failure (e.g., build error, publish error after retry)
                publish_failure_count += 1
                err_msg = f"{target_log_prefix}: Task 'build_and_publish_info_task' failed for platform '{platform}'. Flow will fail."
                run_logger.error(err_msg)
                # Raise an exception to explicitly fail the flow run
                raise RuntimeError(err_msg)

        except Exception as e:
            # Catch unexpected errors during target processing or from the task call itself
            publish_failure_count += 1
            run_logger.exception(
                f"{target_log_prefix}: Unexpected error processing target for platform '{platform}'. Flow will fail."
            )
            # Re-raise the exception to fail the flow run
            raise e

    # --- Flow Completion ---
    if publish_failure_count > 0:
        # Flow already failed due to 'raise', but log a final summary
        run_logger.warning(
            f"{log_prefix}: Finished processing. {publish_failure_count}/{processed_count} target(s) encountered failures. Flow state should be FAILED."
        )
    elif processed_count > 0:
        run_logger.info(
            f"{log_prefix}: Successfully processed all {processed_count} target(s)."
        )
    else:
        run_logger.info(
            f"{log_prefix}: No valid targets were processed."
        )  # Should be caught earlier


# --- Main Execution Block ---
if __name__ == "__main__":
    import sys
    import asyncio
    import os

    try:
        # Import ConfigLoader and potentially ENV for logging
        from utils.config_loader import ConfigLoader
        from utils.settings import ENV  # For logging purposes
    except ImportError:
        print(
            "Error: Missing dependencies (utils.config_loader or utils.settings)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parameters file path relative to CWD (expected to be src/)
    param_file_path = "orch/params/info_params.json"

    try:
        print(
            f"Attempting to load and resolve parameters from: {param_file_path} (using ConfigLoader for ENV='{ENV}')"
        )
        # --- Use ConfigLoader to load the JSON file ---
        loader = ConfigLoader(param_file_path)  # ConfigLoader needs to handle JSON too!
        params = loader.config  # Get the resolved config dictionary
        # --- Modification End ---
        print(f"Loaded and resolved params: {params}")

        # Validate top-level structure
        if "targets" not in params:
            print(
                f"Error: Resolved parameters are missing the required 'targets' key.",
                file=sys.stderr,
            )
            sys.exit(1)

        print("Starting flow execution via Python script (CWD=src)...")
        asyncio.run(send_info_flow(**params))
        print("Flow execution finished successfully.")

    except FileNotFoundError:
        print(
            f"Error: Parameter file not found at '{param_file_path}'.", file=sys.stderr
        )
        sys.exit(1)
    # Catch potential errors from ConfigLoader (e.g., YAML/JSON parsing, reference errors)
    except Exception as e:  # Broadly catch loader errors for now
        print(
            f"Error loading or resolving parameters from '{param_file_path}': {e}",
            file=sys.stderr,
        )
        import traceback

        traceback.print_exc()
        sys.exit(1)
