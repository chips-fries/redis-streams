# src/orch/models/reminders.py
# -*- coding: utf-8 -*-

"""
Pydantic models defining the data structure for Reminder objects and their channel-specific states.
Includes validators moved to appropriate models for clarity and correctness.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Union, Mapping, Type

# Ensure pydantic is installed: poetry add pydantic
try:
    from pydantic import BaseModel, Field, field_validator, ValidationError
except ImportError:
    print("ERROR: pydantic package is required. Install using 'poetry add pydantic'")
    raise

# Assume logger is configured externally
logger = logging.getLogger(__name__)  # Logger name: orch.models.reminders

# --- Constants for Reminder Status ---
REMINDER_STATUS_PENDING = "pending"
REMINDER_STATUS_RESOLVED = "resolved"
REMINDER_STATUS_ERROR = "error"

CHANNEL_STATUS_INITIAL = "initial"
CHANNEL_STATUS_SENT = "sent"
CHANNEL_STATUS_FOLLOWUP_SENT = "followup_sent"
CHANNEL_STATUS_ERROR = "error"
CHANNEL_STATUS_RESOLVED = "resolved"


class ReminderChannelState(BaseModel):
    """
    Represents the state and associated data for a reminder within a *single*
    delivery channel (e.g., 'slack', 'line'). Stored within the 'channels' dict
    of the main Reminder state in Redis.
    """

    # --- Status ---
    status: str = Field(
        default=CHANNEL_STATUS_INITIAL,
        description="Processing status for this specific channel.",
    )
    # --- Platform Specific Data ---
    platform_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Platform-specific identifiers (e.g., Slack ts/channel).",
    )
    # --- Scheduling & Error Tracking ---
    next_followup_time: Optional[float] = Field(
        default=None,
        description="[Timestamp] Next scheduled check/trigger time for this channel's ZSET.",
    )
    last_error: Optional[str] = Field(
        default=None, description="Last failed send error message for this channel."
    )
    error_count: int = Field(
        default=0, ge=0, description="Consecutive send failures for this channel."
    )
    last_reminder_time: Optional[float] = Field(
        default=None,
        description="[Timestamp] Last successful follow-up sent to this channel.",
    )

    # --- Pydantic Model Configuration ---
    model_config = {"extra": "ignore", "frozen": False}

    # --- Validator for ChannelState numeric fields ---
    @field_validator(
        "next_followup_time",
        "last_reminder_time",
        "error_count",  # error_count is validated here
        mode="before",  # Apply before standard Pydantic type coercion
    )
    @classmethod
    def parse_channel_numeric_fields(
        cls, value: Any, info: Optional[Any] = None
    ) -> Optional[Union[int, float]]:
        """
        Safely converts numeric fields likely stored as strings in Redis
        within the ChannelState dictionary. Handles None/empty strings.
        Converts error_count to int, others to float.
        """
        if value is None or value == "":
            return None  # Treat empty string/None as None

        field_name = (
            info.field_name if info else None
        )  # Get field name if possible (Pydantic v2+)

        try:
            num_val = float(value)  # Attempt to convert to float first
            # If the target field is error_count and it's a whole number, convert to int
            if field_name == "error_count" and num_val.is_integer():
                return int(num_val)
            # Otherwise, return as float (for timestamps) or int if it's naturally int
            elif num_val.is_integer():
                # Check if original was string int to avoid float conversion if possible
                if isinstance(value, str) and "." not in value and value.isdigit():
                    return int(num_val)
            return num_val  # Return float for timestamps etc.
        except (ValueError, TypeError):
            # Log warning if conversion fails
            logger.warning(
                f"ChannelState: Could not convert value '{repr(value)}' for field '{field_name}' to number."
            )
            # Raise ValueError to indicate validation failure
            raise ValueError(f"Invalid numeric value for {field_name}: '{repr(value)}'")


class Reminder(BaseModel):
    """
    Represents the complete state and definition of a Reminder notification.
    Stored as a Redis Hash (key: reminder:state:{notification_id}).
    """

    # --- Identifying and Content Fields ---
    notification_id: str = Field(..., min_length=1)
    template_name: str = Field(..., min_length=1)
    recipient: str = Field(..., min_length=1)
    main_text: str = Field(..., min_length=1)
    sub_text: Optional[str] = None
    action_text: Optional[str] = "Acknowledge"
    timeout_seconds: int = Field(..., gt=0)  # Expect int after parsing
    max_attempts: Optional[int] = Field(
        default=None, gt=0
    )  # Expect int/None after parsing
    initial_settings: Dict[str, Any] = Field(default_factory=dict)

    # --- Lifecycle and State Fields ---
    global_status: str = Field(default=REMINDER_STATUS_PENDING)
    created_at: float = Field(default_factory=time.time)  # Expect float after parsing
    resolved_at: Optional[float] = None  # Expect float/None after parsing
    resolved_by_channel: Optional[str] = None

    # --- Channel-Specific States ---
    # Pydantic will use ReminderChannelState's validators for items in this dict
    channels: Dict[str, ReminderChannelState] = Field(default_factory=dict)

    # --- Model Config ---
    model_config = {"extra": "allow", "frozen": False, "validate_assignment": True}

    # --- Validators for Reminder model's OWN fields ---
    @field_validator(  # Validate only top-level fields here
        "created_at", "resolved_at", "timeout_seconds", "max_attempts", mode="before"
    )
    @classmethod
    def parse_reminder_numeric_fields(
        cls, value: Any, info: Optional[Any] = None
    ) -> Optional[Union[int, float]]:
        """Safely converts top-level numeric fields from Redis strings."""
        if value is None or value == "":
            return None
        field_name = info.field_name if info else None
        try:
            num_val = float(value)
            # Convert timeout/attempts to int if they represent whole numbers
            if (
                field_name in ["timeout_seconds", "max_attempts"]
                and num_val.is_integer()
            ):
                return int(num_val)
            return num_val  # Keep timestamps as float
        except (ValueError, TypeError):
            logger.warning(
                f"Reminder: Could not convert value '{repr(value)}' for field '{field_name}' to number."
            )
            raise ValueError(f"Invalid numeric value for {field_name}: '{repr(value)}'")

    # Validator to parse the 'channels' JSON string - remains the same
    @field_validator("channels", mode="before")
    @classmethod
    def parse_channels_json(cls, value: Any) -> Union[Dict[str, Any], Any]:
        """Parses 'channels' JSON string from Redis into a dict."""
        if isinstance(value, (str, bytes)):
            try:
                json_str = value.decode("utf-8") if isinstance(value, bytes) else value
                if not json_str:
                    return {}
                parsed_dict = json.loads(json_str)
                if not isinstance(parsed_dict, dict):
                    raise ValueError("Not dict")
                # Pydantic now automatically validates dict values against ReminderChannelState
                return parsed_dict
            except Exception as e:
                raise ValueError(f"Invalid JSON for channels: {e}") from e
        elif isinstance(value, dict):
            return value
        elif value is None:
            return {}
        raise TypeError(f"Expected dict, JSON str/bytes, or None. Got: {type(value)}")

    # --- Helper method to prepare data for Redis ---
    def to_redis_hash(self) -> Dict[str, str]:
        """Converts model to dict suitable for Redis HSET (all string values)."""
        # (Implementation remains the same as previously provided)
        model_dict = self.model_dump(mode="python", exclude_none=True)
        if "channels" in model_dict and isinstance(model_dict["channels"], dict):
            channels_to_serialize = {
                # Use model_dump on the ChannelState instances within the dict
                ch_name: ch_state.model_dump(mode="python", exclude_none=True)
                for ch_name, ch_state in model_dict["channels"].items()
                # Add check if ch_state is actually a model instance? Pydantic should handle it.
            }
            try:
                model_dict["channels"] = json.dumps(channels_to_serialize)
            except TypeError as e:
                logger.error(
                    f"Failed JSON serialization NID {self.notification_id}: {e}"
                )
                del model_dict["channels"]
        redis_map = {str(k): str(v) for k, v in model_dict.items() if v is not None}
        return redis_map


# --- Parsing Helper Function ---
def parse_reminder_from_redis(
    raw_redis_data: Optional[Mapping[Union[bytes, str], Union[bytes, str]]]
) -> Optional[Reminder]:
    """Safely parses raw HGETALL data (bytes or str) into a Reminder model."""
    # (Implementation remains the same as previously provided)
    if not raw_redis_data:
        return None
    decoded_data: Dict[str, str] = {}
    nid = "UNKNOWN_NID"
    try:
        for k, v in raw_redis_data.items():
            key_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            value_str = v.decode("utf-8") if isinstance(v, bytes) else str(v)
            decoded_data[key_str] = value_str
        nid = decoded_data.get("notification_id", "UNKNOWN_NID")
        # Pydantic V2 handles nested validation during __init__ when dict passed to channels
        state = Reminder(**decoded_data)
        return state
    except (UnicodeDecodeError, ValidationError) as e:
        logger.error(
            f"Failed parse raw Redis data (NID: {nid}): {e.__class__.__name__}: {e}",
            exc_info=False,
        )
        logger.debug(f"Raw Redis keys NID {nid}: {list(raw_redis_data.keys())}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error parsing raw Redis data (NID: {nid}): {e}")
        return None
