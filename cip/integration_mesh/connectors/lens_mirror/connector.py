# foundry: kind=service domain=client-intelligence-platform touches=integration
"""LensMirrorConnector — read a source tenant's lens_* view, yield dicts.

Per Atlas-locked design (docs/vision/ATLAS-REVIEW-PHASE-2.6-RESPONSE.md
§Q4 + §C-1) for PM scope 280a2f20.

KEY ARCHITECTURAL POINTS:

- `tenant_id` is the DESTINATION (e.g., Project Silk). The orchestrator
  drives writes under PS's RLS context. This connector reads from a
  DIFFERENT tenant (source_tenant_id, e.g., EcomLever).

- Atlas Q4 verdict was "safe — premise was wrong." The deployed
  orchestrator already separates `stream_records()`'s read connection
  from the per-batch write Session. So this connector opens its OWN
  short-lived read connection bound to the source_tenant_id GUC,
  materializes source rows fully into memory, closes that connection,
  then yields the buffered dicts back to the orchestrator. The
  orchestrator's per-batch Session then opens under the DEST tenant
  GUC. Two connections, each with a single stable tenant context.
  No "two GUC swaps per session."

- Source rows are tagged with `_source_tenant_id` and `_source_lens` in
  the yielded dict so the mapper can distinguish multi-pass calls and
  for debugging.

- The connector is configured for ONE source lens view + ONE destination
  entity per instance. Phase 2.6 instantiates the connector 3 times
  (one per entity: deals, companies, contacts) and the two-pass
  orchestrator (`scripts/orchestrate_ps_lens_mirror.py`) drives them
  through `run_sync()` sequentially.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from cip.integration_mesh.base import (
    DEFAULT_RATE_LIMIT,
    CIPConnectorBase,
    PropertyDescriptor,
    RateLimitPolicy,
)


class LensMirrorConnector(CIPConnectorBase):
    """Reads one source-tenant lens view, yields each row tagged with
    provenance so the orchestrator + mapper can route it to the
    destination tenant's `cip_*` table.

    Usage::

        connector = LensMirrorConnector(
            tenant_id=PS_TENANT_UUID,
            source_tenant_id=ECOMLEVER_TENANT_UUID,
            source_lens="lens_china_clients",   # source view name
            source_engine=source_engine_or_dsn,  # str (DSN) or Engine
            connector_id="lens-mirror-deals-v1",
        )
        mapper = LensMirrorDealMapper(client_id_lookup=client_lookup)
        run_sync(connector, mapper, engine,
                 tenant_id=PS_TENANT_UUID, sync_mode="lens-mirror")
    """

    # connector_id varies per (entity, source_tenant) — set in __init__.
    cursor_safety_window_seconds: int = 0  # full-mirror, no replica lag concern
    version: str = "1.0.0"

    def __init__(
        self,
        tenant_id: UUID,
        *,
        source_tenant_id: UUID,
        source_lens: str,
        source_engine: Engine | str,
        connector_id: str,
        materialize_limit: int | None = None,
    ) -> None:
        """
        Args:
            tenant_id: DESTINATION tenant (e.g., Project Silk).
            source_tenant_id: SOURCE tenant (e.g., EcomLever). Used to
                set `app.current_tenant` GUC on the read connection.
            source_lens: SQL view name to SELECT from (e.g.,
                `lens_china_companies`).
            source_engine: SQLAlchemy Engine or DSN string for the source
                Postgres. May point at the same database as the
                destination — the GUC swap on a fresh connection handles
                tenant isolation cleanly (Atlas Q4 verdict).
            connector_id: Stable id for the cip_sync_runs / advisory-lock
                key (`lens-mirror-deals-v1`, etc.).
            materialize_limit: Optional row cap (for safety in tests; None
                means yield everything).
        """
        self.tenant_id = tenant_id
        self.source_tenant_id = source_tenant_id
        self.source_lens = source_lens
        self.connector_id = connector_id
        self.materialize_limit = materialize_limit
        # Normalize source_engine to an Engine. If DSN string, create a
        # short-lived NullPool-friendly engine. We do NOT cache long-lived
        # state on the source engine — each stream_records() call opens
        # and closes its own connection.
        if isinstance(source_engine, str):
            self._source_engine: Engine = create_engine(
                source_engine.replace("postgresql://", "postgresql+psycopg://")
                              .replace("postgres://", "postgresql+psycopg://"),
                pool_pre_ping=True,
            )
        else:
            self._source_engine = source_engine
        self._authenticated = False

    @property
    def rate_limit_policy(self) -> RateLimitPolicy:
        # Source is Postgres — local DB, not rate-limited externally.
        return DEFAULT_RATE_LIMIT

    def authenticate(self) -> None:
        """No-op: Postgres connection auth happens on connect()."""
        self._authenticated = True

    def stream_records(
        self,
        cursor: dict[str, object] | None,
        batch_size: int,
    ) -> Iterator[dict[str, object]]:
        """Yield each row from `source_lens` as a dict.

        - Opens a fresh connection bound to source_tenant_id via GUC
          (Atlas Q4 — separate from the orchestrator's write Session).
        - Materializes ALL rows into memory (Atlas explicit: "materialize-
          then-yield"). Source data is bounded for the PS case (Wayward's
          China subset is ~1,400 deals + ~1,400 companies + ~1,000
          contacts), so memory is not a concern.
        - Closes the source connection BEFORE yielding (so the read
          connection isn't held while the orchestrator's writes run).

        cursor is ignored for full-mirror semantics — the lens view IS
        the cursor (every run rescans the current source state).
        """
        # Materialize the source view under the source GUC.
        rows: list[dict[str, object]] = []
        with self._source_engine.begin() as conn:
            conn.execute(text(
                "SELECT set_config('app.current_tenant', :t, true)"
            ), {"t": str(self.source_tenant_id)})
            sql = f"SELECT * FROM {self.source_lens}"
            if self.materialize_limit is not None:
                sql += f" LIMIT {int(self.materialize_limit)}"
            result = conn.execute(text(sql))
            for row in result.mappings():
                d = dict(row)
                # Tag each row so the mapper / debugger can distinguish.
                d["_source_tenant_id"] = str(self.source_tenant_id)
                d["_source_lens"] = self.source_lens
                rows.append(d)
        # Source connection closes here (engine.begin() context). Yield
        # buffered rows back to the orchestrator.
        for row in rows:
            yield row

    def describe_schema(self) -> list[PropertyDescriptor]:
        """Lens-mirror does NOT introduce new properties to the registry.
        The destination tables' property registries are inherited from
        the source ingestion (HubSpot/Zendesk connector schemas).
        """
        return []

    def incremental_key(self, record: dict[str, object]) -> datetime:
        """Return the lens row's last-modified timestamp.

        Lens views project source-table columns, so `refreshed_at` (the
        source row's ingest-pipeline refresh time) is the natural cursor
        when callers run in incremental mode. The lens-mirror connector
        is normally run in full-mirror mode (`sync_mode='lens-mirror'`),
        which ignores cursors, but we implement this for protocol
        completeness.
        """
        val = (
            record.get("refreshed_at")
            or record.get("updated_at")
            or record.get("ingested_at")
        )
        if isinstance(val, datetime):
            if val.tzinfo is None:
                return val.replace(tzinfo=UTC)
            return val
        # Fallback — UTC now (forces re-evaluation on next sync; safe
        # because lens-mirror runs full each time anyway).
        return datetime.now(UTC)
