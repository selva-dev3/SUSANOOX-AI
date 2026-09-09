"""Best-effort secret redaction for user-facing diagnostics and logs."""

from __future__ import annotations

import re
from collections.abc import Iterable

_AUTHORIZATION = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+")
_API_KEY_FIELD = re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+")
_TOKENISH = re.compile(r"\b(?:sk|sess|key)-[A-Za-z0-9_-]{8,}\b")


def redact_secrets(value: object, known_secrets: Iterable[str] = ()) -> str:
    """Return a printable string with likely credentials removed."""
    redacted = str(value)
    for secret in known_secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _AUTHORIZATION.sub(r"\1[REDACTED]", redacted)
    redacted = _API_KEY_FIELD.sub(r"\1[REDACTED]", redacted)
    return _TOKENISH.sub("[REDACTED]", redacted)
