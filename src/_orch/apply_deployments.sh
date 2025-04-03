#!/bin/bash

set -e  # 有錯誤就中斷腳本
echo "Applying Prefect deployments..."

# 部署 reminder
echo "Deploying example-reminder..."
poetry run prefect deploy --yes \
  --prefect-file /Users/bacon.huang85/Desktop/TPP/chips-fries/redis-streams/src/orch/deployments/example-reminder.yaml \
  --params "$(cat src/orch/params/reminder_params.json | jq -c .)"

# 部署 reminder-checks
echo "Deploying example-reminder-checks..."
poetry run prefect deploy --yes \
  --prefect-file /Users/bacon.huang85/Desktop/TPP/chips-fries/redis-streams/src/orch/deployments/example-reminder-checks.yaml

echo "Deployments completed successfully."
