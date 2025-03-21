from utils.config import API_TOKEN
from fastapi import Header, HTTPException


def verify_token(token: str = Header(None)):
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")
