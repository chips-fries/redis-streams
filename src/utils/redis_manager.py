import redis
from typing import Optional

from utils.config_loader import ConfigLoader
from utils.logger import logger
from utils.config import REDIS_PASSWORD


class RedisManager:
    """Manages Redis connections, initializes all streams and consumer groups"""

    def __init__(self):
        """Load YAML configuration and initialize Redis clients"""
        self.config_loader = ConfigLoader("config/redis_config.yaml")

        # Load Redis config
        self.redis_host = self.config_loader.config["redis"]["host"]
        self.redis_port = self.config_loader.config["redis"]["port"]
        self.allowed_modes = self.config_loader.config["redis"]["allowed_modes"]
        self.db_mapping = self.config_loader.config["redis"]["db_mapping"]
        self.decode_responses = self.config_loader.config["redis"]["decode_responses"]
        self.streams = {env: f"{env}_stream" for env in self.allowed_modes}

        # Connect to Redis for each mode
        self.redis_db_mapping = {
            mode: redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.db_mapping[mode],
                decode_responses=self.decode_responses,
                password=REDIS_PASSWORD,
            )
            for mode in self.allowed_modes
        }

        # Registered stream subscribers (callbacks)
        self.subscribers = {}

        # Ensure all streams exist
        self._initialize_streams()

    def _initialize_streams(self):
        """Initialize all Redis streams and their consumer groups"""
        for env, stream_name in self.streams.items():
            consumer_group = f"{stream_name}_group"
            redis_db = self.redis_db_mapping[env]
            try:
                redis_db.xinfo_stream(stream_name)
                logger.debug(
                    f"ℹ️ Stream `{stream_name}` already exists, skipping creation"
                )
            except redis.exceptions.ResponseError:
                try:
                    redis_db.xgroup_create(
                        stream_name, consumer_group, id="0", mkstream=True
                    )
                    logger.info(
                        f"✅ Created stream `{stream_name}` and consumer group `{consumer_group}`"
                    )
                except redis.exceptions.ResponseError:
                    logger.warning(f"⚠️ Failed to create stream `{stream_name}`")

    def register_subscribers(self, callback):
        """Register a callback function for each environment's stream"""
        for env, _ in self.streams.items():
            if env not in self.streams:
                logger.error(f"❌ Invalid environment: {env}")
                return
            self.subscribers[env] = callback

    def listen(self):
        """Continuously listen to all subscribed Redis streams and trigger the corresponding callbacks"""
        while True:
            for env, callback in self.subscribers.items():
                stream_name = self.streams[env]
                consumer_group = f"{stream_name}_group"
                redis_db = self.redis_db_mapping[env]

                # Ensure consumer group exists
                try:
                    redis_db.xinfo_groups(stream_name)
                except redis.exceptions.ResponseError:
                    logger.warning(
                        f"⚠️ Consumer group `{consumer_group}` does not exist, creating..."
                    )
                    redis_db.xgroup_create(
                        stream_name, consumer_group, id="0", mkstream=True
                    )

                # Read messages in batch (count=10 improves performance)
                messages = redis_db.xreadgroup(
                    groupname=consumer_group,
                    consumername=f"{stream_name}_worker",
                    streams={stream_name: ">"},
                    count=10,
                    block=5000,
                )

                for _, msgs in messages:
                    for msg_id, msg_data in msgs:
                        callback(msg_data)
                        redis_db.xack(
                            stream_name, consumer_group, msg_id
                        )  # Acknowledge message

    def send_message(self, env: str, message: str):
        """Send a message to the specified environment's Redis stream"""
        if env not in self.streams:
            logger.error(f"❌ Invalid environment: {env}")
            return False
        stream_name = self.streams[env]
        redis_db = self.redis_db_mapping[env]
        return redis_db.xadd(stream_name, {"message": message})

    def get_streams_info(self, env: Optional[str] = None):
        """
        Get the status of Redis streams.
        - If `env` is provided, only return info for that environment.
        - If `env` is None, return info for all configured environments.
        """
        streams_info = {}

        if env:
            if env not in self.redis_db_mapping:
                logger.error(f"❌ Invalid environment: {env}")
                return None
            redis_db = self.redis_db_mapping[env]
            streams_info[env] = self._get_db_streams_info(redis_db=redis_db)
        else:
            for env, redis_db in self.redis_db_mapping.items():
                streams_info[env] = self._get_db_streams_info(redis_db=redis_db)

        return streams_info

    def _get_db_streams_info(self, redis_db):
        """Return detailed stream info for a single Redis DB, including consumer info"""
        db_streams_info = {}
        stream_list = [
            key for key in redis_db.scan_iter() if str(redis_db.type(key)) == "stream"
        ]

        for stream in stream_list:
            try:
                total_messages = redis_db.xlen(stream)
                consumer_group = f"{stream}_group"

                # Get number of pending messages
                try:
                    pending_info = redis_db.xpending(stream, consumer_group)
                    pending_count = pending_info["pending"] if pending_info else 0
                except redis.exceptions.ResponseError:
                    pending_count = 0

                # First & last message
                last_entry = redis_db.xrevrange(stream, count=1)
                last_entry_data = last_entry[0] if last_entry else None

                first_entry = redis_db.xrange(stream, count=1)
                first_entry_data = first_entry[0] if first_entry else None

                # Consumer group details
                consumers = []
                try:
                    consumer_info = redis_db.xinfo_consumers(stream, consumer_group)
                    for c in consumer_info:
                        consumers.append(
                            {
                                "name": c["name"],
                                "pending": c["pending"],
                                "idle": c["idle"],
                            }
                        )
                except redis.exceptions.ResponseError:
                    # No group or consumers yet
                    consumers = []

                db_streams_info[stream] = {
                    "total_messages": total_messages,
                    "pending_messages": pending_count,
                    "first_entry": first_entry_data,
                    "last_entry": last_entry_data,
                    "consumers": consumers,
                }

            except redis.exceptions.ResponseError:
                logger.warning(f"⚠️ Unable to retrieve info for stream `{stream}`")

        return db_streams_info

    def clear_streams(self, env: Optional[str] = None):
        """
        Clear all messages (new and pending) from Redis streams.
        - If `env` is None, clear streams across all environments.
        - If `env` is specified, only clear streams for that environment.
        :return: Dict mapping environment to list of cleared stream names
        """
        cleared = {}
        env_list = [env] if env else self.redis_db_mapping.keys()

        for env_name in env_list:
            if env_name not in self.redis_db_mapping:
                logger.warning(f"⚠️ Invalid environment: {env_name}")
                continue

            redis_db = self.redis_db_mapping[env_name]
            removed_streams = []

            for stream in [
                key
                for key in redis_db.scan_iter()
                if str(redis_db.type(key)) == "stream"
            ]:
                try:
                    # Clear pending messages
                    groups = redis_db.xinfo_groups(stream)
                    for group in groups:
                        group_name = group["name"]
                        pending_messages = redis_db.xpending_range(
                            stream, group_name, "-", "+", count=1000
                        )
                        for msg in pending_messages:
                            redis_db.xack(stream, group_name, msg["message_id"])
                            redis_db.xdel(stream, msg["message_id"])

                    # Clear new messages (not yet assigned to any group)
                    messages = redis_db.xrange(stream, "-", "+")
                    for msg_id, _ in messages:
                        redis_db.xdel(stream, msg_id)

                    removed_streams.append(stream)
                    logger.info(
                        f"✅ Cleared all new and pending messages in stream `{stream}` of environment `{env_name}`"
                    )
                except Exception as e:
                    logger.error(
                        f"❌ Failed to clear stream `{stream}` in environment `{env_name}`: {e}"
                    )

            cleared[env_name] = removed_streams

        return cleared
