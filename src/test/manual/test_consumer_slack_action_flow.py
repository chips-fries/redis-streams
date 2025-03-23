import time
from slack.slack_template import SlackTemplate
from utils.redis_manager import RedisManager

env = "test"
notification_id = "text-" + str(int(time.time() * 1000))

template = SlackTemplate(
    notification_id=notification_id,
    main_text="📢 這是一則純文字通知",
    sub_text="沒有按鈕，不會註冊提醒",
    template="action",
    recipient="@bacon",
    status="info",
)

# 只寫入 Redis Stream，交給 Consumer 處理
redis_manager = RedisManager()
redis_db = redis_manager.redis_db_mapping[env]
redis_db.xadd(f"{env}_stream", template.to_redis_msg())

print(f"✅ 已寫入 Redis Stream: {env}_stream notification_id={notification_id}")
