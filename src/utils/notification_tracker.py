import time
import redis
from typing import Dict, List, Optional
from utils.logger import logger
from utils.redis_manager import RedisManager


class NotificationTracker:
    def __init__(self, redis_manager: RedisManager):
        self.redis_manager = redis_manager

    def _get_db(self, env: str) -> redis.Redis:
        return self.redis_manager.redis_db_mapping[env]

    def mark_as_pending(
        self, notification_id: str, env: str, metadata: Dict, delay_seconds: int = 300
    ):
        """
        將通知標記為等待提醒中。
        :param notification_id: 通知唯一 ID
        :param env: 所屬環境
        :param metadata: 裡面包含 thread_ts, recipient 等資訊
        :param delay_seconds: 幾秒後要提醒，預設 5 分鐘
        """
        db = self._get_db(env)
        remind_at = int(time.time()) + delay_seconds

        # ✅ 修正 ZSET key，讓它與 scheduler 使用的 key 一致
        zset_key = f"pending_notifications:{env}"
        db.zadd(zset_key, {notification_id: remind_at})

        # ✅ 設定必要欄位（若外部未提供時自動補上）
        metadata.setdefault("status", "pending")
        metadata.setdefault("reminder_sent_count", 0)
        metadata.setdefault("last_reminder_sent_time", 0)

        db.hset(f"notification_meta:{notification_id}", mapping=metadata)
        logger.info(f"📌 已標記 notification {notification_id} 為待提醒（{delay_seconds} 秒後）")

    def mark_as_resolved(self, notification_id: str, env: str):
        """將通知標記為已處理，從提醒名單中移除，並記錄處理完成的時間"""
        db = self._get_db(env)
        db.zrem("pending_notifications", notification_id)

        key = f"notification_meta:{notification_id}"
        db.hset(key, mapping={"status": "resolved", "resolved_time": int(time.time())})

        logger.info(f"✅ notification {notification_id} 已處理，標記為 resolved")

    def get_overdue_notifications(self, env: str) -> List[str]:
        db = self._get_db(env)
        now = int(time.time())
        return db.zrangebyscore(f"pending_notifications:{env}", 0, now)

    def get_notification_meta(self, notification_id: str, env: str) -> Optional[Dict]:
        """取得通知的 metadata"""
        db = self._get_db(env)
        raw = db.hgetall(f"notification_meta:{notification_id}")
        return raw if raw else None

    def update_notification_meta(self, notification_id, env, update_fields: dict):
        key = f"notification_meta:{notification_id}"
        db = self._get_db(env)
        db.hset(key, mapping=update_fields)
