import traceback
from fastapi import APIRouter, Request, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional, List
from utils.settings import ENV
from orch.flows.templates.send_reminder_message_flow import send_reminder_message_flow
from orch.utils.reminder_resolver import resolve_reminder
import json

router = APIRouter(prefix="/api/v1")


class ReminderRequest(BaseModel):
    platforms: List[str] = ["slack", "line"]
    main_text: str = "Please confirm action."
    sub_text: Optional[str] = None
    mention_aliases: Optional[List[str]] = ["bacon"]
    initial_delay_seconds: Optional[int] = 600
    trigger_source: Optional[str] = "api_reminder_handler"


@router.post("/reminder")
async def reminder_handler(request: ReminderRequest):
    """
    API Endpoint to send a reminder message to supported platforms.
    Wraps the request into flow's expected format.
    """
    targets = []
    sub_text = (
        request.sub_text + "\n時間: {{TIME}}" if request.sub_text else "時間: {{TIME}}"
    )

    if "slack" in request.platforms:
        targets.append(
            {
                "platform": "slack",
                "template_name": "SlackReminderTemplate",
                "context_data": {
                    "destination_alias": ENV,
                    "mention_aliases": request.mention_aliases,
                    "main_text": request.main_text,
                    "sub_text": sub_text,
                    "initial_delay_seconds": request.initial_delay_seconds,
                },
            }
        )

    if "line" in request.platforms:
        targets.append(
            {
                "platform": "line",
                "template_name": "LineReminderTemplate",
                "context_data": {
                    "destination_alias": "bacon_dm",
                    "mention_aliases": request.mention_aliases,
                    "main_text": request.main_text,
                    "sub_text": sub_text,
                    "initial_delay_seconds": request.initial_delay_seconds,
                },
            }
        )

    await send_reminder_message_flow(
        targets=targets,
        message_context={"source": "api_reminder_handler"},
        trigger_source=request.trigger_source or "api_reminder_handler",
    )
    return {"status": "reminder message flow triggered", "platforms": request.platforms}


@router.post("/reminder/action")
async def reminder_action_handler(payload: str = Form(...)):
    """
    Endpoint triggered by Slack button action.
    """
    try:
        data = json.loads(payload)
        action = data.get("actions", [{}])[0]
        reminder_id = action.get("value")
        channel_id = data.get("channel", {}).get("id")
        message_ts = data.get("message", {}).get("ts")

        if not all([reminder_id, channel_id, message_ts]):
            return PlainTextResponse("Missing required action data", status_code=400)

        await resolve_reminder(
            reminder_id=reminder_id,
            slack_update={"channel": channel_id, "ts": message_ts},
        )
        return PlainTextResponse("OK")

    except Exception as e:
        traceback.print_exc()
        return PlainTextResponse(f"Error: {e}", status_code=500)
