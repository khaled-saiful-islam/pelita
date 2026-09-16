"""Logging setup.

Structured enough to grep, plain enough to read in `make logs`.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # These are chatty at INFO and say nothing the app log does not.
    for noisy in ("httpx", "httpcore", "sqlalchemy.engine.Engine", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
