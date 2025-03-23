import logging
import sys

# 建立 logger 實例
logger = logging.getLogger("project_logger")
logger.setLevel(logging.DEBUG)

# 建立 Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# 日誌格式加上 [SERVICE_NAME]
formatter = logging.Formatter("[%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)

# 設定 Handler
logger.handlers = [console_handler]
logger.propagate = False

# 強制讓 Uvicorn 的 logger 也套用這個格式（只限主 API service）
for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    uvicorn_logger = logging.getLogger(name)
    uvicorn_logger.handlers.clear()
    uvicorn_logger.propagate = True
