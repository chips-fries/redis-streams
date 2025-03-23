from fastapi import APIRouter
from utils.redis_manager import RedisManager
from utils.notification_tracker import NotificationTracker
from slack.slack_consumer import SlackNotifier
from utils.config_loader import ConfigLoader
from utils.logger import logger
import time

router = APIRouter()


@router.post("/internal/reminder/run_once")
def run_reminder_once():
    redis_manager = RedisManager()
    tracker = NotificationTracker(redis_manager)

    total_triggered = 0

    for env in redis_manager.allowed_modes:
        notifier = SlackNotifier(env)
        overdue_ids = tracker.get_overdue_notifications(env)

        for notification_id in overdue_ids:
            meta = tracker.get_notification_meta(notification_id, env)

            if not meta:
                continue

            recipient = meta.get("recipient", "")
            thread_ts = meta.get("thread_ts", "")
            template = meta.get("template", "action")

            if template == "action":
                notifier.send_reminder(
                    thread_ts=thread_ts, text=f"⏰ [Reminder] {recipient} 快處理！"
                )
                logger.info(
                    f"🔔 Reminder sent to {recipient} (notification_id={notification_id}, env={env})"
                )

            tracker.mark_as_resolved(notification_id, env)
            total_triggered += 1

    return {"status": "success", "reminders_sent": total_triggered}


@router.post("/internal/reminder/run_continuous")
def run_reminder_continuous():
    config = ConfigLoader("config/consumer_config.yaml").config
    pending_notification_reminder_timeout = config["consumer"]["action"][
        "pending_notification_reminder_timeout"
    ]

    redis_manager = RedisManager()
    tracker = NotificationTracker(redis_manager)
    total_triggered = 0

    for env in redis_manager.allowed_modes:
        notifier = SlackNotifier(env)
        overdue_ids = tracker.get_overdue_notifications(env)
        db = tracker._get_db(env)
        zset_key = f"pending_notifications:{env}"

        for notification_id in overdue_ids:
            current_time = int(time.time())
            meta = tracker.get_notification_meta(notification_id, env)
            if not meta:
                continue

            if meta.get("status") == "resolved":
                continue

            reminder_sent_count = int(meta.get("reminder_sent_count", 0))
            last_reminder_sent_time = int(meta.get("last_reminder_sent_time", 0))
            recipient = meta.get("recipient", "")
            thread_ts = meta.get("thread_ts", "")
            template = meta.get("template", "action")

            logger.debug(
                {
                    "env": env,
                    "id": notification_id,
                    "reminder_sent_count": reminder_sent_count,
                    "last_reminder_sent_time": last_reminder_sent_time,
                    "current_time": current_time,
                    "time_diff": current_time - last_reminder_sent_time,
                }
            )

            lock_key = f"reminder_lock:{notification_id}"
            lock_acquired = db.set(lock_key, "1", nx=True, ex=2)

            if not lock_acquired:
                continue

            if (
                current_time - last_reminder_sent_time
                >= pending_notification_reminder_timeout
            ):
                if template == "action":
                    # ✅ 發送提醒，取得 success 和 error 回傳值
                    success, error = notifier.send_reminder(
                        thread_ts=thread_ts,
                        text=f"⏰ [Reminder #{reminder_sent_count + 1}] {recipient} 快處理！",
                    )

                    if not success:
                        logger.warning(
                            f"⚠️ Slack 發送失敗 notification_id={notification_id}, error={error}"
                        )
                        continue  # ❌ 不更新 reminder_sent_count，也不排下一輪

                    logger.info(
                        f"🔔 Reminder #{reminder_sent_count + 1} sent to {recipient} "
                        f"(notification_id={notification_id}, env={env})"
                    )

                    # ✅ 成功才更新 metadata 與重新排程
                    tracker.update_notification_meta(
                        notification_id,
                        env,
                        {
                            "reminder_sent_count": reminder_sent_count + 1,
                            "last_reminder_sent_time": current_time,
                        },
                    )

                    remind_at = current_time + pending_notification_reminder_timeout
                    db.zadd(zset_key, {notification_id: remind_at})
                    logger.debug(
                        f"⏭️  Next reminder for {notification_id} scheduled at {remind_at} "
                        f"(in {pending_notification_reminder_timeout} sec)"
                    )

                    total_triggered += 1

    return {"status": "success", "reminders_sent": total_triggered}
