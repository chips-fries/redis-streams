# src/consumer/base/__init__.py
# -*- coding: utf-8 -*-

"""Base components for consumers."""

from consumer.base.exceptions import ConsumerError, UnrecoverableError, TransientError
from consumer.base.consumer import BaseConsumer

__all__ = [
    "ConsumerError",
    "UnrecoverableError",
    "TransientError",
    "BaseConsumer",
]
