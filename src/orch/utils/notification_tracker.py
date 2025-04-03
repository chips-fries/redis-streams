# src/orch/utils/notification_tracker.py
# -*- coding: utf-8 -*-

"""
Tracks the resolution state of reminder notifications in Redis.
Used to prevent re-sending already-resolved reminders across platforms.
"""

import logging
from typing import Optional
from redis import Redis
from redis.exceptions import RedisError

# Local imports
try:
    from broker.redis_manager import get_redis_manager
except ImportError:
    raise ImportError(
        "RedisManager not found. Make sure broker/redis_manager.py exists and is working."
    )

logger = logging.getLogger(__name__)

# Key prefix for Redis hash table
NOTIFICATION_HASH_KEY = "reminder_notification_status"


def mark_resolved(notification_id: str) -> bool:
    """Mark a given notification ID as resolved."""
    try:
        redis: Redis = get_redis_manager().redis
        redis.hset(NOTIFICATION_HASH_KEY, notification_id, "resolved")
        logger.debug(f"Notification {notification_id} marked as resolved.")
        return True
    except RedisError as e:
        logger.error(f"Failed to mark notification {notification_id} as resolved: {e}")
        return False


def is_resolved(notification_id: str) -> bool:
    """Check if the notification is already resolved."""
    try:
        redis: Redis = get_redis_manager().redis
        status: Optional[bytes] = redis.hget(NOTIFICATION_HASH_KEY, notification_id)
        return status == b"resolved"
    except RedisError as e:
        logger.error(f"Failed to check notification status for {notification_id}: {e}")
        return False


def clear_all_statuses():
    """(Dev only) Clear all stored notification statuses. Use with caution."""
    try:
        redis: Redis = get_redis_manager().redis
        redis.delete(NOTIFICATION_HASH_KEY)
        logger.warning("All reminder notification statuses have been cleared.")
    except RedisError as e:
        logger.error(f"Failed to clear notification statuses: {e}")


# src/utils/notification_tracker.py
# -*- coding: utf-8 -*-
"""
Utility for tracking the status of reminder notifications (e.g. pending, resolved).
Uses Redis to manage state and prevent duplicate follow-ups.
"""

import time
import logging
from typing import Optional
from broker.redis_manager import RedisManager

logger = logging.getLogger(__name__)

# Redis key prefix
REMINDER_STATUS_PREFIX = "reminder:status:"
FOLLOWUP_ZSET_KEY = "reminder:followup_schedule"

# TTL for resolved status (in seconds, e.g. 7 days)
RESOLVED_TTL = 7 * 24 * 60 * 60  # 7 days


def _get_status_key(reminder_id: str) -> str:
    return f"{REMINDER_STATUS_PREFIX}{reminder_id}"


def mark_as_resolved(reminder_id: str) -> None:
    """
    Mark a reminder as resolved and remove it from follow-up schedule.
    """
    redis = RedisManager()
    status_key = _get_status_key(reminder_id)
    redis.set(status_key, "resolved", ex=RESOLVED_TTL)
    redis.zrem(FOLLOWUP_ZSET_KEY, reminder_id)
    logger.info(f"Marked reminder '{reminder_id}' as resolved and removed from ZSET.")


def is_resolved(reminder_id: str) -> bool:
    """
    Check if a reminder has been resolved.
    """
    redis = RedisManager()
    status = redis.get(_get_status_key(reminder_id))
    return status == b"resolved"


def schedule_followup(reminder_id: str, delay_seconds: int) -> None:
    """
    Schedule a reminder follow-up after the given delay.
    """
    redis = RedisManager()
    score = int(time.time()) + delay_seconds
    redis.zadd(FOLLOWUP_ZSET_KEY, {reminder_id: score})
    logger.info(
        f"Scheduled reminder follow-up for '{reminder_id}' at timestamp {score}."
    )
