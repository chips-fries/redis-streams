#!/bin/bash
set -e

cd /app/src

# === Redis ===
echo "🧠 Starting Redis..."
redis-server config/redis.conf --requirepass "$REDIS_PASSWORD" &
sleep 1

# === Scheduler ===
echo "📅 Starting Scheduler..."
poetry run python scheduler.py > logs/scheduler.log 2>&1 &
sleep 0.5

# === Consumer ===
echo "🎧 Starting Consumer..."
poetry run python consumers.py > logs/consumer.log 2>&1 &
sleep 0.5

# === Prefect Submodule ===
echo "🔐 Pulling latest prefect-flow submodule..."
if [[ -z "${GITHUB_ACCESS_TOKEN:-}" ]]; then
  echo "❌ GITHUB_ACCESS_TOKEN is not set! Cannot pull submodule."
  exit 1
fi

git config -f .gitmodules submodule.src/prefect/prefect_flow.url "https://${GITHUB_ACCESS_TOKEN}@github.com/chips-fries/prefect-flow.git"
git submodule sync
git submodule update --init --recursive --remote

# === Prefect Server ===
echo "🧠 Starting Prefect Server..."
poetry run prefect server start > logs/prefect.log 2>&1 &
echo $! > .prefect.pid
sleep 30

# === Prefect Worker ===
echo "🔧 Starting Prefect Worker..."
poetry run prefect worker start --pool default > logs/prefect-worker.log 2>&1 &
echo $! > .prefect-worker.pid

# === Prefect Deployment ===
echo "📦 Registering Prefect Blocks..."
poetry run python src/prefect/register_blocks.py

echo "📡 Applying Prefect Deployments..."
poetry run python src/prefect/apply_all_deployments.py
sleep 1

# === FastAPI ===
echo "🚀 Starting FastAPI API server..."
exec poetry run uvicorn api:app --host 0.0.0.0 --port 10000 --reload
