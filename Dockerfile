# Use official Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    POETRY_NO_INTERACTION=1

# Set work directory
WORKDIR /app

# Install system packages + Redis
RUN apt-get update && \
    apt-get install -y curl build-essential redis && \
    curl -sSL https://install.python-poetry.org | python3 - && \
    apt-get autoremove -y && apt-get clean

# Add poetry to PATH
ENV PATH="/root/.local/bin:$PATH"

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY src ./src

# Install dependencies
RUN poetry install --no-root

# Expose API port
EXPOSE 10000

WORKDIR /app/src

# Run Redis and FastAPI (Redis config is in src/config/redis.conf)
CMD sh -c 'redis-server config/redis.conf --requirepass "$REDIS_PASSWORD" & poetry run python src/scheduler.py & exec poetry run uvicorn api:app --host 0.0.0.0 --port 10000 --reload'
