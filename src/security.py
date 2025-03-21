import time
import hmac
import hashlib
from fastapi import Header, HTTPException
from utils.config import API_TOKEN


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
