"""Unobtrusive application logging with secret redaction."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from susanoox.security.redaction import redact_secrets


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def configure_logging(log_file: Path, *, debug: bool = False) -> bool:
    """Configure local logging, returning false when the destination is unavailable."""
    logger = logging.getLogger("susanoox")
    for existing_handler in logger.handlers:
        existing_handler.close()
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    handler: logging.Handler | None = None
    try:
        log_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8", delay=False)
        if os.name != "nt":
            log_file.chmod(0o600)
    except OSError:
        if handler is not None:
            handler.close()
        logger.addHandler(logging.NullHandler())
        return False
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.info("Diagnostic logging initialized")
    if debug:
        logger.debug("Redacted debug logging enabled")
    return True
