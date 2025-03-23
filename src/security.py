import time
import hmac
import hashlib
from fastapi import Header, HTTPException
from utils.config import API_TOKEN, SLACK_SIGNING_SECRET
from fastapi import Request
from utils.logger import logger


def verify_token(
    token: str = Header(None),
    x_timestamp: str = Header(None),
    x_signature: str = Header(None),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    try:
        ts = int(x_timestamp)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid timestamp")

    # 時間差限制（例：60 秒內）
    if abs(time.time() - ts) > 60:
        raise HTTPException(status_code=400, detail="Request expired")

    # 重算 HMAC
    expected_sig = hmac.new(
        token.encode(), x_timestamp.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, x_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")


# def verify_slack_signature(request: Request, body: str):
#     timestamp = request.headers["x-slack-request-timestamp"]
#     slack_signature = request.headers["x-slack-signature"]

#     # 防止重放攻擊
#     if abs(time.time() - int(timestamp)) > 60 * 500:
#         return False

#     basestring = f"v0:{timestamp}:{body}".encode()
#     my_signature = 'v0=' + hmac.new(
#         SLACK_SIGNING_SECRET.encode(), basestring, hashlib.sha256
#     ).hexdigest()

#     return hmac.compare_digest(my_signature, slack_signature)


def verify_slack_signature(request: Request, body: bytes) -> bool:
    # SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
    if not SLACK_SIGNING_SECRET:
        logger.warning("⚠️ SLACK_SIGNING_SECRET is not set")
        return False

    timestamp = request.headers.get("x-slack-request-timestamp")
    slack_signature = request.headers.get("x-slack-signature")

    if not timestamp or not slack_signature:
        return False

    # 防止 replay 攻擊
    if abs(time.time() - int(timestamp)) > 60 * 500:
        logger.warning("⚠️ Slack request timestamp too old")
        return False

    basestring = f"v0:{timestamp}:{body.decode()}".encode("utf-8")
    my_signature = (
        "v0="
        + hmac.new(
            SLACK_SIGNING_SECRET.encode("utf-8"), basestring, hashlib.sha256
        ).hexdigest()
    )

    if not hmac.compare_digest(my_signature, slack_signature):
        logger.warning("⚠️ Slack signature mismatch")
        logger.debug(f"Expected: {my_signature}")
        logger.debug(f"Received: {slack_signature}")
        return False

    return True
