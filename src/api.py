from fastapi import FastAPI, Header, HTTPException
from security import verify_token
from utils.redis_manager import RedisManager
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from utils.logger import logger

app = FastAPI()
redis_manager = RedisManager()


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # Log the error or send it to external services like Slack or Sentry
    logger.error(f"❌ Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# Get status of a specific Redis environment (e.g., dev, uat, prod)
@app.get("/status/{env}")
def get_env_status(env: str, token: str = Header(None)):
    verify_token(token)
    return redis_manager.get_streams_info(env)


# Get status of all Redis environments
@app.get("/status")
def get_all_status(token: str = Header(None)):
    verify_token(token)
    return redis_manager.get_streams_info()


# Publish a message to a specific environment's Redis stream
@app.post("/publish/{env}")
def publish_message(
    env: str,
    message: str,
    token: str = Header(None),
    x_timestamp: str = Header(None),
    x_signature: str = Header(None),
):
    verify_token(token, x_timestamp, x_signature)
    result = redis_manager.send_message(env, message)
    if result:
        return {"status": "success", "message_id": result}
    else:
        raise HTTPException(status_code=400, detail="Publish failed")


# Clear all messages (new + pending) in a specific environment
@app.delete("/clear/{env}")
def clear_env_stream(env: str, token: str = Header(None)):
    verify_token(token)
    return redis_manager.clear_streams(env)


# Clear all messages in all environments
@app.delete("/clear")
def clear_all_streams(token: str = Header(None)):
    verify_token(token)
    return redis_manager.clear_streams()
