"""Logging setup. Called explicitly by the entry point, never at import time."""
from __future__ import annotations

import logging
import sys

from app.config import LOG_FILE

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(log_file: str = LOG_FILE, level: int = logging.DEBUG) -> None:
    """Log to stdout and a file. Safe to call more than once."""
    root = logging.getLogger()
    if getattr(root, "_mynaksh_configured", False):
        return
    formatter = logging.Formatter(_FORMAT)
    for handler in (logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(level)
    root._mynaksh_configured = True  # type: ignore[attr-defined]
