# foundry: kind=test domain=client-intelligence-platform
"""HttpxTransport unit tests — retry-on-429 + backoff-on-5xx + 4xx-fast-fail.

Uses httpx's MockTransport (built into httpx) to inject responses without
network. Verifies the retry budget + Retry-After honoring behavior.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from cip.integration_mesh.connectors import _http
from cip.integration_mesh.connectors._http import (
    HTTPError,
    HttpxTransport,
)


def _build_transport_with_mock(handler: Any) -> HttpxTransport:
    """Build HttpxTransport whose underlying httpx.Client uses MockTransport."""
    t = HttpxTransport(
        base_url="https://example.test",
        auth_headers={"Authorization": "Bearer test"},
        max_retries=3,
        retry_after_cap_seconds=2,
        backoff_base_seconds=0.0,  # speed up tests
        timeout_seconds=5.0,
    )
    # Replace the internal httpx.Client with one using MockTransport
    t._client = httpx.Client(
        base_url="https://example.test",
        headers={"Authorization": "Bearer test"},
        transport=httpx.MockTransport(handler),
    )
    return t


def test_200_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_http, "_sleep", lambda _s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "value": 42})

    t = _build_transport_with_mock(handler)
    result = t.get("/anything")
    assert result == {"ok": True, "value": 42}


def test_401_raises_immediately_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_http, "_sleep", lambda _s: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    t = _build_transport_with_mock(handler)
    with pytest.raises(HTTPError) as exc_info:
        t.get("/secure")
    assert exc_info.value.status == 401
    assert call_count == 1  # NO retry on 4xx


def test_429_retries_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(_http, "_sleep", fake_sleep)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(
                429, json={"error": "rate limited"}, headers={"Retry-After": "1"}
            )
        return httpx.Response(200, json={"ok": True})

    t = _build_transport_with_mock(handler)
    result = t.get("/limited")
    assert result == {"ok": True}
    assert call_count == 3
    # Each 429 should have triggered a sleep
    assert len(sleeps) == 2
    # All sleeps should be 1 (Retry-After value)
    assert sleeps == [1, 1]


def test_429_retry_after_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-After larger than retry_after_cap_seconds caps at the cap."""
    sleeps: list[float] = []
    monkeypatch.setattr(_http, "_sleep", lambda s: sleeps.append(s))

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "300"})  # 5 min
        return httpx.Response(200, json={"ok": True})

    t = _build_transport_with_mock(handler)
    t.retry_after_cap_seconds = 2  # cap at 2 sec
    t.get("/limited")
    assert sleeps == [2]  # capped


def test_5xx_retries_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(_http, "_sleep", lambda s: sleeps.append(s))
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(503, json={"error": "service unavailable"})
        return httpx.Response(200, json={"ok": True})

    t = _build_transport_with_mock(handler)
    t.backoff_base_seconds = 0.5
    result = t.get("/down")
    assert result == {"ok": True}
    assert call_count == 3
    # First retry: 0.5 * 2^0 = 0.5; second retry: 0.5 * 2^1 = 1.0
    assert sleeps == [0.5, 1.0]


def test_retries_exhausted_raises_with_last_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_http, "_sleep", lambda _s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "perpetually down"})

    t = _build_transport_with_mock(handler)
    with pytest.raises(HTTPError) as exc_info:
        t.get("/perpetual-503")
    assert exc_info.value.status == 503
    assert "retries exhausted" in exc_info.value.body


def test_non_dict_json_raises_error() -> None:
    """If the API returns a JSON array (or non-dict), the transport
    raises so connectors don't silently mis-handle the shape."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["a", "b", "c"])

    t = _build_transport_with_mock(handler)
    with pytest.raises(HTTPError, match="non-dict JSON"):
        t.get("/list-result")
