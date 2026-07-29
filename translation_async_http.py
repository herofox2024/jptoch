"""Optional shared httpx executor for OpenAI-compatible JSON requests."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, Optional

import requests

try:
    import httpx
except Exception:  # pragma: no cover - optional speed-up dependency
    httpx = None


HTTPX_AVAILABLE = httpx is not None


class HttpxResponseAdapter:
    """Expose the requests.Response subset consumed by the translation engine."""

    def __init__(
        self,
        status_code: int,
        text: str,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = int(status_code)
        self.text = text or ""
        self.url = url or ""
        self._json_data = json_data
        self.headers = headers or {}

    def json(self) -> Dict[str, Any]:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text or "{}")

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        raise requests.exceptions.HTTPError(
            f"{self.status_code} Error for url: {self.url}",
            response=self,
        )


class AsyncHttpJsonExecutor:
    """Run JSON POST calls through one reusable httpx.AsyncClient pool."""

    def __init__(self, max_connections: int):
        if httpx is None:
            raise RuntimeError("httpx is not available")
        self._max_connections = max(1, int(max_connections or 1))
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._client = None
        self._thread = threading.Thread(target=self._run_loop, name="translator-httpx", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        limits = httpx.Limits(
            max_connections=self._max_connections * 2,
            max_keepalive_connections=self._max_connections,
        )
        self._client = httpx.AsyncClient(limits=limits, trust_env=True)
        self._ready.set()
        self._loop.run_forever()

    async def _post(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int,
    ) -> HttpxResponseAdapter:
        assert self._client is not None
        try:
            response = await self._client.post(url, headers=headers, json=payload, timeout=float(timeout))
            text = response.text or ""
            try:
                json_data = response.json()
            except Exception:
                json_data = None
            return HttpxResponseAdapter(
                response.status_code,
                text,
                str(response.url),
                json_data,
                dict(response.headers),
            )
        except httpx.TimeoutException as exc:
            raise requests.exceptions.Timeout(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise requests.exceptions.ConnectionError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise requests.exceptions.RequestException(str(exc)) from exc

    def post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> HttpxResponseAdapter:
        if self._closed.is_set():
            raise requests.exceptions.ConnectionError("async http executor is closed")
        future = asyncio.run_coroutine_threadsafe(self._post(url, headers, payload, timeout), self._loop)
        return future.result(timeout=max(float(timeout) + 10.0, 15.0))

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()

        async def close_client() -> None:
            if self._client is not None:
                await self._client.aclose()

        try:
            future = asyncio.run_coroutine_threadsafe(close_client(), self._loop)
            future.result(timeout=5)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
