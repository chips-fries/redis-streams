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

---

## 🔐 Security

This API is protected using a combination of:

1. **Static Token Authentication**
   Every request must include a valid token via the `token` HTTP header.

2. **HMAC-SHA256 Signature Verification**
   To prevent token leakage and replay attacks, every request must also include:
   - `x-timestamp`: A Unix timestamp (in seconds)
   - `x-signature`: A HMAC-SHA256 signature based on the timestamp and shared token

### How It Works

The client computes the signature like this:

```python
import time
import hmac
import hashlib
import requests

# === 設定區 ===
API_URL = "http://localhost:10000/publish/test"
API_TOKEN = "your-secret-token"  # 請換成你在 .env 裡設定的 token
MESSAGE = "Hello from Python client!"

# === 計算 timestamp 和 HMAC signature ===
timestamp = str(int(time.time()))  # 秒為單位的 timestamp
signature = hmac.new(
    API_TOKEN.encode(), timestamp.encode(), hashlib.sha256
).hexdigest()

# === Headers ===
headers = {
    "token": API_TOKEN,
    "x-timestamp": timestamp,
    "x-signature": signature,
}

# === 發送 POST 請求 ===
params = {"message": MESSAGE}
response = requests.post(API_URL, headers=headers, params=params)

# === 顯示結果 ===
print("Status code:", response.status_code)
print("Response:", response.json())

```

---

## 🧼 Code Quality

This project uses [pre-commit](https://pre-commit.com/) to enforce formatting and linting.

To run all pre-commit checks manually:

```bash
poetry run pre-commit run --all-files
```
