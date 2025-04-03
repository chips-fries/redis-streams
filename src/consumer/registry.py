# src/consumer/registry.py
# -*- coding: utf-8 -*-

"""
Consumer registry for dynamically loading consumer classes based on configuration.
"""

import logging
from typing import Dict, Type, Callable, TypeVar

# Import BaseConsumer using relative path within the package
try:
    from .base.consumer import BaseConsumer
except ImportError:
    # Fallback might be needed if registry is imported before base during certain setups
    logging.getLogger(__name__).warning(
        "Could not import BaseConsumer relative to registry, trying direct."
    )
    from base.consumer import BaseConsumer  # type: ignore


logger = logging.getLogger(__name__)  # Logger name: consumer.registry

CONSUMER_REGISTRY: Dict[str, Type["BaseConsumer"]] = {}  # Use forward reference
T_Consumer = TypeVar("T_Consumer", bound=Type["BaseConsumer"])


def register_consumer(name: str) -> Callable[[T_Consumer], T_Consumer]:
    """Decorator factory for registering concrete Consumer classes derived from BaseConsumer."""

    def decorator(cls: T_Consumer) -> T_Consumer:
        # Ensure the registered class is actually a consumer
        if not issubclass(cls, BaseConsumer):
            raise TypeError(
                f"Class {cls.__name__} must inherit from BaseConsumer to be registered."
            )
        if name in CONSUMER_REGISTRY:
            # Warn if overwriting
            logger.warning(
                f"Overwriting consumer registration for name '{name}'. New: {cls.__module__}.{cls.__name__}"
            )
        logger.debug(
            f"Registering list consumer: '{name}' -> {cls.__module__}.{cls.__name__}"
        )
        CONSUMER_REGISTRY[name] = cls
        return cls

    return decorator
