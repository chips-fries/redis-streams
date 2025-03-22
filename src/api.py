from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from utils.redis_manager import RedisManager
from utils.logger import logger
from security import verify_token

app = FastAPI()
redis_manager = RedisManager()


# === Exception Handlers ===
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"❌ Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# === Header Auth Class ===
class AuthHeader:
    def __init__(
        self,
        token: str = Header(None),
        x_timestamp: str = Header(None),
        x_signature: str = Header(None),
    ):
        verify_token(token, x_timestamp, x_signature)


# === Routes ===
@app.get("/status")
def get_all_status(_: AuthHeader = Depends()):
    return redis_manager.get_streams_info()


@app.get("/status/{env}")
def get_env_status(env: str, _: AuthHeader = Depends()):
    return redis_manager.get_streams_info(env)


@app.post("/publish/{env}")
def publish_message(env: str, message: str, _: AuthHeader = Depends()):
    result = redis_manager.send_message(env, message)
    if not result:
        raise HTTPException(400, detail="Publish failed")
    return {"status": "success", "message_id": result}


@app.delete("/clear")
def clear_all(_: AuthHeader = Depends()):
    return redis_manager.clear_streams()


@app.delete("/clear/{env}")
def clear_env(env: str, _: AuthHeader = Depends()):
    return redis_manager.clear_streams(env)
