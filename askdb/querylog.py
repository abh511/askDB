"""Append one JSON line per /ask call: question, SQL, status, attempts, latency."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .pipeline import AskResult

logger = logging.getLogger("askdb")


def log_query(result: AskResult) -> None:
    record = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": result.question,
        "sql": result.sql,
        "status": result.status,
        "reason": result.reason,
        "attempts": result.attempts,
        "latency_ms": result.latency_ms,
        "n_rows": len(result.rows),
    }
    logger.info("ask status=%s attempts=%s latency_ms=%s", result.status, result.attempts, result.latency_ms)
    try:
        path = Path(settings.query_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("could not write the query log")  # logging must never break /ask
