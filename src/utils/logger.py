import logging
import sys

logger = logging.getLogger("project_logger")
logger.setLevel(logging.DEBUG)

# Console only
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.propagate = False
