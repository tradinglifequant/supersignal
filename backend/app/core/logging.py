from collections.abc import Mapping
import logging
import re
import sys
from typing import Any

# Patterns to redact in log strings and query parameters
REDACT_PATTERNS = [
    (re.compile(r"(api[_-]?key\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(api[_-]?secret\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(x-mbx-apikey\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(x-api-key\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(signature\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(listenkey\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(secret\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(password\s*[:=]\s*)([^\s&,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_\.=]+", re.I), "Bearer ***REDACTED***"),
]

SECRET_KEYS = {
    "api_key",
    "api_secret",
    "secret",
    "password",
    "admin_password_hash",
    "authorization",
    "token",
    "access_token",
    "signature",
    "listenkey",
    "x-mbx-apikey",
    "x-api-key",
    "jwt_secret_key",
    "credentials_encryption_key",
}


def redact_str(value: str) -> str:
    s = value
    for pat, repl in REDACT_PATTERNS:
        s = pat.sub(repl, s)
    return s


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: "***REDACTED***" if str(k).lower() in SECRET_KEYS else redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(x) for x in obj)
    if isinstance(obj, str):
        return redact_str(obj)
    return obj


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_str(record.msg)
        if getattr(record, "args", None):
            if isinstance(record.args, Mapping):
                record.args = redact_obj(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_obj(a) for a in record.args)
            elif isinstance(record.args, str):
                record.args = (redact_str(record.args),)
        return True


def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.setLevel(getattr(logging, level.upper(), logging.INFO))
        lg.propagate = False
    return root
