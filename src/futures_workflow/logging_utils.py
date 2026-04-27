import json
import logging
from pathlib import Path
from typing import Any, Dict

from .config import LOG_DIR
from .utils import ensure_directory


def get_logger(name: str = "futures_workflow") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    ensure_directory(LOG_DIR)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_DIR / "workflow.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def append_failure_log(payload: Dict[str, Any]) -> None:
    ensure_directory(LOG_DIR)
    with (LOG_DIR / "failures.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
