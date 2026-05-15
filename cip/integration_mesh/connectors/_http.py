# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Shared HTTP transport abstraction for CIP connectors.

Defines a ``HTTPTransport`` Protocol that real connectors (HubSpot,
Zendesk, future) consume. The default implementation ``HttpxTransport``
wraps ``httpx.Client`` with built-in retry-on-429 (honoring ``Retry-After``)
+ retry-on-5xx with exponential backoff.

Tests inject a stub transport (e.g. ``StubTransport`` from
``tests/connectors/conftest.py``) returning canned responses so the
conformance harness runs without real HTTP traffic in CI.

Why a shared module:
  - Both HubSpot and Zendesk need the same retry / rate-limit-handling
    behavior; duplicating it across connectors is foot-gun-prone.
  - The injectable Protocol pattern is the connector-conformance-harness
    contract — every new connector ships with an injectable transport.
"""
from __future__ import annotations

import time
from typing import Any, Protocol


class HTTPError(Exception):
    """Raised by ``HTTPTransport`` implementations on non-2xx responses
    after retry budget is exhausted. Connectors translate to
    ``AuthenticationError`` / ``RateLimitExceeded`` / etc. at the
    boundary."""

    def __init__(
        self,
        status: int,
        body: str,
        url: str = "",
        method: str = "",
    ) -> None:
        self.status = status
        self.body = body
        self.url = url
        self.method = method
        super().__init__(
            f"{method or 'HTTP'} {url or '?'} → {status}: {body[:200]}"
        )


class HTTPTransport(Protocol):
    """Read-only HTTP client surface a CIP connector consumes.

    Implementations MUST:
      - Handle authentication transparently (the connector configures
        auth at construction; per-call code never sets headers).
      - Retry on 429 with Retry-After honored (capped per connector).
      - Retry on 5xx with exponential backoff up to a small budget.
      - Raise ``HTTPError`` on non-2xx after retry budget exhausted.
    """

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a GET to ``base_url + path``; return parsed JSON dict.

        Raises:
            HTTPError: non-2xx after retries.
        """
        ...

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a POST to ``base_url + path`` with JSON body; return
        parsed JSON dict. Same retry / 429 / 5xx semantics as ``get()``.

        Added 2026-05-15 (scope 9c3d1393) so connectors can use POST
        batch/read endpoints that accept large property lists in the
        body, avoiding GET URL-length caps (~32KB on most stacks) when
        a single tenant has 200+ HubSpot properties.

        Raises:
            HTTPError: non-2xx after retries.
        """
        ...


class HttpxTransport:
    """httpx-backed default ``HTTPTransport``. Used by production code;
    tests substitute a stub.

    Constructor accepts:
      - ``base_url``: e.g. ``https://api.hubapi.com``
      - ``auth_headers``: dict of headers attached to every request (e.g.
        ``{"Authorization": "Bearer pat-..."}``)
      - ``max_retries``: total retry attempts on 429 / 5xx; default 5
      - ``retry_after_cap_seconds``: max sleep on 429; default 300
        (matches orchestrator's ``MAX_RATE_LIMIT_SLEEP_SECONDS``)
      - ``backoff_base_seconds``: exponential backoff base; default 1
      - ``timeout_seconds``: per-request timeout; default 30
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_headers: dict[str, str],
        max_retries: int = 5,
        retry_after_cap_seconds: int = 300,
        backoff_base_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
    ) -> None:
        # Lazy-import httpx so the framework's core import path doesn't
        # require httpx in environments that only use FixtureConnector.
        import httpx  # noqa: F401  # lazy import; see module docstring

        self._httpx = httpx
        self._client = httpx.Client(
            base_url=base_url,
            headers=auth_headers,
            timeout=timeout_seconds,
        )
        self.max_retries = max_retries
        self.retry_after_cap_seconds = retry_after_cap_seconds
        self.backoff_base_seconds = backoff_base_seconds

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        last_status = 0
        last_body = ""
        while attempt <= self.max_retries:
            response = self._client.get(path, params=params)
            if 200 <= response.status_code < 300:
                # httpx returns Any for .json(); cast for typing.
                json_value = response.json()
                if not isinstance(json_value, dict):
                    raise HTTPError(
                        status=response.status_code,
                        body=f"Unexpected non-dict JSON: {type(json_value).__name__}",
                        url=str(response.url),
                        method="GET",
                    )
                return json_value

            last_status = response.status_code
            last_body = response.text

            if response.status_code == 429:
                wait_str = response.headers.get("Retry-After", "")
                try:
                    wait = int(wait_str) if wait_str else 60
                except ValueError:
                    wait = 60
                wait = min(wait, self.retry_after_cap_seconds)
                _sleep(wait)
                attempt += 1
                continue

            if 500 <= response.status_code < 600:
                # Exponential backoff on 5xx
                _sleep(self.backoff_base_seconds * (2 ** attempt))
                attempt += 1
                continue

            # Non-retryable 4xx (401, 403, 404, 400, ...) — surface immediately
            raise HTTPError(
                status=response.status_code,
                body=response.text,
                url=str(response.url),
                method="GET",
            )

        raise HTTPError(
            status=last_status,
            body=f"retries exhausted ({self.max_retries}): {last_body}",
            url=path,
            method="GET",
        )

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST with JSON body. Same retry semantics as ``get()`` —
        retries on 429 (honoring Retry-After up to cap) and 5xx
        (exponential backoff). Raises HTTPError on non-retryable 4xx
        or after retry budget exhausted."""
        attempt = 0
        last_status = 0
        last_body = ""
        while attempt <= self.max_retries:
            response = self._client.post(path, json=json_body, params=params)
            if 200 <= response.status_code < 300:
                json_value = response.json()
                if not isinstance(json_value, dict):
                    raise HTTPError(
                        status=response.status_code,
                        body=f"Unexpected non-dict JSON: {type(json_value).__name__}",
                        url=str(response.url),
                        method="POST",
                    )
                return json_value

            last_status = response.status_code
            last_body = response.text

            if response.status_code == 429:
                wait_str = response.headers.get("Retry-After", "")
                try:
                    wait = int(wait_str) if wait_str else 60
                except ValueError:
                    wait = 60
                wait = min(wait, self.retry_after_cap_seconds)
                _sleep(wait)
                attempt += 1
                continue

            if 500 <= response.status_code < 600:
                _sleep(self.backoff_base_seconds * (2 ** attempt))
                attempt += 1
                continue

            raise HTTPError(
                status=response.status_code,
                body=response.text,
                url=str(response.url),
                method="POST",
            )

        raise HTTPError(
            status=last_status,
            body=f"retries exhausted ({self.max_retries}): {last_body}",
            url=path,
            method="POST",
        )

    def __enter__(self) -> HttpxTransport:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()


# Tests can monkeypatch this to skip real sleeps.
def _sleep(seconds: float) -> None:
    time.sleep(seconds)
