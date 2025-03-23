import requests
from fastapi import APIRouter, Request, Response, HTTPException
import json
import urllib.parse
from security import verify_slack_signature
from utils.logger import logger
from utils.redis_manager import RedisManager
from utils.config import SLACK_BOT_TOKEN

router = APIRouter()
redis_manager = RedisManager()


@router.post("/slack/actions")
async def handle_slack_interaction(request: Request):
    logger.info("📥 Received Slack interaction")

    body = await request.body()

    if not verify_slack_signature(request, body):
        logger.warning("❌ Invalid Slack signature")
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    data = urllib.parse.parse_qs(body.decode())
    payload = json.loads(data.get("payload", ["{}"])[0])

    action_id = payload.get("actions", [{}])[0].get("action_id")
    value = payload.get("actions", [{}])[0].get("value")  # notification_id
    user = payload.get("user", {}).get("username")

    if not value:
        logger.warning("⚠️ Slack interaction missing value field (notification_id)")
        return Response(status_code=400)

    logger.info(
        f"👤 Slack user '{user}' clicked action '{action_id}' for notification_id: {value}"
    )

    env = None
    redis_db = None

    for mode in redis_manager.allowed_modes:
        candidate_db = redis_manager.redis_db_mapping[mode]
        if candidate_db.exists(f"notification_meta:{value}"):
            env = mode
            redis_db = candidate_db
            break

    if not redis_db:
        logger.warning(f"❌ notification_id {value} not found in any environment")
        return Response(status_code=404, content="Notification not found")

    redis_db.zrem(f"pending_notifications:{env}", value)
    redis_db.delete(f"notification_meta:{value}")

    logger.info(
        f"✅ Removed notification {value} from env '{env}' (via action_id: {action_id})"
    )

    # ========== Update Slack message ==========
    channel_id = payload["channel"]["id"]
    message_ts = payload["message"]["ts"]

    updated_blocks = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *已處理*"}],
        }
    ]

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        "https://slack.com/api/chat.update",
        headers=headers,
        json={"channel": channel_id, "ts": message_ts, "blocks": updated_blocks},
    )

    if not response.ok or not response.json().get("ok"):
        logger.error(f"❌ Failed to update Slack message: {response.text}")
    else:
        logger.info("✅ Slack message updated to '已處理'")

    return Response(status_code=200)


def handle_slack_action(payload: dict):
    channel_id = payload["channel"]["id"]
    message_ts = payload["message"]["ts"]

    # ✅ 更新為已處理的樣式
    updated_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "⏳ 測試提醒功能（勿點擊按鈕）\n\n若 10 秒內未點擊按鈕，將收到提醒訊息",
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *已處理*"}],
        },
    ]

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        "https://slack.com/api/chat.update",
        json={"channel": channel_id, "ts": message_ts, "blocks": updated_blocks},
        headers=headers,
    )

    if not response.json().get("ok"):
        logger.error(f"❌ Failed to update Slack message: {response.text}")
    else:
        logger.info("✅ Slack message updated to '已處理'")
