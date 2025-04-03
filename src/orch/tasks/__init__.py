# src/orch/tasks/__init__.py
# -*- coding: utf-8 -*-

"""
Exports Prefect tasks used in orchestration flows.
"""

# Import task(s) from info_sending_tasks.py
from .info_sending_tasks import build_and_publish_info_task

# Import task(s) from reminder_sending_tasks.py
# Currently, this file only contains the main build/publish/schedule task
from .reminder_sending_tasks import build_and_publish_reminder_task

# --- Removed Imports for Persistence Tasks ---
# These tasks (save_initial_reminder_state_task, get_reminder_state_task, etc.)
# should now reside in other files (e.g., maybe a new state_management_tasks.py
# or be part of the check_reminder_flow logic and its associated tasks)
# and should be imported directly where needed, not necessarily re-exported here,
# unless you specifically want to expose them via the 'tasks' package level.
# --- End Removed Imports ---


# Define __all__ for explicit export - ONLY include tasks currently defined
# in the imported modules within this __init__.py
__all__ = [
    # Sending Tasks
    "build_and_publish_info_task",
    "build_and_publish_reminder_task",
    # --- Removed Persistence Task Names ---
]

# Optional: If you create a new file for state tasks, you could import them:
# try:
#     from .state_management_tasks import (
#         get_reminder_state_task,
#         # ... other state tasks
#     )
#     __all__.extend([
#         "get_reminder_state_task",
#         # ...
#     ])
# except ImportError:
#     pass # Handle if state management tasks are not yet created
