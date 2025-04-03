# src/consumer/__init__.py
# -*- coding: utf-8 -*-

"""
Consumer package for processing background tasks from Redis Lists.
Provides base classes, specific consumer implementations, and registry utilities.
"""

# Import base components first
from .base.exceptions import ConsumerError, UnrecoverableError, TransientError
from .base.consumer import BaseConsumer

# Import registry and decorator
from .registry import CONSUMER_REGISTRY, register_consumer

# Import concrete consumers to ensure they get registered when this package is imported
# The act of importing the module where '@register_consumer' is used triggers registration.
try:
    from .consumer.slack_sender import SlackMessageSenderConsumer
    from .consumer.line_sender import LinePushMessageConsumer
    from .consumer.slack_updater import SlackMessageUpdaterConsumer

    # Import others as they are created...
except ImportError as e:
    # Log or print warning if consumers can't be imported - might indicate missing deps
    import logging

    logging.getLogger(__name__).warning(
        f"Could not import all concrete consumers: {e}. Registration might be incomplete."
    )


# Define __all__ for explicit public interface of the package
__all__ = [
    # Base classes and exceptions
    "BaseConsumer",
    "ConsumerError",
    "UnrecoverableError",
    "TransientError",
    # Registry and decorator
    "CONSUMER_REGISTRY",
    "register_consumer",
    # Concrete Consumers (List them explicitly)
    "SlackMessageSenderConsumer",
    "LinePushMessageConsumer",
    "SlackMessageUpdaterConsumer",
    # Add other concrete consumer classes here
]
