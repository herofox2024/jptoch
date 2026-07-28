"""Shared retry policy helpers for translation HTTP requests."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional


RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def is_retryable_status(status_code: Any) -> bool:
    """Return whether an HTTP status represents a transient failure."""
    try:
        return int(status_code) in RETRYABLE_STATUS_CODES
    except (TypeError, ValueError):
        return False


def parse_retry_after(value: Any, *, now: Optional[datetime] = None) -> Optional[float]:
    """Parse Retry-After seconds or an RFC-compatible HTTP date."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    try:
        target = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (target - current).total_seconds())


def response_retry_after(response: Any) -> Optional[float]:
    """Read Retry-After from requests/httpx-compatible response objects."""
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("Retry-After")
    except (AttributeError, TypeError):
        return None
    return parse_retry_after(value)


def retry_delay(
    attempt: int,
    *,
    response: Any = None,
    base_delay: float = 2.0,
    max_local_delay: float = 16.0,
    max_server_delay: float = 300.0,
    jitter_max: float = 1.0,
    random_fn: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return max(local exponential delay, provider Retry-After)."""
    attempt_index = max(0, int(attempt or 0))
    local_delay = min(max_local_delay, base_delay * (2 ** attempt_index))
    if jitter_max > 0:
        local_delay += max(0.0, float(random_fn(0.0, jitter_max)))
    server_delay = response_retry_after(response)
    if server_delay is not None:
        server_delay = min(max_server_delay, server_delay)
        return max(local_delay, server_delay)
    return local_delay
