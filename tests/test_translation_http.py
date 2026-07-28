from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

import pytest

from translation_http import (
    is_retryable_status,
    parse_retry_after,
    retry_delay,
)


class HeaderResponse:
    def __init__(self, retry_after=None):
        self.headers = {}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retryable(status):
    assert is_retryable_status(status)


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 422])
def test_permanent_statuses_are_not_retryable(status):
    assert not is_retryable_status(status)


def test_retry_after_seconds_override_local_backoff():
    response = HeaderResponse("12")
    delay = retry_delay(
        0,
        response=response,
        random_fn=lambda _start, _end: 0.0,
    )
    assert delay == 12.0


def test_retry_after_http_date_is_supported():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    value = format_datetime(now + timedelta(seconds=30), usegmt=True)
    delay = parse_retry_after(value, now=now)
    assert delay == pytest.approx(30.0, abs=0.1)


def test_retry_wait_is_cancellable():
    from translator import JaZhTranslator

    translator = JaZhTranslator.__new__(JaZhTranslator)
    translator.cancel_event = mock.Mock()
    translator.cancel_event.wait.return_value = True

    with pytest.raises(RuntimeError, match="翻译已取消"):
        translator._wait_http_retry(0, context="test")
