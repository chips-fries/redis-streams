import time
from utils.redis_manager import RedisManager
from utils.logger import logger
from slack.slack_template import SlackTemplate
from slack.slack_consumer import SlackNotifier
from utils.notification_tracker import NotificationTracker
from utils.config_loader import ConfigLoader


def run_all_env_consumers():
    config = ConfigLoader("config/consumer_config.yaml").config
    pending_notification_reminder_timeout = config["consumer"]["action"][
        "pending_notification_reminder_timeout"
    ]
    redis_manager = RedisManager()
    tracker = NotificationTracker(redis_manager)  # 🔹 NEW
    allowed_envs = redis_manager.allowed_modes

    for env in allowed_envs:
        stream = f"{env}_stream"
        group = f"{stream}_group"
        consumer = f"{stream}_worker"
        db = redis_manager.redis_db_mapping[env]

        try:
            db.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info(f"✅ 已註冊 consumer group `{group}`")
        except Exception:
            logger.info(f"ℹ️ Consumer group `{group}` 已存在")

    logger.info("🎧 Consumer loop started (all environments)")

    while True:
        for env in allowed_envs:
            stream = f"{env}_stream"
            group = f"{stream}_group"
            consumer = f"{stream}_worker"
            db = redis_manager.redis_db_mapping[env]
            notifier = SlackNotifier(env)

            try:
                results = db.xreadgroup(
                    group, consumer, streams={stream: ">"}, count=10, block=5000
                )

                for _, entries in results:
                    for msg_id, msg in entries:
                        try:
                            template = SlackTemplate.from_redis_msg(msg)
                            thread_ts = notifier.send_message(
                                template
                            )  # 🔹 拿到 thread_ts

                            # 🔹 若是 action 類型，才需要追蹤
                            if template.template == "action":
                                tracker.mark_as_pending(
                                    notification_id=template.notification_id,
                                    env=env,
                                    metadata={
                                        "thread_ts": thread_ts,
                                        "recipient": template.recipient,
                                        "template": template.template,
                                    },
                                    delay_seconds=pending_notification_reminder_timeout,
                                )
                                logger.info(
                                    f"📌 登記通知 {template.notification_id} 為待提醒（env={env}）"
                                )

                            db.xack(stream, group, msg_id)
                            logger.info(f"📨 Consumed message {msg_id} from {env}")
                        except Exception as e:
                            logger.error(
                                f"❌ Failed to process message {msg_id} from {env}: {e}"
                            )

            except Exception as e:
                logger.error(f"❌ Redis readgroup error for {env}: {e}")

        time.sleep(1)


if __name__ == "__main__":
    run_all_env_consumers()
