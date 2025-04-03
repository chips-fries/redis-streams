import os
from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("ENV")
API_TOKEN = os.getenv("API_TOKEN")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
NGROK_URL = os.getenv("NGROK_URL", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
PREFECT_PROFILES_PATH = os.getenv("PREFECT_PROFILES_PATH")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
