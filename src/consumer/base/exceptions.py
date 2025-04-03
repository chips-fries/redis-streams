# src/consumers/base/exceptions.py


class ConsumerError(Exception):
    """Base exception for all consumer-related errors within this module."""

    pass


class UnrecoverableError(ConsumerError):
    """
    Indicates an error occurred due to the message content itself or a permanent
    platform issue, which is considered non-retriable.
    Messages causing this error should ideally be moved to the DLQ and then acknowledged.
    Example: Malformed message data, invalid recipient format, missing mandatory fields,
             platform rejecting message due to invalid permissions that won't change.
    """

    pass


class TransientError(ConsumerError):
    """
    Indicates an error that might be resolved by retrying the message processing later.
    This is typically due to external factors like network issues, temporary
    unavailability of dependent services, or rate limiting.
    Messages causing this error should NOT be acknowledged immediately, allowing Redis
    (or the consumer logic itself) to potentially redeliver or retry them.
    Example: Temporary network issue communicating with Slack/Line, API rate limiting,
             database connection timeout during processing.
    """

    pass


class ConfigurationError(ConsumerError):
    """
    Indicates an error related to the consumer's setup, configuration,
    or environment, rather than a specific message. This usually prevents
    a consumer worker from initializing or running correctly and requires
    manual intervention (fixing config, environment variables, etc.).
    Example: Missing required environment variable (API key), invalid YAML config value,
             failure to connect to Redis during startup due to bad credentials,
             required Python package missing.
    """

    pass
