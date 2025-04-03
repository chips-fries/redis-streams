# === Redis & API Configuration ===
REDIS_CONF=$(SRC_PATH)/config/redis.conf --requirepass "$(REDIS_PASSWORD)"
REDIS_PID=.redis.pid

SCHEDULER_PID=.scheduler.pid
CONSUMER_PID=.consumer.pid
PREFECT_PID=.prefect.pid
PREFECT_WORKER_PID=.prefect-worker.pid
API_PID=.api.pid

API_MODULE=app:app
API_HOST=0.0.0.0
API_PORT=10000
UVICORN_CMD=uvicorn $(API_MODULE) --host $(API_HOST) --port $(API_PORT) --reload

PREFECT_WORK_POOL ?= default

PREFECT_SERVER_CMD = $(if $(PREFECT_PROFILES_PATH),PREFECT_PROFILES_PATH=$(PREFECT_PROFILES_PATH)) poetry run prefect server start --host 0.0.0.0 --port 4200
PREFECT_WORKER_CMD = $(if $(PREFECT_PROFILES_PATH),PREFECT_PROFILES_PATH=$(PREFECT_PROFILES_PATH)) poetry run prefect worker start --pool $(PREFECT_WORK_POOL)

.PHONY: install init start stop restart redis-up redis-down api-up api-down consumer-up consumer-down scheduler-up scheduler-down status clean lint commit

## === Base Commands ===

install:
	poetry install --no-root

init: install start
restart: stop start
start: redis-up consumer-up orch-up api-up #prefect-up
stop: api-down consumer-down orch-down redis-down clean

## === Redis ===

redis-up:
	@echo "🔌 Starting Redis..."
	@make redis-down
	@sh -c 'redis-server $(REDIS_CONF) --logfile $(SRC_PATH)/redis.out' & echo $$! > $(SRC_PATH)/$(REDIS_PID);
	@cd src && poetry run python redis_service.py
	@echo "✅ Redis started (PID: `cat $(SRC_PATH)/$(REDIS_PID)`)" ;

redis-down:
	@echo "🛑 Stopping Redis..."
	@if [ -f $(SRC_PATH)/$(REDIS_PID) ]; then \
		kill `cat $(SRC_PATH)/$(REDIS_PID)` && rm -f $(SRC_PATH)/$(REDIS_PID); \
		echo "✅ Redis stopped via PID file"; \
	else \
		echo "⚠️ Redis PID not found, trying fallback..."; \
	fi; \
	PIDS=$$(lsof -ti :6379); \
	if [ ! -z "$$PIDS" ]; then \
		kill -9 $$PIDS && echo "✅ Redis force killed (PID: $$PIDS)"; \
	else \
		echo "✅ No Redis process found"; \
	fi; \
	rm -f dump.rdb appendonly.aof *.rdb *.aof

## === FastAPI ===

api-up:
	@echo "🚀 Starting FastAPI..."
	@sh -c 'cd $(SRC_MODULE) && poetry run $(UVICORN_CMD) > $(SRC_PATH)/api.out 2>&1' & echo $$! > $(SRC_PATH)/$(API_PID);
	@echo "🧾 Showing last 10 lines of FastAPI log:"
	@sleep 10
	@tail -n 10 $(SRC_PATH)/api.out
	@echo "✅ FastAPI started (PID: `cat $(SRC_PATH)/$(API_PID)`)" ;

api-down:
	@echo "🛑 Stopping FastAPI..."
	@if [ -f $(SRC_PATH)/$(API_PID) ]; then \
		kill `cat $(SRC_PATH)/$(API_PID)` && rm -f $(SRC_PATH)/$(API_PID); \
		echo "✅ FastAPI stopped (PID file)"; \
	else \
		echo "⚠️ FastAPI PID not found, fallback killing by port..."; \
	fi; \
	PIDS=$$(lsof -ti :$(API_PORT)); \
	if [ ! -z "$$PIDS" ]; then \
		kill -9 $$PIDS && echo "✅ Killed FastAPI on port $(API_PORT)"; \
	else \
		echo "✅ No FastAPI process found"; \
	fi

## === Consumer ===

consumer-up:
	@echo "🎧 Starting Consumer..."
	@sh -c 'cd src && poetry run python consumer_service.py > $(SRC_PATH)/consumer.out 2>&1' & echo $$! > $(SRC_PATH)/$(CONSUMER_PID);
	@echo "✅ Consumer started (PID: `cat $(SRC_PATH)/$(CONSUMER_PID)`)" ;

consumer-down:
	@echo "🛑 Stopping Consumer..."
	@if [ -f $(CONSUMER_PID) ]; then \
		kill `cat $(SRC_PATH)/$(CONSUMER_PID)` && rm -f $(SRC_PATH)/$(CONSUMER_PID); \
		echo "✅ Consumer stopped"; \
	else \
		echo "⚠️ Consumer not running or PID file missing"; \
	fi


## === Scheduler ===

# scheduler-up:
# 	@echo "📅 Starting Scheduler..."
# 	@cd $(SRC_PATH) && nohup poetry run python scheduler.py > $(SRC_PATH)/scheduler.out 2>&1 & echo $$! > $(SRC_PATH)/$(SCHEDULER_PID)
# 	@echo "🧾 Showing last 10 lines of Scheduler log:"
# 	@tail -n 10 $(SRC_PATH)/scheduler.out
# 	@echo "✅ Scheduler started (PID: `cat $(SRC_PATH)/$(SCHEDULER_PID)`)"


# scheduler-down:
# 	@echo "🛑 Stopping Scheduler..."
# 	@if [ -f $(SCHEDULER_PID) ]; then \
# 		kill `cat $(SCHEDULER_PID)` && rm -f $(SCHEDULER_PID); \
# 		echo "✅ Scheduler stopped"; \
# 	else \
# 		echo "⚠️ Scheduler not running or PID missing"; \
# 	fi



## === Status Check ===

status:
	@echo "🔍 Checking service status..."
	@if lsof -ti :6379 > /dev/null; then \
		echo "✅ Redis is running"; \
	else \
		echo "❌ Redis is not running"; \
	fi
	@if lsof -ti :$(API_PORT) > /dev/null; then \
		echo "✅ FastAPI is running"; \
	else \
		echo "❌ FastAPI is not running"; \
	fi
# 	@if [ -f $(SCHEDULER_PID) ] && ps -p `cat $(SCHEDULER_PID)` > /dev/null 2>&1; then \
# 		echo "✅ Scheduler is running (PID: `cat $(SCHEDULER_PID)`)"; \
# 	else \
# 		echo "❌ Scheduler is not running"; \
# 	fi
	@if [ -f $(SRC_PATH)/$(CONSUMER_PID) ] && ps -p `cat $(SRC_PATH)/$(CONSUMER_PID)` > /dev/null 2>&1; then \
		echo "✅ Consumer is running (PID: `cat $(SRC_PATH)/$(CONSUMER_PID)`)"; \
	else \
		echo "❌ Consumer is not running"; \
	fi
	@if [ -f $(SRC_PATH)/$(PREFECT_PID) ] && ps -p `cat $(SRC_PATH)/$(PREFECT_PID)` > /dev/null 2>&1; then \
		echo "✅ Prefect Orchestration is running (PID: `cat $(SRC_PATH)/$(PREFECT_PID)`)"; \
	else \
		echo "❌ Prefect Orchestration is not running"; \
	fi
	@if [ -f $(SRC_PATH)/$(PREFECT_WORKER_PID) ] && ps -p `cat $(SRC_PATH)/$(PREFECT_WORKER_PID)` > /dev/null 2>&1; then \
		echo "✅ Prefect Worker is running (PID: `cat $(SRC_PATH)/$(PREFECT_WORKER_PID)`)"; \
	else \
		echo "❌ Prefect Worker is not running"; \
	fi

# ## === Clean / Lint ===

clean:
	pyclean -v .
	rm -rf .pytest_cache .mypy_cache
	find . -name ".*.pid" -delete
	find . -name "*.rdb" -delete
	find . -name "*.aof" -delete
	find . -name "*.out" -delete
	find . -name "*.sqlite*" -delete
	rm -rf src/prefect/db/db.*
	pkill -f redis
	pkill -f prefect
	pkill -f consumer
	pkill -f orch
	@echo "🧹 Project cleaned."

# lint:
# 	poetry run pre-commit run --all-files

# commit:
# 	poetry run pre-commit run --all-files
# 	make clean
# 	cz commit
# 	@echo "✅ Pre-commit checks completed."


# ngrok-up:
# 	ngrok http http://localhost:$(API_PORT)

orch-up:
	@echo "🚀 Starting Prefect Orchestration (ephemeral server)..."
	@sh -c 'PREFECT_PROFILES_PATH=$(PREFECT_PROFILES_PATH) poetry run prefect server start' > $(SRC_PATH)/prefect.out 2>&1 & echo $$! > $(SRC_PATH)/$(PREFECT_PID)
	@sleep 30
	@sh -c 'PREFECT_PROFILES_PATH=$(PREFECT_PROFILES_PATH) poetry run prefect worker start --pool default' > $(SRC_PATH)/prefect-worker.out 2>&1 & echo $$! > $(SRC_PATH)/$(PREFECT_WORKER_PID)
	@cd src && poetry run prefect deploy --all --prefect-file $(SRC_PATH)/orch/prefect.yaml


	echo "✅ Prefect Orchestration started (PID: `cat $(SRC_PATH)/$(PREFECT_PID)`)"
	echo "✅ Prefect Worker started (PID: `cat $(SRC_PATH)/$(PREFECT_WORKER_PID)`)"
	echo "✅ Block 'gitlab-access-token' is ready for all deployments"
	echo "✅ All deployments applied"

orch-down:
	@echo "🛑 Stopping Prefect Orchestration..."

	@poetry run prefect server stop
	@if [ -f $(SRC_PATH)/$(PREFECT_PID) ]; then \
		kill `cat $(SRC_PATH)/$(PREFECT_PID)` && rm -f $(SRC_PATH)/$(PREFECT_PID); \
		echo "✅ Prefect Orchestration stopped"; \
	else \
		echo "⚠️ Prefect Orchestration not running or PID file missing"; \
	fi

	@sleep 2

	@echo "🛑 Stopping Prefect Worker..."
	@if [ -f $(SRC_PATH)/$(PREFECT_WORKER_PID) ]; then \
		kill `cat $(SRC_PATH)/$(PREFECT_WORKER_PID)` && rm -f $(SRC_PATH)/$(PREFECT_WORKER_PID); \
		echo "✅ Prefect Worker stopped"; \
	else \
		echo "⚠️ Prefect Worker not running or PID file missing"; \
	fi
