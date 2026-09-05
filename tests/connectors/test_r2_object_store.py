# foundry: kind=test domain=client-intelligence-platform
"""R2ObjectStore: the one place the document connector touches real storage.

Exercised against a stubbed boto3 client, so these run with no network and no
CIP_R2_* variables set.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cip.integration_mesh.connectors.document_library import (
    R2ConfigError,
    R2ObjectStore,
)

T0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)


class FakePaginator:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    def paginate(self, **_kw: object) -> list[dict]:
        return self._pages


class FakeS3:
    def __init__(self, pages: list[dict], bodies: dict[str, bytes] | None = None) -> None:
        self._pages = pages
        self._bodies = bodies or {}
        self.get_calls: list[str] = []

    def get_paginator(self, _name: str) -> FakePaginator:
        return FakePaginator(self._pages)

    def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
        self.get_calls.append(Key)

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self._bodies[Key])}


def _obj(key: str, size: int = 10) -> dict:
    return {"Key": key, "LastModified": T0, "Size": size}


def test_missing_config_fails_at_construction_naming_what_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail here, not deep inside the first listing. This repo has a cautionary
    tale about a stale endpoint that ran silently for three days because the
    first failure surfaced far from its cause."""
    for var in ("CIP_R2_ENDPOINT_URL", "CIP_R2_ACCESS_KEY_ID", "CIP_R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(R2ConfigError) as exc:
        R2ObjectStore()

    msg = str(exc.value)
    for var in ("CIP_R2_ENDPOINT_URL", "CIP_R2_ACCESS_KEY_ID", "CIP_R2_SECRET_ACCESS_KEY"):
        assert var in msg, f"the error must name {var} so it can be fixed"


def test_listing_spans_every_page() -> None:
    """PAGINATION IS LOAD-BEARING, not tidiness.

    list_objects_v2 caps at 1000 keys and returns a truncated result WITHOUT
    erroring. A library that grew past the cap would silently stop being fully
    enumerated, and under the tombstone rule every file beyond it would read as
    vanished and have its chunks purged. A silent truncation would therefore
    DELETE content, not merely miss it.
    """
    pages = [
        {"Contents": [_obj("p/a.pdf"), _obj("p/b.pdf")]},
        {"Contents": [_obj("p/c.pdf")]},
    ]
    store = R2ObjectStore(client=FakeS3(pages), bucket="b")
    assert [o.key for o in store.list_objects("p/")] == ["p/a.pdf", "p/b.pdf", "p/c.pdf"]


def test_directory_placeholders_are_not_documents() -> None:
    pages = [{"Contents": [_obj("p/"), _obj("p/real.pdf")]}]
    store = R2ObjectStore(client=FakeS3(pages), bucket="b")
    assert [o.key for o in store.list_objects("p/")] == ["p/real.pdf"]


def test_an_empty_page_yields_nothing_rather_than_raising() -> None:
    store = R2ObjectStore(client=FakeS3([{}]), bucket="b")
    assert list(store.list_objects("p/")) == []


def test_listing_carries_last_modified_and_size() -> None:
    store = R2ObjectStore(client=FakeS3([{"Contents": [_obj("p/a.pdf", 42)]}]), bucket="b")
    (obj,) = store.list_objects("p/")
    assert obj.last_modified == T0
    assert obj.size_bytes == 42


def test_get_bytes_returns_the_body() -> None:
    s3 = FakeS3([{"Contents": []}], {"p/a.pdf": b"canebrake"})
    store = R2ObjectStore(client=s3, bucket="b")
    assert store.get_bytes("p/a.pdf") == b"canebrake"
    assert s3.get_calls == ["p/a.pdf"]


def test_the_store_exposes_no_write_or_delete() -> None:
    """Read-only by construction. The connector mirrors a tenant's library into
    CIP; it has no business writing to it, and removal is handled CIP-side by
    tombstoning, never by touching the source."""
    for forbidden in ("put_object", "delete_object", "put", "delete", "upload"):
        assert not hasattr(R2ObjectStore, forbidden), (
            f"R2ObjectStore exposes {forbidden}; it must stay read-only"
        )
