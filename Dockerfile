# Use official Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    POETRY_NO_INTERACTION=1

# Set work directory
WORKDIR /app

# Install required system packages
RUN apt-get update && apt-get install -y curl build-essential && \
    curl -sSL https://install.python-poetry.org | python3 - && \
    apt-get autoremove -y && apt-get clean

# Add Poetry to PATH
ENV PATH="/root/.local/bin:$PATH"

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY src ./src
COPY config ./config

# Install Python dependencies using Poetry
RUN poetry install --no-root

# Expose the port used by Uvicorn
EXPOSE 10000

# Start FastAPI using Uvicorn
CMD ["poetry", "run", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "10000", "--reload"]
