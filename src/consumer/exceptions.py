# src/consumer/exceptions.py
# -*- coding: utf-8 -*-

"""
Custom exceptions for the consumer package.
"""


class ConsumerError(Exception):
    """Base exception for consumer-related errors defined in this module."""

    pass


class UnrecoverableError(ConsumerError):
    """
    Indicates an error primarily due to invalid or unprocessable task data,
    making retries futile. The task should typically be discarded (and potentially logged or sent to a DLQ).
    Examples: Malformed JSON, missing critical fields in parsed data, invalid recipient ID format.
    """

    pass


class TransientError(ConsumerError):
    """
    Indicates a temporary error, usually related to external services or network issues,
    suggesting a retry might succeed. Consumers implementing retry logic should catch this.
    Examples: Network timeout connecting to Slack/Line, API rate limiting, temporary database lock.
    """

    pass


# Note: RedisConfigurationError can be imported from broker.redis_manager if needed elsewhere,
# or defined here if consumers have specific configuration needs beyond Redis.
