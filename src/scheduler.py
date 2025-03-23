import time
from routes.internal_reminder import run_reminder_continuous
from utils.logger import logger

logger.debug("🔍 DEBUG 測試訊息 from scheduler")


def loop():
    logger.info("⏳ Reminder loop started.")
    while True:
        try:
            result = run_reminder_continuous()
            logger.debug(f"🔁 Reminder triggered: {result}")
        except Exception as e:
            logger.error(f"❌ Error running reminder: {e}")
        time.sleep(10)


if __name__ == "__main__":
    loop()
