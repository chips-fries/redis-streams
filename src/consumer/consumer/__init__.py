# src/consumer/consumers/__init__.py
# -*- coding: utf-8 -*-

"""Concrete consumer implementations."""

from .slack_sender import SlackMessageSenderConsumer
from .line_sender import LinePushMessageConsumer
from .slack_updater import SlackMessageUpdaterConsumer  # Assuming we create this

# Add others like LineReplyMessageConsumer if needed

__all__ = [
    "SlackMessageSenderConsumer",
    "LinePushMessageConsumer",
    "SlackMessageUpdaterConsumer",
]
