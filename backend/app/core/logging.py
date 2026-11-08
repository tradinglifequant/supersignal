import logging
import re
import sys
from typing import Any

# Patterns to redact
REDACT_PATTERNS = [
    (re.compile(r"(api[_-]?key\s*[:=]\s*)([^\s,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(api[_-]?secret\s*[:=]\s*)([^\s,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(secret\s*[:=]\s*)([^\s,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"(password\s*[:=]\s*)([^\s,;\"']+)", re.I), r"\1***REDACTED***"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_\.=]+", re.I), "Bearer ***REDACTED***"),
]

SECRET_KEYS = {"api_key", "api_secret", "secret", "password", "authorization", "token"}


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: "***REDACTED***" if k.lower() in SECRET_KEYS else redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, str):
        s = obj
        for pat, repl in REDACT_PATTERNS:
            s = pat.sub(repl, s)
        return s
    return obj


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pat, repl in REDACT_PATTERNS:
                record.msg = pat.sub(repl, record.msg)
        if hasattr(record, "args") and record.args:
            # Tuple args
            new_args = []
            for a in record.args if isinstance(record.args, tuple) else [record.args]:  # type: ignore
                if isinstance(a, str):
                    s = a
                    for pat, repl in REDACT_PATTERNS:
                        s = pat.sub(repl, s)
                    new_args.append(s)
                else:
                    new_args.append(a)
            record.args = tuple(new_args)  # type: ignore
        return True


def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    ))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Uvicorn loggers
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.setLevel(getattr(logging, level.upper(), logging.INFO))
        lg.propagate = False
    return root
