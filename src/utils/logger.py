# src/utils/logger.py (Revised - Cleaner Uvicorn Integration)

import logging
import sys
import os

# --- Configuration ---
log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)
log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"

# --- Configure Root Logger ---
root_logger = logging.getLogger()
root_logger.setLevel(log_level)

# --- Setup Console Handler for Root Logger ---
if root_logger.hasHandlers():
    root_logger.handlers.clear()
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(log_level)
formatter = logging.Formatter(log_format)
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# --- Configure Third-Party Loggers (Optional) ---
logging.getLogger("redis").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.INFO)

# --- Integrate Uvicorn by Clearing its Handlers and Relying on Propagation ---
# This ensures Uvicorn logs use the root logger's handler and format, avoiding duplicates.
try:
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uvicorn_logger = logging.getLogger(name)
        # Remove Uvicorn's default handlers
        uvicorn_logger.handlers.clear()
        # Ensure propagation is enabled (it should be by default, but being explicit is safe)
        uvicorn_logger.propagate = True
        # Set level (optional, can inherit from root or be set specifically)
        if "access" in name:
            # Keep access logs potentially less verbose than DEBUG
            uvicorn_logger.setLevel(max(log_level, logging.INFO))
        else:
            uvicorn_logger.setLevel(log_level)  # Sync with root level
except Exception as e:
    logging.warning(
        f"Could not reconfigure uvicorn loggers (clear handlers): {e}", exc_info=False
    )

# --- Log Initialization Message ---
logging.info(
    f"Root logger configured. Level: {log_level_name}. Uvicorn integration attempted (clear handlers)."
)

# --- Usage in other modules: import logging; logger = logging.getLogger(__name__) ---
