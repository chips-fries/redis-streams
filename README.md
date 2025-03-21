# 📡 Redis Stream Notification Service

A lightweight, environment-aware messaging system built with **FastAPI** and **Redis Streams**, designed to handle producer/consumer workflows and deliver real-time alerts via **Slack**.

---

## 🚀 Features

- ✅ Token-authenticated API for publishing messages
- ✅ Redis Streams used for `dev`, `uat`, and `prod` environments
- ✅ Stream status monitoring & cleanup endpoints
- ✅ Slack consumer integration for notifications
- ✅ Configurable via YAML and environment variables
- ✅ Built-in Makefile for local control (start/stop services)
- ✅ Pre-commit hooks for code quality enforcement (Black, isort, Flake8)

---

## 🔧 Setup

```bash
# Clone repo and install dependencies
poetry install

# Set up environment variable for token (via .env or .envrc)
export API_TOKEN=your-secret-token

# Run Redis and API
make start

# Or run individually
make redis-up
make api-up
```

---

## 🧪 API Endpoints

| Method | Endpoint              | Description                         |
|--------|------------------------|-------------------------------------|
| GET    | `/status/{env}`        | Check stream status for given env   |
| GET    | `/status`              | Check all environment stream status |
| POST   | `/publish/{env}`       | Publish a message to the stream     |
| DELETE | `/clear/{env}`         | Clear stream messages by environment |
| DELETE | `/clear`               | Clear all environment streams       |

> **Note:** All endpoints require a `token` header for authentication.

## 🧼 Code Quality

This project uses [pre-commit](https://pre-commit.com/) to enforce formatting and linting.

To run all pre-commit checks manually:

```bash
poetry run pre-commit run --all-files
```
