# Redis and API configuration
REDIS_CONF=config/redis.conf
REDIS_PID=.redis.pid

API_MODULE=api:app
API_HOST=0.0.0.0
API_PORT=10000
API_PID=.api.pid
UVICORN_CMD=uvicorn $(API_MODULE) --host $(API_HOST) --port $(API_PORT) --reload

.PHONY: install init start stop restart redis-up redis-down api-up api-down status clean lint commit

## Install Python dependencies (without installing the current project itself)
install:
	poetry install --no-root

## Initialize the project (install dependencies and start services)
init: install start

## Start both Redis and API services
start: redis-up api-up

## Stop both Redis and API services
stop: api-down redis-down

## Restart both Redis and API services
restart: stop start

## Start Redis using the specified redis.conf
redis-up:
	@echo "🔌 Starting Redis..."
	@if ! pgrep -x "redis-server" > /dev/null; then \
		redis-server $(REDIS_CONF) & \
		echo $$! > $(REDIS_PID); \
		echo "✅ Redis started (PID: `cat $(REDIS_PID)`)" ;\
	else \
		echo "⚠️ Redis is already running"; \
	fi

## Stop Redis (only if started via this Makefile)
redis-down:
	@echo "🛑 Stopping Redis..."
	@if [ -f $(REDIS_PID) ]; then \
		kill `cat $(REDIS_PID)` && rm $(REDIS_PID); \
		echo "✅ Redis stopped"; \
	else \
		echo "⚠️ Redis is not controlled by Makefile or already stopped"; \
	fi

## Start FastAPI using Uvicorn
api-up:
	@echo "🚀 Starting FastAPI..."
	@cd src && poetry run $(UVICORN_CMD) & \
	echo $$! > $(API_PID); \
	echo "✅ FastAPI started (PID: `cat $(API_PID)`)" ;

## Stop FastAPI (fallback to lsof if .api.pid is missing)
api-down:
	@echo "🛑 Stopping FastAPI..."
	@if [ -f $(API_PID) ]; then \
		PID=`cat $(API_PID)`; \
		if ps -p $$PID > /dev/null 2>&1; then \
			kill -9 $$PID && echo "✅ Main process $$PID stopped"; \
		fi; \
		rm -f $(API_PID); \
	fi; \
	# Fallback: force kill all processes using the API port
	PROCESSES=$$(lsof -ti :$(API_PORT)); \
	if [ ! -z "$$PROCESSES" ]; then \
		echo "⚠️ Detected leftover FastAPI child processes: $$PROCESSES"; \
		kill -9 $$PROCESSES && echo "✅ All child processes killed"; \
	else \
		echo "✅ No leftover FastAPI processes"; \
	fi

## Show current status of Redis and FastAPI services
status:
	@echo "🔍 Checking service status..."
	@if pgrep -x "redis-server" > /dev/null; then echo "✅ Redis is running"; else echo "❌ Redis is not running"; fi
	@if lsof -ti :$(API_PORT) > /dev/null; then echo "✅ FastAPI is running"; else echo "❌ FastAPI is not running"; fi

clean:
	pyclean -v .
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	find . -maxdepth 1 -name ".*.pid" -delete
	@echo "Project cleaned."

lint:
	poetry run pre-commit run --all-files

commit:
	poetry run pre-commit run --all-files
	make clean
	cz commit
	@echo "Pre-commit checks completed."
