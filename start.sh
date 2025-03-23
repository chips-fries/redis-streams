#!/bin/bash
set -e

cd /app/src

echo "🧠 Starting Redis..."
redis-server config/redis.conf --requirepass "$REDIS_PASSWORD" &
sleep 1

echo "📅 Starting Scheduler..."
poetry run python scheduler.py > logs/scheduler.log 2>&1 &
sleep 0.5

echo "🎧 Starting Consumer..."
poetry run python consumers.py > logs/consumer.log 2>&1 &
sleep 0.5

echo "🚀 Starting FastAPI API server..."
exec poetry run uvicorn api:app --host 0.0.0.0 --port 10000 --reload
