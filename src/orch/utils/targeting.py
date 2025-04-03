# src/orch/utils/targeting.py
# -*- coding: utf-8 -*-

"""
Utility functions for resolving destination and user aliases based on platform and environment.
Loads mappings from a YAML configuration file.
"""

import logging
import os
from typing import Optional, Dict, List

# --- Imports and Configuration Loading ---
try:
    # Assumes settings.py provides the current ENV variable
    from utils.settings import ENV

    # Assumes config_loader.py provides ConfigLoader class
    from utils.config_loader import ConfigLoader
except ImportError:
    # Fallback if running standalone or imports fail
    ENV = os.environ.get("ENV", "test")
    logging.getLogger(__name__).warning(
        f"Could not import settings/ConfigLoader, using fallback ENV: {ENV}"
    )
    # Dummy ConfigLoader for basic functionality if real one fails
    class ConfigLoader:
        def __init__(self, path):
            logger = logging.getLogger(__name__)
            logger.warning(f"Using dummy ConfigLoader for path: {path}")
            # In a real fallback, you might try loading yaml directly here
            self.config = {}  # Empty config on failure


logger = logging.getLogger(__name__)

# Path to the configuration file (relative to execution CWD, expected to be src/)
DESTINATIONS_CONFIG_PATH = "config/destinations.yaml"

# Global dictionaries to hold the loaded mappings
PLATFORM_DESTINATION_MAPS: Dict[str, Dict[str, str]] = {}
PLATFORM_USER_MAPS: Dict[str, Dict[str, str]] = {}


def _load_targeting_config():
    """Loads destination and user maps from the YAML file."""
    global PLATFORM_DESTINATION_MAPS, PLATFORM_USER_MAPS
    try:
        logger.info(
            f"Attempting to load targeting config from: {DESTINATIONS_CONFIG_PATH}"
        )
        loader = ConfigLoader(DESTINATIONS_CONFIG_PATH)
        config = loader.config

        # Clear existing maps before loading
        PLATFORM_DESTINATION_MAPS = {}
        PLATFORM_USER_MAPS = {}

        # Extract destination maps (all top-level keys except 'users')
        for platform, mappings in config.items():
            if platform == "users":
                continue  # Skip the special 'users' key
            if isinstance(mappings, dict):
                PLATFORM_DESTINATION_MAPS[platform] = mappings
            else:
                logger.warning(
                    f"Invalid format for platform '{platform}' in config. Expected a dictionary."
                )

        # Extract user maps (from the 'users' key)
        users_config = config.get("users")
        if isinstance(users_config, dict):
            for platform, user_mappings in users_config.items():
                if isinstance(user_mappings, dict):
                    PLATFORM_USER_MAPS[platform] = user_mappings
                else:
                    logger.warning(
                        f"Invalid format for user map under platform '{platform}'. Expected a dictionary."
                    )
        elif users_config is not None:
            logger.warning(
                "Invalid format for 'users' key in config. Expected a dictionary."
            )

        logger.info(f"Successfully loaded targeting config.")
        logger.debug(
            f"Loaded destination platforms: {list(PLATFORM_DESTINATION_MAPS.keys())}"
        )
        logger.debug(f"Loaded user map platforms: {list(PLATFORM_USER_MAPS.keys())}")

    except FileNotFoundError:
        logger.critical(
            f"Targeting config file not found at '{DESTINATIONS_CONFIG_PATH}'. Alias resolution will fail."
        )
    except Exception as e:
        logger.critical(
            f"Failed to load or parse targeting config from '{DESTINATIONS_CONFIG_PATH}': {e}",
            exc_info=True,
        )


# Load the configuration when the module is imported
_load_targeting_config()

# --- Targeting Functions ---


def get_destination_id(platform: str, destination_alias: str) -> Optional[str]:
    """
    Resolves a destination alias into a platform-specific Destination ID (as string) using loaded config.
    Handles aliases prefixed with 'env_' by replacing 'env' with the current ENV value.
    """
    platform_map = PLATFORM_DESTINATION_MAPS.get(platform)
    if not platform_map:
        logger.error(f"No destination map loaded for platform: '{platform}'")
        return None

    # Handle ENV-dependent aliases (e.g., "env_default_channel")
    if destination_alias.startswith("env_"):
        resolved_alias = destination_alias.replace("env_", f"{ENV}_", 1)
        logger.debug(
            f"Resolved ENV-dependent alias '{destination_alias}' to '{resolved_alias}' for ENV='{ENV}'"
        )
    else:
        resolved_alias = destination_alias  # Use alias directly

    destination_id_from_yaml = platform_map.get(
        resolved_alias
    )  # Renamed variable for clarity

    # Check if the key (resolved alias) exists in the map
    if destination_id_from_yaml is None:
        logger.error(
            f"Destination ID not found for platform '{platform}' and resolved alias '{resolved_alias}' (Original Alias: '{destination_alias}')"
        )
        return None

    # --- Convert the retrieved ID to string before returning ---
    destination_id_str = str(destination_id_from_yaml)
    # --- End modification ---

    # Log the final string ID and its type for confirmation
    logger.debug(
        f"Resolved destination alias '{resolved_alias}' to ID '{destination_id_str}' (type: {type(destination_id_str)}) for platform '{platform}'"
    )
    # Return the string representation
    return destination_id_str


def get_mention_user_id(platform: str, user_alias: str) -> Optional[str]:
    """Resolves a user alias to a platform-specific User ID using loaded config."""
    user_map = PLATFORM_USER_MAPS.get(platform)
    if not user_map:
        # Log warning as mention might be optional
        logger.warning(
            f"No user map loaded for platform: '{platform}' to resolve mention alias '{user_alias}'"
        )
        return None
    user_id = user_map.get(user_alias)
    if not user_id:
        logger.warning(
            f"User ID not found in map for platform '{platform}' and alias '{user_alias}'"
        )
        return None
    logger.debug(
        f"Resolved mention user alias '{user_alias}' to ID '{user_id}' for platform '{platform}'"
    )
    return user_id


def resolve_mention_aliases(platform: str, aliases: List[str]) -> List[str]:
    """Resolves a list of user aliases into a list of valid User IDs for the platform."""
    resolved_ids = []
    if not isinstance(aliases, list):
        logger.warning(
            f"resolve_mention_aliases received non-list input for aliases: {aliases}. Returning empty list."
        )
        return []
    for alias in aliases:
        if not isinstance(alias, str):
            logger.warning(f"Skipping non-string alias in mention list: {alias}")
            continue
        user_id = get_mention_user_id(platform, alias)
        if user_id:
            resolved_ids.append(user_id)
        # Warning for unresolved alias is logged inside get_mention_user_id
    return resolved_ids
