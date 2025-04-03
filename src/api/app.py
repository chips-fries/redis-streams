import uvicorn
from fastapi import FastAPI
from api.routers import reminder  # example router
from api.routers import info

app = FastAPI()
app.include_router(reminder.router)
app.include_router(info.router)


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
