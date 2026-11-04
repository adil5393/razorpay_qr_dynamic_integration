"""Logging with a per-request ID. LOG_FORMAT=json gives one JSON object per line (for production)."""
import json
import logging
import os
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_INCOMING_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_request_id(incoming: str | None) -> str:
    """Reuse a well-formed X-Request-ID from the proxy, otherwise make a new one."""
    if incoming and _INCOMING_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in ("method", "path", "status", "duration_ms", "client_ip"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if (os.environ.get("LOG_FORMAT") or "text").strip().lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel((os.environ.get("LOG_LEVEL") or "INFO").upper())
