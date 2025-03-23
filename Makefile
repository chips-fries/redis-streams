# === Redis & API Configuration ===
REDIS_CONF=config/redis.conf --requirepass "$(REDIS_PASSWORD)"
REDIS_PID=.redis.pid

SCHEDULER_PID=.scheduler.pid
CONSUMER_PID=.consumer.pid
API_PID=.api.pid

API_MODULE=api:app
API_HOST=0.0.0.0
API_PORT=10000
UVICORN_CMD=uvicorn $(API_MODULE) --host $(API_HOST) --port $(API_PORT) --reload

.PHONY: install init start stop restart redis-up redis-down api-up api-down consumer-up consumer-down scheduler-up scheduler-down status clean lint commit

## === Base Commands ===

install:
	poetry install --no-root

init: install start
restart: stop start
start: redis-up scheduler-up consumer-up api-up
stop: api-down scheduler-down consumer-down redis-down clean

## === Redis ===

redis-up:
	@echo "🔌 Starting Redis..."
	@make redis-down
	@sh -c 'cd src && redis-server $(REDIS_CONF)' & echo $$! > $(REDIS_PID); \
	echo "✅ Redis started (PID: `cat $(REDIS_PID)`)" ;

redis-down:
	@echo "🛑 Stopping Redis..."
	@if [ -f $(REDIS_PID) ]; then \
		kill `cat $(REDIS_PID)` && rm -f $(REDIS_PID); \
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
	@sh -c 'cd src && poetry run $(UVICORN_CMD)' & echo $$! > $(API_PID); \
	echo "✅ FastAPI started (PID: `cat $(API_PID)`)" ;

api-down:
	@echo "🛑 Stopping FastAPI..."
	@if [ -f $(API_PID) ]; then \
		kill `cat $(API_PID)` && rm -f $(API_PID); \
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

## === Scheduler ===

scheduler-up:
	@echo "📅 Starting Scheduler..."
	@cd src && nohup poetry run python scheduler.py > ../scheduler.out 2>&1 & echo $$! > $(SCHEDULER_PID)
	@echo "🧾 Showing last 10 lines of Scheduler log:"
	@tail -n 10 scheduler.out
	@echo "✅ Scheduler started (PID: `cat $(SCHEDULER_PID)`)"


scheduler-down:
	@echo "🛑 Stopping Scheduler..."
	@if [ -f $(SCHEDULER_PID) ]; then \
		kill `cat $(SCHEDULER_PID)` && rm -f $(SCHEDULER_PID); \
		echo "✅ Scheduler stopped"; \
	else \
		echo "⚠️ Scheduler not running or PID missing"; \
	fi

## === Consumer ===

consumer-up:
	@echo "🎧 Starting Consumer..."
	@sh -c 'cd src && poetry run python consumers.py' & echo $$! > $(CONSUMER_PID); \
	echo "✅ Consumer started (PID: `cat $(CONSUMER_PID)`)" ;

consumer-down:
	@echo "🛑 Stopping Consumer..."
	@if [ -f $(CONSUMER_PID) ]; then \
		kill `cat $(CONSUMER_PID)` && rm -f $(CONSUMER_PID); \
		echo "✅ Consumer stopped"; \
	else \
		echo "⚠️ Consumer not running or PID file missing"; \
	fi

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
	@if [ -f $(SCHEDULER_PID) ] && ps -p `cat $(SCHEDULER_PID)` > /dev/null 2>&1; then \
		echo "✅ Scheduler is running (PID: `cat $(SCHEDULER_PID)`)"; \
	else \
		echo "❌ Scheduler is not running"; \
	fi
	@if [ -f $(CONSUMER_PID) ] && ps -p `cat $(CONSUMER_PID)` > /dev/null 2>&1; then \
		echo "✅ Consumer is running (PID: `cat $(CONSUMER_PID)`)"; \
	else \
		echo "❌ Consumer is not running"; \
	fi

## === Clean / Lint ===

clean:
	pyclean -v .
	rm -rf .pytest_cache .mypy_cache
	find . -name ".*.pid" -delete
	find . -name "*.rdb" -delete
	find . -name "*.aof" -delete
	find . -name "*.out" -delete
	@echo "🧹 Project cleaned."

lint:
	poetry run pre-commit run --all-files

commit:
	poetry run pre-commit run --all-files
	make clean
	cz commit
	@echo "✅ Pre-commit checks completed."


ngrok-up:
	ngrok http http://localhost:$(API_PORT)
