import sys
import subprocess
import platform
import logging
from typing import Optional, List
from utils.config_loader import ConfigLoader


# Assuming logger is imported/configured elsewhere if needed for the warning
try:
    from utils.logger import logger  # Or however you access your configured logger
except ImportError:
    logger = logging.getLogger(__name__)  # Fallback basic logger


def detect_env_from_git_branch() -> str:
    """
    Detects the current environment (test, uat, prod) based on Git branch and OS,
    temporarily suppressing logs when run directly via command line (e.g., 'python -c').
    """
    is_run_directly = __name__ == "__main__" or (
        hasattr(sys, "argv") and len(sys.argv) > 0 and sys.argv[0] == "-c"
    )
    root_logger = logging.getLogger()
    original_level = root_logger.level
    original_handlers: List[logging.Handler] = root_logger.handlers[:]  # Store handlers

    if is_run_directly:
        root_logger.setLevel(logging.CRITICAL + 1)  # Suppress logs below CRITICAL
        # Optional: you could clear handlers instead if level setting doesn't work reliably
        # root_logger.handlers.clear()

    env = "test"  # Default
    try:
        branch_bytes = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        branch = branch_bytes.decode("utf-8").strip()

        if branch == "main":
            env = "prod"
            system = platform.system().lower()
            if (
                "linux" not in system and not is_run_directly
            ):  # Log warning only when imported
                logger.warning(
                    "⚠️ Running on main branch outside of Linux (prod env). Ensure this is intended."
                )
        elif branch == "uat":
            env = "uat"
        else:  # Any other branch is 'test'
            if not is_run_directly:  # Log only when imported
                logger.info(
                    f"Branch '{branch}' detected, setting environment to 'test'."
                )
            env = "test"

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as e:
        if not is_run_directly:  # Log error only when imported
            logger.error(
                f"Git branch detection failed ({type(e).__name__}). Defaulting to 'test'."
            )
        env = "test"  # Fallback to test on any git error
    except Exception as e:
        if not is_run_directly:
            logger.error(
                f"Unexpected error detecting git branch: {e}. Defaulting to 'test'."
            )
        env = "test"  # Fallback

    finally:
        if is_run_directly:  # Restore logging state only if it was changed
            root_logger.setLevel(original_level)
            # If handlers were cleared, restore them:
            # root_logger.handlers.clear(); root_logger.handlers.extend(original_handlers)

    return env


# --- Get API Base URL based on Environment ---
def get_api_base_url(
    config_path: str = "config/environments_config.yaml",
) -> Optional[str]:
    """
    Determines the current environment using Git branch and retrieves
    the corresponding api_base_url from the specified configuration file.

    Args:
        config_path (str): Path to the environments configuration YAML file.

    Returns:
        Optional[str]: The API base URL for the detected environment, or None if not found/error.
    """
    try:
        # 1. Detect the environment
        current_env = detect_env_from_git_branch()
        logger.info(f"Detected environment: {current_env}")

        # 2. Load the environments configuration
        try:
            # Assuming ConfigLoader takes path and exposes config via .config attribute
            loader = ConfigLoader(config_path)
            environments_config = loader.config.get("environments")
        except FileNotFoundError:
            logger.error(f"Environment config file not found at: {config_path}")
            return None
        except Exception as e:
            logger.error(
                f"Error loading environment config from {config_path}: {e}",
                exc_info=True,
            )
            return None

        if not environments_config or not isinstance(environments_config, dict):
            logger.error(
                f"Invalid format in {config_path}: 'environments' key missing or not a dictionary."
            )
            return None

        # 3. Get the configuration for the current environment
        env_settings = environments_config.get(current_env)
        if not env_settings or not isinstance(env_settings, dict):
            logger.error(
                f"Configuration for environment '{current_env}' not found or invalid in {config_path}."
            )
            return None

        # 4. Retrieve the api_base_url
        api_base_url = env_settings.get("api_base_url")
        if not api_base_url or not isinstance(api_base_url, str):
            logger.error(
                f"'api_base_url' not found or invalid for environment '{current_env}' in {config_path}."
            )
            return None

        logger.info(f"Using API Base URL for '{current_env}': {api_base_url}")
        return api_base_url.strip("/")  # Remove trailing slash if present

    except Exception as e:
        # Catch any unexpected errors during the process
        logger.error(f"Failed to determine API base URL: {e}", exc_info=True)
        return None
