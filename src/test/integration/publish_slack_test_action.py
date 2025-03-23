import time
from slack.slack_template import SlackTemplate
from slack.slack_consumer import SlackNotifier
from utils.redis_manager import RedisManager
from utils.notification_tracker import NotificationTracker

env = "test"
notification_id = "action-" + str(int(time.time() * 1000))

template = SlackTemplate(
    notification_id=notification_id,
    main_text="📢 這是一則互動通知",
    sub_text="有按鈕，5 分鐘內未處理會補提醒",
    template="action",
    recipient="@bacon",
)

redis_manager = RedisManager()
notifier = SlackNotifier(env)
tracker = NotificationTracker(redis_manager)

# 發送主訊息
thread_ts = notifier.send_message(template)

# 登記追蹤
tracker.mark_as_pending(
    notification_id,
    env,
    {
        "recipient": template.recipient,
        "template": template.template,
        "thread_ts": thread_ts,
    },
)

# 同時寫入 Redis Stream（模擬 Producer）
redis_db = redis_manager.redis_db_mapping[env]
redis_db.xadd(f"{env}_stream", template.to_redis_msg())

print(f"✅ 已發送互動通知 notification_id={notification_id}")
