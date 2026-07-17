# foundry: kind=module domain=client-intelligence-platform
"""Project Silk (PS) — nationality-signal harvester, lifted into the package.

WHY THIS EXISTS
---------------
Review M9 (2026-07-17): the FAS scheduler imports executors from the INSTALLED
``cip`` package. ``scripts/`` is not importable from a wheel, so the nationality
harvester could never be wired into the hourly schedule while it lived only in
``scripts/harvest_nationality_signals.py``. This module is the callable the
scheduler drives; the script is now a thin operator-facing wrapper around it —
the exact precedent set by ``cip/integration_mesh/sync/ps_lens_mirror.py``.

The harvester writes SIGNALS, never verdicts (the verdict is derived downstream
in ``lens_ps_china_verdict``, where CHINA WINS: one positive signal locks the
brand). It is idempotent by ``INSERT ... ON CONFLICT DO NOTHING`` on the
``(tenant_id, wayward_brand_id, signal, source_system)`` key.

THE seen_in PRE-STEP (review C2 / M9 root cause)
------------------------------------------------
``ps_brands.seen_in_exclusion_list`` and ``seen_in_eric_sheets`` are a
denormalised cache that ``cip_55`` filled ONCE and nothing has maintained
since (see the ``stale_seen_in_flags`` invariant for the truth conditions).
The harvester READS ``seen_in_eric_sheets`` to emit the DEFINITIONAL
``eric_sheet`` china signal — so a stale cache silently corrupts the
nationality verdict itself. By 2026-07-14 ``seen_in_exclusion_list`` was FALSE
on 26 brands that were on the frozen list ($41,743.82 collected).

So the harvest's FIRST step is a deterministic re-sync of both flags to their
truth (the invariant's own ``EXISTS`` definitions). It runs BEFORE the harvest
on purpose: the ``eric_sheet`` harvest depends on the flag it corrects. It is
idempotent by construction — ``UPDATE ... WHERE flag IS DISTINCT FROM truth``
touches zero rows on a already-consistent book.

THE HEARTBEAT (review M9 + FAS scheduling prerequisite)
-------------------------------------------------------
Every run records a ``cip_sync_runs`` row via ``SyncRunRecorder`` so a
scheduled harvest is observable (liveness + what it did) exactly like every
other CIP sync. ``connector_id='ps-signal-harvest-v1'``, ``sync_mode='incremental'``.

Counter mapping onto the recorder's fields (deployed schema collapses 7 → 5):
  - ``rows_created``  <- signals INSERTed into ps_nationality_signals this run
                        (ON CONFLICT DO NOTHING, so only genuinely-new rows).
  - ``rows_updated``  <- ps_brands rows whose seen_in_* cache the pre-step
                        corrected (distinct rows written).
  - deployed ``rows_ingested`` = rows_created + rows_updated (total rows written).
  - ``rows_history`` / ``rows_skipped`` stay 0: there is no history side-table
    here, and ON CONFLICT DO NOTHING hides the examined-but-skipped count (it is
    not a drift/duplicate skip in the orchestrator's sense).
A dry-run (``apply=False``) rolls the DATA writes back, so nothing is persisted
and the counters are left at 0 — the heartbeat still records that the run
happened, honestly reporting zero persisted rows.

Public API:
  ``run_signal_harvest(engine_or_db, *, tenant_id, apply=True) -> dict``
    Returns a JSON-safe summary dict. Owns its own transactions (like the
    recorder): pass an Engine, or a Connection/Session bound to one.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from cip.integration_mesh.sync_run_recorder import SyncRunRecorder

logger = logging.getLogger(__name__)

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

CONNECTOR_ID = "ps-signal-harvest-v1"
CONNECTOR_NAME = "PS Nationality Signal Harvest"

CN_PARTNERS = (
    "kerry", "cassie", "sarah", "adina", "eric", "shallow",
    "openlight", "chen", "caspar", "dbzw",
)

INSERT = """
    INSERT INTO ps_nationality_signals
        (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
    {select}
    ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
"""

# (name, SELECT). Lifted verbatim from scripts/harvest_nationality_signals.py —
# see that file's docstring for what each signal means and why it is graded as it is.
HARVESTS: list[tuple[str, str]] = [
    # ── DEFINITIONAL ────────────────────────────────────────────────────────
    ("on_exclusion_list", """
        SELECT CAST(:t AS uuid), x.wayward_brand_id, 'on_exclusion_list', 'definitional', 'china',
               'On the frozen exclusion list (bucket: ' || COALESCE(x.bucket,'?') || '). '
               || 'Contract §1.4 defines Excluded Brands as "any and all CHINESE-BASED Brands" — '
               || 'so the list is Wayward and Project Silk jointly asserting, in a signed '
               || 'instrument, that this brand is Chinese. Excluded and Chinese are different '
               || 'questions: this brand still earns us Boost and reactivation money.',
               'contract:exhibit_a_frozen_2025_11_18'
        FROM ps_excluded_brands x
        WHERE x.tenant_id = CAST(:t AS uuid) AND x.wayward_brand_id IS NOT NULL
    """),
    # DEFINITIONAL, by Tim's ruling of 2026-07-14: "ANY that are on an eric list or something are
    # definitely, you dont even need to ask me, CHinese. Exclusion list, heav performaer, or any of
    # them." This was 'strong' until then, which left 71 brands resting on it alone looking like a
    # research queue. They are not. LIST MEMBERSHIP IS THE ANSWER.
    #
    # The one carve-out is BruMate — on the list (OceanWing bucket) and American. Tim ruled it
    # personally, and a pinned ps_added_facts row outranks any machine signal, definitional or not.
    # That is the mechanism: the rule is absolute, and Tim can still overrule it by name.
    #
    # NOTE this reads b.seen_in_eric_sheets — a denormalised cache. The maintenance pre-step in
    # run_signal_harvest re-syncs that flag to its truth BEFORE this runs, so a stale cache can no
    # longer suppress (or invent) an eric_sheet signal.
    ("eric_sheet", """
        SELECT CAST(:t AS uuid), b.wayward_brand_id, 'eric_sheet', 'definitional', 'china',
               'Present in Eric''s all-agreements sheet. Eric''s book IS the China programme — '
               || 'every brand in it was sourced through Chinese referral channels. '
               || 'TIM, 2026-07-14: list membership is DEFINITIVE, not a hint. Do not ask.',
               'gsheet:eric-all-agreements'
        FROM ps_brands b
        WHERE b.tenant_id = CAST(:t AS uuid) AND b.seen_in_eric_sheets
    """),
    # ── CONFIRMED ───────────────────────────────────────────────────────────
    ("wayward_country_cn", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'wayward_country_cn', 'confirmed',
               'china',
               'Wayward''s own onboarding feed records country = CN.',
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid) AND o.field = 'country' AND o.value = 'CN'
          AND o.wayward_brand_id IS NOT NULL
    """),
    ("cjk_in_name", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'cjk_in_name', 'confirmed', 'china',
               'Chinese characters in the ' || o.field || ': ' || o.value,
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid)
          AND o.field IN ('brand_name','contact_name')
          AND o.value ~ '[\\u4e00-\\u9fff]'
          AND o.wayward_brand_id IS NOT NULL
    """),
    # ── STRONG ──────────────────────────────────────────────────────────────
    ("chinese_email_domain", """
        SELECT DISTINCT CAST(:t AS uuid), s.wayward_brand_id, 'chinese_email_domain', 'strong',
               'china',
               'Brand contact uses a Chinese consumer mailbox: ' || s.email,
               'stripe:customers'
        FROM ps_stripe_customers s
        WHERE s.tenant_id = CAST(:t AS uuid) AND s.wayward_brand_id IS NOT NULL
          AND s.email ~* '@(qq|163|126|sina|foxmail|aliyun|139|188|yeah)\\.'
    """),
    ("chinese_email_domain_slack", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'chinese_email_domain', 'strong',
               'china',
               'Onboarding contact uses a Chinese consumer mailbox: ' || o.value,
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid) AND o.field = 'email'
          AND o.value ~* '@(qq|163|126|sina|foxmail|aliyun|139|188|yeah)\\.'
          AND o.wayward_brand_id IS NOT NULL
    """),
    ("chinese_partner", f"""
        SELECT DISTINCT CAST(:t AS uuid), p.wayward_brand_id, 'chinese_partner', 'strong', 'china',
               'Referred by ' || p.partner_of_record || ', one of our China partners. They do not '
               || 'source US brands.',
               'cip:ps_partner_credit'
        FROM ps_partner_credit p
        WHERE p.tenant_id = CAST(:t AS uuid) AND p.wayward_brand_id IS NOT NULL
          AND p.partner_of_record IN ({", ".join(f"'{x}'" for x in CN_PARTNERS)})
    """),
    # ── NEGATIVE ────────────────────────────────────────────────────────────
    # ISO-2 ONLY. Two brands carry HubSpot page furniture in this field — one of them is Tiny
    # Land, which is Chinese, has collected $11,524, and has been paid $0. Treating that string
    # as "a foreign country" is what disqualified it.
    ("wayward_country_other", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'wayward_country_other', 'negative',
               'not_china',
               'Wayward''s onboarding feed records country = ' || o.value || ' (a real ISO-2 code, '
               || 'not CN). NOTE: this only decides the brand if NO positive China signal exists — '
               || 'a US flag is routinely just a US-registered shell for a Chinese operator.',
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid) AND o.field = 'country'
          AND o.value ~ '^[A-Z]{2}$' AND o.value <> 'CN'
          AND o.wayward_brand_id IS NOT NULL
    """),
]


def _resolve_engine(engine_or_db: Any) -> Engine:
    """Normalise an Engine / Connection / Session down to the Engine.

    ``SyncRunRecorder`` owns its own short-lived connections (``engine.begin()``)
    and this harvester owns its own work transaction, so both need the Engine —
    not a live Connection. Accepting the union keeps the FAS executor contract
    (``function(db, ...)``) and ad-hoc/test callers happy without a cast.
    """
    if isinstance(engine_or_db, Engine):
        return engine_or_db
    bound = getattr(engine_or_db, "engine", None)  # Connection.engine
    if isinstance(bound, Engine):
        return bound
    get_bind = getattr(engine_or_db, "get_bind", None)  # Session.get_bind()
    if callable(get_bind):
        bind = get_bind()
        if isinstance(bind, Engine):
            return bind
        bind_engine = getattr(bind, "engine", None)
        if isinstance(bind_engine, Engine):
            return bind_engine
    raise TypeError(
        "run_signal_harvest needs an Engine (or a Connection/Session bound to "
        f"one); got {type(engine_or_db)!r}"
    )


def _maintain_seen_in_flags(conn: Connection, tenant_id: str) -> dict[str, int]:
    """Re-sync ps_brands.seen_in_{exclusion_list,eric_sheets} to their truth.

    The truth conditions are the ``stale_seen_in_flags`` invariant's own
    ``EXISTS`` definitions — this maintenance is precisely what drives that
    invariant back to zero. Deterministic + idempotent: the WHERE clause only
    matches rows where a flag ``IS DISTINCT FROM`` its truth, so a second run
    over a consistent book updates nothing.

    Returns per-flag corrected counts plus the distinct-row count actually
    written (a row wrong on both flags is one written row, two per-flag
    corrections). Must be called inside the tenant-scoped work transaction.
    """
    excl_corrected = conn.execute(
        text(
            """
            SELECT count(*) FROM ps_brands b
            WHERE b.tenant_id = CAST(:t AS uuid)
              AND b.seen_in_exclusion_list IS DISTINCT FROM EXISTS (
                    SELECT 1 FROM ps_excluded_brands x
                     WHERE x.wayward_brand_id = b.wayward_brand_id)
            """
        ),
        {"t": tenant_id},
    ).scalar() or 0
    eric_corrected = conn.execute(
        text(
            """
            SELECT count(*) FROM ps_brands b
            WHERE b.tenant_id = CAST(:t AS uuid)
              AND b.seen_in_eric_sheets IS DISTINCT FROM EXISTS (
                    SELECT 1 FROM ps_brand_observations o
                     WHERE o.wayward_brand_id = b.wayward_brand_id
                       AND o.source_system = 'gsheet:eric-all-agreements')
            """
        ),
        {"t": tenant_id},
    ).scalar() or 0
    res = conn.execute(
        text(
            """
            UPDATE ps_brands b SET
                seen_in_exclusion_list = EXISTS (
                    SELECT 1 FROM ps_excluded_brands x
                     WHERE x.wayward_brand_id = b.wayward_brand_id),
                seen_in_eric_sheets = EXISTS (
                    SELECT 1 FROM ps_brand_observations o
                     WHERE o.wayward_brand_id = b.wayward_brand_id
                       AND o.source_system = 'gsheet:eric-all-agreements')
            WHERE b.tenant_id = CAST(:t AS uuid)
              AND (
                b.seen_in_exclusion_list IS DISTINCT FROM EXISTS (
                    SELECT 1 FROM ps_excluded_brands x
                     WHERE x.wayward_brand_id = b.wayward_brand_id)
                OR b.seen_in_eric_sheets IS DISTINCT FROM EXISTS (
                    SELECT 1 FROM ps_brand_observations o
                     WHERE o.wayward_brand_id = b.wayward_brand_id
                       AND o.source_system = 'gsheet:eric-all-agreements')
              )
            """
        ),
        {"t": tenant_id},
    )
    rows_corrected = res.rowcount or 0
    return {
        "seen_in_exclusion_list_corrected": int(excl_corrected),
        "seen_in_eric_sheets_corrected": int(eric_corrected),
        "rows_corrected": int(rows_corrected),
    }


def run_signal_harvest(
    engine_or_db: Any,
    *,
    tenant_id: str | UUID,
    apply: bool = True,
) -> dict[str, Any]:
    """Harvest every automatic China signal we already hold, idempotently.

    Steps, all inside ONE tenant-scoped work transaction:
      1. maintenance — re-sync the ``seen_in_*`` denormalised cache to truth
         (review C2/M9): the ``eric_sheet`` harvest reads a flag this corrects.
      2. harvest — ``INSERT ... ON CONFLICT DO NOTHING`` for every signal.
      3. summary — the verdict roll-up from ``lens_ps_china_verdict``.

    The whole run is wrapped in a ``SyncRunRecorder`` heartbeat (M9). The
    recorder owns SEPARATE short-lived connections, so the heartbeat persists
    even when a dry-run rolls the work transaction back.

    Args:
      engine_or_db: an Engine, or a Connection/Session bound to one. The
        function manages its own transactions (see ``_resolve_engine``).
      tenant_id: PS tenant UUID (str or UUID). No hardcoded default — the
        caller supplies it (D-017/018/031).
      apply: True commits the harvest + maintenance; False (dry-run) rolls the
        DATA writes back. The heartbeat is recorded either way; on a dry-run
        its counters stay 0 because nothing was persisted.

    Returns a JSON-safe dict (no UUIDs/Decimals/datetimes):
      ``{tenant_id, applied, seen_in_maintenance:{...}, harvested:{signal:int},
         signals_inserted, verdicts:[{verdict,strength,brands,collected}],
         sync_run_id, sync_run_status}``.
    """
    engine = _resolve_engine(engine_or_db)
    tenant_uuid = UUID(str(tenant_id))
    tenant_str = str(tenant_uuid)

    with SyncRunRecorder(
        engine,
        tenant_id=tenant_uuid,
        client_id=None,
        connector_id=CONNECTOR_ID,
        connector_name=CONNECTOR_NAME,
        sync_mode="incremental",
    ) as run:
        with engine.connect() as conn:
            # Transaction-local tenant GUC (RLS scope) for the whole work txn.
            conn.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"),
                {"t": tenant_str},
            )

            # Step 1 — the cache the harvest depends on, brought to truth FIRST.
            maintenance = _maintain_seen_in_flags(conn, tenant_str)

            # Step 2 — harvest the signals.
            harvested: dict[str, int] = {}
            for name, select in HARVESTS:
                r = conn.execute(text(INSERT.format(select=select)), {"t": tenant_str})
                harvested[name] = r.rowcount or 0

            # Step 3 — the verdict roll-up (nationality only; cip_110 dropped the
            # vestigial money columns — money lives in lens_ps_claim).
            verdicts = [
                dict(zip(("verdict", "strength", "brands", "collected"), row, strict=False))
                for row in conn.execute(
                    text(
                        """
                        SELECT verdict, COALESCE(verdict_strength, '-'),
                               count(*), round(sum(usage_collected), 2)
                        FROM lens_ps_china_verdict
                        GROUP BY 1, 2
                        ORDER BY 3 DESC NULLS LAST
                        """
                    )
                ).fetchall()
            ]

            if apply:
                conn.commit()
            else:
                conn.rollback()

        signals_inserted = sum(harvested.values())

        # Heartbeat counters reflect what was PERSISTED. A dry-run persisted
        # nothing (rolled back), so its counters stay at 0.
        if apply:
            run.counters.rows_created = signals_inserted
            run.counters.rows_updated = maintenance["rows_corrected"]

    logger.info(
        "signal-harvest tenant=%s applied=%s signals_inserted=%d flags_corrected=%d status=%s",
        tenant_str, apply, signals_inserted, maintenance["rows_corrected"], run.final_status,
    )

    return {
        "tenant_id": tenant_str,
        "applied": apply,
        "seen_in_maintenance": maintenance,
        "harvested": harvested,
        "signals_inserted": signals_inserted,
        "verdicts": verdicts,
        "sync_run_id": str(run.run_id),
        "sync_run_status": run.final_status,
    }
