import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
NGROK_URL = os.getenv("NGROK_URL", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
