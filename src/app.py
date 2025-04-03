import uvicorn
from fastapi import FastAPI
from api.routers import reminder  # example router
from api.routers import info
from utils.logger import root_logger


app = FastAPI()
app.include_router(reminder.router)
app.include_router(info.router)


# if __name__ == "__main__":
#     uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
