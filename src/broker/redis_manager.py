# src/utils/redis_manager.py
# -*- coding: utf-8 -*-

"""
Utility class for managing interactions with a Redis server.

Reads connection details from config/redis_config.yaml and uses password
from utils.config. Reads connection details using ConfigLoader and password
from utils.config.
"""

import logging
import json
import threading
import os
from typing import Dict, Any, List, Optional, Union, Mapping, Callable, Tuple

# --- Dependencies ---
# Required: redis, (Optional but used here: python-dotenv for utils.config)
# Install: poetry add redis python-dotenv
try:
    from redis import Redis
    from redis.exceptions import (
        RedisError,
        WatchError,
        ConnectionError as RedisConnectionError,
        AuthenticationError as RedisAuthenticationError,
    )
except ImportError:
    print(
        "Error: The 'redis' package is required. Please install it using 'poetry add redis'"
    )
    raise

# --- Local Imports ---
# Assuming these files exist and function correctly
try:
    from utils.config_loader import ConfigLoader  # To load redis_config.yaml
    from utils.settings import REDIS_PASSWORD  # To get the password
except ImportError as e:
    print(f"Error: Failed to import ConfigLoader or REDIS_PASSWORD from utils: {e}")
    print("Please ensure src/utils/config_loader.py and src/utils/config.py exist.")
    # If these are critical for initialization, raise the error
    raise ImportError(f"Missing required utils components: {e}") from e

# --- Logging ---
# Logger setup is handled externally (e.g., in utils.logger.py)
logger = logging.getLogger(__name__)

# --- Custom Exceptions ---
class RedisManagerError(Exception):
    """Base exception for RedisManager specific errors."""

    pass


class RedisConfigurationError(RedisManagerError):
    """Error related to RedisManager configuration or connection setup."""

    pass


class RedisOperationError(RedisManagerError):
    """Error occurred during a Redis operation."""

    pass


# --- RedisManager Class ---
class RedisManager:
    """
    Manages connections and provides methods for interacting with Redis.

    Reads connection details from 'config/redis_config.yaml' using ConfigLoader.
    Uses password provided by 'utils.config.REDIS_PASSWORD'.
    Provides generic interfaces for common Redis operations.
    """

    LOCK_PREFIX: str = "lock:"

    def __init__(self, config_path: str = "config/redis_config.yaml"):
        """
        Initializes the RedisManager by loading configuration and connecting to Redis.

        Args:
            config_path (str): Path to the Redis configuration YAML file, relative
                               to the project root or execution directory where
                               ConfigLoader expects it.

        Raises:
            RedisConfigurationError: If configuration cannot be loaded or connection fails.
        """
        self.redis: Optional[Redis] = None
        self.config = self._load_config(config_path)
        self._connect()

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Loads Redis configuration from the specified YAML file."""
        try:
            loader = ConfigLoader(config_path)
            redis_config = loader.config.get("redis")
            if not redis_config or not isinstance(redis_config, dict):
                raise RedisConfigurationError(
                    f"Invalid or missing 'redis' section in config file: {config_path}"
                )
            logger.info(f"Loaded Redis configuration from {config_path}.")
            return redis_config
        except FileNotFoundError:
            logger.critical(f"Redis configuration file not found at: {config_path}")
            raise RedisConfigurationError(
                f"Redis config file not found: {config_path}"
            ) from FileNotFoundError
        except Exception as e:
            logger.critical(
                f"Failed to load or parse Redis configuration from {config_path}: {e}",
                exc_info=True,
            )
            raise RedisConfigurationError(f"Failed to load Redis config: {e}") from e

    def _connect(self) -> None:
        """Establishes the connection to Redis based on loaded configuration."""
        host = self.config.get("host", "localhost")
        port = self.config.get("port", 6379)
        db = self.config.get("db", 0)
        # Use decode_responses=True by default for convenience unless explicitly set otherwise
        decode_responses = self.config.get("decode_responses", True)
        redis_url = self.config.get("url")  # Optional URL override

        # Password comes from utils.config, not the YAML file for security
        password = REDIS_PASSWORD

        logger.info(f"Attempting to connect to Redis...")
        logger.debug(
            f"Redis connection params: URL={redis_url}, Host={host}, Port={port}, DB={db}, Decode={decode_responses}, Password={'***' if password else 'None'}"
        )

        try:
            if redis_url:
                logger.info(f"Connecting using Redis URL from config: {redis_url}")
                # Note: Password in URL might override the environment variable password depending on redis-py version.
                # It's usually better to use host/port/db/password separate or ensure URL doesn't contain password.
                # Let's prioritize environment password if provided.
                self.redis = Redis.from_url(
                    redis_url, password=password, decode_responses=decode_responses
                )
            else:
                logger.info(f"Connecting using Redis host/port/db from config.")
                self.redis = Redis(
                    host=host,
                    port=int(port),
                    db=int(db),
                    password=password,
                    decode_responses=decode_responses,
                )

            # Verify connection
            self.redis.ping()
            logger.info(
                f"Redis connection successful (Host: {host}, Port: {port}, DB: {db})."
            )

        except (RedisConnectionError, RedisAuthenticationError) as e:
            logger.critical(f"Failed to connect to Redis: {e}", exc_info=True)
            raise RedisConfigurationError(f"Failed to connect to Redis: {e}") from e
        except (ValueError, TypeError) as e:  # Catch errors from int(port)/int(db)
            logger.critical(
                f"Invalid Redis configuration value (e.g., port, db): {e}",
                exc_info=True,
            )
            raise RedisConfigurationError(f"Invalid Redis config value: {e}") from e
        except Exception as e:
            logger.critical(
                f"Unexpected error initializing Redis client: {e}", exc_info=True
            )
            raise RedisConfigurationError(
                f"Unexpected error initializing Redis: {e}"
            ) from e

        if not self.redis:
            raise RedisConfigurationError(
                "Redis client initialization failed unexpectedly after connection attempt."
            )

    # --- Helper to ensure client is connected ---
    def _ensure_connected(self) -> None:
        """Raises an error if the Redis client is not initialized."""
        if not self.redis:
            # This should ideally not happen after successful __init__, but acts as a safeguard.
            logger.error("Redis client is not initialized. Cannot perform operation.")
            raise RedisConfigurationError("Redis client not initialized.")

    # --- Generic Key-Value / Hash Operations ---

    def get_hash(self, key: str) -> Optional[Dict[str, str]]:
        """Gets all fields and values from a Redis Hash."""
        self._ensure_connected()
        try:
            data = self.redis.hgetall(key)
            if not data:
                return None
            return {
                k.decode()
                if isinstance(k, bytes)
                else k: v.decode()
                if isinstance(v, bytes)
                else v
                for k, v in data.items()
            }
        except RedisError as e:
            logger.error(f"Redis error getting hash '{key}': {e}", exc_info=True)
            return None

    def set_hash(
        self, key: str, data: Mapping[str, Union[str, bytes, int, float, None]]
    ) -> bool:
        """Sets multiple fields in a Redis Hash."""
        self._ensure_connected()
        if not data:
            return True  # No-op for empty data
        try:
            redis_map = {
                str(k): str(v) if v is not None else "" for k, v in data.items()
            }
            result = self.redis.hset(key, mapping=redis_map)
            logger.debug(
                f"Set hash '{key}'. HSET result (fields added/updated): {result}"
            )
            return True
        except RedisError as e:
            logger.error(f"Redis error setting hash '{key}': {e}", exc_info=True)
            return False

    def set_hash_field(
        self, key: str, field: str, value: Union[str, bytes, int, float, None]
    ) -> bool:
        """Sets a single field in a Redis Hash."""
        self._ensure_connected()
        try:
            value_str = str(value) if value is not None else ""
            self.redis.hset(key, str(field), value_str)
            return True
        except RedisError as e:
            logger.error(
                f"Redis error setting field '{field}' in hash '{key}': {e}",
                exc_info=True,
            )
            return False

    def get_hash_field(self, key: str, field: str) -> Optional[str]:
        """Gets a single field's value from a Redis Hash."""
        self._ensure_connected()
        try:
            value = self.redis.hget(key, str(field))
            return value  # Returns str or None
        except RedisError as e:
            logger.error(
                f"Redis error getting field '{field}' from hash '{key}': {e}",
                exc_info=True,
            )
            return None

    def hash_exists(self, key: str) -> bool:
        """Checks if a hash key exists."""
        self._ensure_connected()
        try:
            return bool(self.redis.exists(key))
        except RedisError as e:
            logger.error(
                f"Redis error checking existence of key '{key}': {e}", exc_info=True
            )
            return False

    def delete_key(self, key: str) -> bool:
        """Deletes a key."""
        self._ensure_connected()
        try:
            deleted_count = self.redis.delete(key)
            logger.debug(f"Deleted key '{key}'. Count: {deleted_count}")
            return deleted_count > 0
        except RedisError as e:
            logger.error(f"Redis error deleting key '{key}': {e}", exc_info=True)
            return False

    # --- Generic Sorted Set (ZSET) Operations ---

    def zadd(
        self, key: str, mapping: Mapping[str, float], nx: bool = False, xx: bool = False
    ) -> Optional[int]:
        """Adds or updates members in a Sorted Set."""
        self._ensure_connected()
        if not mapping:
            return 0
        try:
            result = self.redis.zadd(key, mapping, nx=nx, xx=xx)
            return result
        except RedisError as e:
            logger.error(
                f"Redis error performing ZADD on key '{key}': {e}", exc_info=True
            )
            return None

    def zrem(self, key: str, members: List[str]) -> Optional[int]:
        """Removes members from a Sorted Set."""
        self._ensure_connected()
        if not members:
            return 0
        try:
            result = self.redis.zrem(key, *members)
            return result
        except RedisError as e:
            logger.error(
                f"Redis error performing ZREM on key '{key}' for members {members}: {e}",
                exc_info=True,
            )
            return None

    def zrangebyscore(
        self, key: str, min_score: Union[float, str], max_score: Union[float, str]
    ) -> Optional[List[str]]:
        """Gets members from a Sorted Set within a score range (inclusive)."""
        self._ensure_connected()
        try:
            results = self.redis.zrangebyscore(key, min_score, max_score)
            return results  # List[str]
        except RedisError as e:
            logger.error(
                f"Redis error performing ZRANGEBYSCORE on key '{key}' ({min_score} - {max_score}): {e}",
                exc_info=True,
            )
            return None

    # --- Generic List Operations ---

    def lpush(self, key: str, values: List[str]) -> Optional[int]:
        """Prepends one or more values to a List."""
        self._ensure_connected()
        if not values:
            return None
        try:
            result = self.redis.lpush(key, *values)
            return result  # List length
        except RedisError as e:
            logger.error(
                f"Redis error performing LPUSH on key '{key}': {e}", exc_info=True
            )
            return None

    def brpop(
        self, keys: Union[str, List[str]], timeout: int = 0
    ) -> Optional[Tuple[str, str]]:
        """Blocking pop from the tail (right side) of one or more Lists."""
        self._ensure_connected()
        try:
            result = self.redis.brpop(keys, timeout=timeout)
            return result  # (key, value) or None
        except RedisError as e:
            logger.error(
                f"Redis error performing BRPOP on key(s) '{keys}': {e}", exc_info=True
            )
            return None

    # --- Distributed Lock Operations ---

    def _get_lock_key(self, lock_name: str) -> str:
        """Constructs a Redis key for a distributed lock."""
        safe_lock_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in lock_name
        )
        return f"{self.LOCK_PREFIX}{safe_lock_name}"

    def acquire_lock(
        self, lock_name: str, lock_value: str, timeout_sec: int = 60
    ) -> bool:
        """Tries to acquire a distributed lock using SET NX EX."""
        self._ensure_connected()
        key = self._get_lock_key(lock_name)
        if timeout_sec <= 0:
            logger.warning(
                f"Acquiring lock '{key}' with non-positive timeout ({timeout_sec}s)."
            )
            # Consider raising error or setting a minimum default timeout?
            # For now, allow it but log warning.

        try:
            acquired = self.redis.set(key, lock_value, nx=True, ex=timeout_sec)
            if acquired:
                logger.debug(f"Acquired lock '{key}'.")
                return True
            else:
                return False
        except RedisError as e:
            logger.error(f"Redis error acquiring lock '{key}': {e}", exc_info=True)
            return False

    def release_lock(self, lock_name: str, lock_value: str) -> bool:
        """Safely releases a distributed lock using a Lua script."""
        self._ensure_connected()
        key = self._get_lock_key(lock_name)
        lua_script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        try:
            result = self.execute_lua_script(lua_script, keys=[key], args=[lock_value])
            if result == 1:
                logger.debug(f"Released lock '{key}'.")
                return True
            else:
                logger.warning(
                    f"Did not release lock '{key}' (value mismatch or lock missing)."
                )
                return False
        except RedisOperationError:
            return False  # Error logged within execute_lua_script

    # --- Lua Script Execution ---
    def execute_lua_script(
        self, script_content: str, keys: List[str], args: List[Any]
    ) -> Any:
        """Executes a Lua script atomically."""
        self._ensure_connected()
        try:
            script = self.redis.register_script(script_content)
            result = script(keys=keys, args=args)
            return result
        except RedisError as e:
            logger.error(f"Redis error executing Lua script: {e}", exc_info=True)
            raise RedisOperationError(
                f"Redis error during Lua script execution: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error executing Lua script: {e}", exc_info=True)
            raise  # Re-raise other errors

    # --- WATCH/MULTI/EXEC ---
    def execute_transaction(
        self, watch_keys: List[str], transaction_commands: Callable[[Redis], None]
    ) -> Optional[List[Any]]:
        """Executes commands within a WATCH/MULTI/EXEC transaction."""
        self._ensure_connected()
        pipe = self.redis.pipeline()
        try:
            if watch_keys:
                pipe.watch(*watch_keys)
            pipe.multi()
            transaction_commands(pipe)  # Function queues commands on pipe
            results = pipe.execute()
            logger.debug(
                f"Executed transaction watching {watch_keys}. Results count: {len(results)}"
            )
            return results
        except WatchError:
            logger.warning(
                f"WATCH error during transaction (watched keys: {watch_keys}). Transaction aborted."
            )
            return None  # Indicate failure due to watch
        except RedisError as e:
            logger.error(
                f"Redis error during transaction (watched keys: {watch_keys}): {e}",
                exc_info=True,
            )
            raise RedisOperationError(f"Redis error during transaction: {e}") from e
        except Exception as e:
            logger.error(
                f"Unexpected error during transaction function (watched keys: {watch_keys}): {e}",
                exc_info=True,
            )
            raise
        finally:
            pipe.reset()


# --- Dependency Injection Helper ---
# (Same get_redis_manager as before, but it now uses RedisManager which reads config)
_redis_manager_instance: Optional[RedisManager] = None
_redis_manager_lock = threading.Lock()


def get_redis_manager(config_path: str = "config/redis_config.yaml") -> RedisManager:
    """
    Provides a RedisManager instance (thread-safe singleton pattern).
    Loads config from the specified path on first call.
    """
    global _redis_manager_instance
    if _redis_manager_instance is None:
        with _redis_manager_lock:
            if _redis_manager_instance is None:
                logger.info(
                    f"Creating global RedisManager instance using config: {config_path}"
                )
                try:
                    # Initialize using the specified config path
                    _redis_manager_instance = RedisManager(config_path=config_path)
                    logger.info("Global RedisManager instance created successfully.")
                except RedisConfigurationError as e:
                    logger.critical(
                        f"CRITICAL: Failed to initialize global RedisManager: {e}",
                        exc_info=True,
                    )
                    raise e  # Propagate configuration error
    return _redis_manager_instance


# --- Example Usage ---
if __name__ == "__main__":
    # Assumes config/redis_config.yaml exists and is valid
    # Assumes utils.config.py exists and loads .env for REDIS_PASSWORD
    print("--- RedisManager Example (using ConfigLoader) ---")
    # Need dummy config files and .env for this to run standalone
    # Create dummy config/redis_config.yaml
    if not os.path.exists("config"):
        os.makedirs("config")
    with open("config/redis_config.yaml", "w") as f:
        f.write(
            "redis:\n  host: localhost\n  port: 6379\n  db: 0\n  decode_responses: true\n"
        )
    # Create dummy utils/config.py and utils/config_loader.py if they don't exist
    # Create .env file with REDIS_PASSWORD=your_redis_password (if needed)

    # Need a basic logger setup if utils.logger isn't fully functional yet
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    try:
        # Get manager (implicitly loads config/redis_config.yaml)
        manager = get_redis_manager()
        print("RedisManager obtained.")

        # Test connection with ping (already done in init, but can do again)
        if manager.redis and manager.redis.ping():
            print("Redis ping successful.")
        else:
            print("Redis ping failed.")
            exit()  # Exit if cannot connect

        # Example Hash operations
        print("\nTesting Hash...")
        hash_key = "my_test_hash_cfg"
        manager.delete_key(hash_key)
        data_to_set = {"fieldA": "valueA", "fieldB": 456, "fieldC": None}
        if manager.set_hash(hash_key, data_to_set):
            print(f"Set hash '{hash_key}'.")
            retrieved_hash = manager.get_hash(hash_key)
            print(f"Retrieved hash: {retrieved_hash}")
            field_val = manager.get_hash_field(hash_key, "fieldA")
            print(f"Retrieved fieldA: {field_val}")
        else:
            print("Failed to set hash.")

    except RedisConfigurationError as e:
        print(f"CONFIGURATION ERROR: {e}")
    except ImportError as e:
        print(
            f"IMPORT ERROR: {e}. Please ensure utils/config.py and utils/config_loader.py are present."
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        # Clean up dummy files if created
        if os.path.exists("config/redis_config.yaml"):
            os.remove("config/redis_config.yaml")
        if os.path.exists("config"):
            os.rmdir("config")  # Remove dir if empty
