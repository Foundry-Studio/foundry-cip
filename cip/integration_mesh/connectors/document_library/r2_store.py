# foundry: kind=service domain=client-intelligence-platform touches=integration
"""boto3-backed :class:`ObjectStore` for Cloudflare R2.

The connector is written against the two-method ``ObjectStore`` Protocol so
that its whole classification path stays testable without network or
credentials. This module is the one place that actually talks to R2.

Credentials follow the pattern already established by
``scripts/migrate_rocky_ridge_to_cip.py``, so an operator who has run that has
the environment this needs:

    CIP_R2_BUCKET             (default: foundry-agent-system)
    CIP_R2_ENDPOINT           https://<account>.r2.cloudflarestorage.com
    CIP_R2_ACCESS_KEY_ID
    CIP_R2_SECRET_ACCESS_KEY

DELIBERATELY READ-ONLY. There is no put or delete here. The connector's job is
to observe a library and mirror it into CIP; it has no business writing to a
tenant's document store, and a client that cannot write cannot corrupt one by
accident. Removal is handled on the CIP side by tombstoning the file record and
purging its derived chunks, never by touching the source.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from .connector import StoredObject

DEFAULT_BUCKET = "foundry-agent-system"


class R2ConfigError(RuntimeError):
    """Raised when the R2 environment is incomplete."""


class R2ObjectStore:
    """Reads objects from an R2 bucket under a prefix."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        """
        Args:
            client: a preconstructed boto3 S3 client. Supplying it skips all
                environment reading, which is what lets this class be exercised
                against a stub without the ``CIP_R2_*`` variables being set.
        """
        self.bucket = bucket or os.environ.get("CIP_R2_BUCKET") or DEFAULT_BUCKET
        if client is not None:
            self._s3 = client
            return

        endpoint = endpoint or os.environ.get("CIP_R2_ENDPOINT")
        key = access_key_id or os.environ.get("CIP_R2_ACCESS_KEY_ID")
        secret = secret_access_key or os.environ.get("CIP_R2_SECRET_ACCESS_KEY")

        # Fail here, naming what is missing, rather than deep inside the first
        # listing. This repo has a cautionary tale about a stale endpoint that
        # ran silently for three days because the first failure surfaced far
        # from its cause.
        missing = [
            name
            for name, value in (
                ("CIP_R2_ENDPOINT", endpoint),
                ("CIP_R2_ACCESS_KEY_ID", key),
                ("CIP_R2_SECRET_ACCESS_KEY", secret),
            )
            if not value
        ]
        if missing:
            raise R2ConfigError(
                f"R2 configuration incomplete; missing: {', '.join(missing)}"
            )

        import boto3  # type: ignore[import-untyped]  # lazy: module imports without it

        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name="auto",
        )

    def list_objects(self, prefix: str) -> Iterator[StoredObject]:
        """Yield every object under ``prefix``, paginated.

        Paginated rather than a single list_objects_v2 call because that caps
        at 1000 keys and returns a truncated result WITHOUT erroring. A library
        that grew past 1000 files would silently stop being fully enumerated,
        and every file beyond the cap would read as vanished — which, under the
        tombstone rule, would purge their chunks.
        """
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue  # directory placeholder, not a document
                yield StoredObject(
                    key=key,
                    last_modified=obj["LastModified"],
                    size_bytes=int(obj.get("Size", 0)),
                )

    def get_bytes(self, key: str) -> bytes:
        obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        body: bytes = obj["Body"].read()
        return body
