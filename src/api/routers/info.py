from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from utils.settings import ENV

from orch.flows.templates.send_info_message_flow import send_info_message_flow

router = APIRouter(prefix="/api/v1")


class InfoRequest(BaseModel):
    platforms: list[str] = ["slack", "line"]
    main_text: str = "Hello, World!"
    sub_text: str = None
    mention_aliases: Optional[List[str]] = ["bacon"]


@router.post("/info")
async def info_handler(request: InfoRequest):
    """
    API Endpoint to send a simple info message to all supported platforms.
    Automatically wraps request into the flow's expected format.
    """
    targets = []
    sub_text = (
        f"{request.sub_text}\n時間: {{TIME}}" if request.sub_text else "時間: {{TIME}}"
    )

    if "slack" in request.platforms:
        targets.append(
            {
                "platform": "slack",
                "template_name": "SlackInfoTemplate",
                "context_data": {
                    "destination_alias": f"{ENV}_channel",
                    "mention_aliases": request.mention_aliases,
                    "main_text": request.main_text,
                    "sub_text": sub_text,
                },
            }
        )

    if "line" in request.platforms:
        targets.append(
            {
                "platform": "line",
                "template_name": "LineInfoTemplate",
                "context_data": {
                    "destination_alias": "bacon_dm",
                    "mention_aliases": request.mention_aliases,
                    "main_text": request.main_text,
                    "sub_text": sub_text,
                },
            }
        )

    await send_info_message_flow(
        targets=targets,
        message_context={"source": "api_info_handler"},
        trigger_source="api_info_handler",
    )
    return {"status": "info message flow triggered"}
