# foundry: kind=test domain=client-intelligence-platform
"""StubTransport — in-memory HTTPTransport stub for connector tests.

Implements the ``HTTPTransport`` Protocol with canned responses keyed by
(method, path) tuples. Tests configure the stub with expected calls +
their responses; the connector consumes the stub as it would a real
``HttpxTransport``.

Pattern:

    stub = StubTransport()
    stub.queue(
        "GET",
        "/crm/v3/objects/companies",
        response={"results": [...], "paging": {"next": {"after": "100"}}},
    )
    stub.queue("GET", "/crm/v3/objects/companies", response={"results": [...]})
    connector = HubSpotConnector(tenant_id=..., http=stub)

The stub records all calls in ``stub.calls`` for assertion.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from cip.integration_mesh.connectors._http import HTTPError


class StubResponse:
    """Either a JSON dict to return or an HTTPError to raise."""

    def __init__(
        self,
        json: dict[str, Any] | None = None,
        *,
        error: HTTPError | None = None,
    ) -> None:
        self.json = json
        self.error = error


class StubTransport:
    """HTTPTransport stub. Tests pre-queue responses; consumer pulls
    them in FIFO order. Records all observed GETs in ``self.calls``."""

    def __init__(self) -> None:
        self._queue: deque[StubResponse] = deque()
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def queue(
        self,
        method: str,
        path: str,
        *,
        response: dict[str, Any] | None = None,
        error: HTTPError | None = None,
    ) -> None:
        """Queue the NEXT response. Method + path are informational; the
        stub returns responses in queue order regardless of which call
        is made (intentional: connector tests assert on order/count, not
        per-call routing)."""
        del method, path  # informational only; queue is FIFO
        self._queue.append(StubResponse(json=response, error=error))

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("GET", path, params))
        if not self._queue:
            raise AssertionError(
                f"StubTransport: no queued response for GET {path} "
                f"(params={params}); previous calls: {self.calls[:-1]}"
            )
        next_response = self._queue.popleft()
        if next_response.error is not None:
            raise next_response.error
        assert next_response.json is not None  # mypy
        return next_response.json
