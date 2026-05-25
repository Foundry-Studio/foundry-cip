# foundry: kind=service domain=client-intelligence-platform touches=integration,security
"""Leg B — CRM → CIP companion_data writeback.

Per Atlas-locked Phase 2.8 Leg B deep plan v2 (2026-05-23). Reads
PS-team-curated brand enrichments out of the Foundry-CRM Postgres and
writes them into ``cip_clients.companion_data`` JSONB on the matching
PS-tenant rows.

KEY CONTRACTS (all LOCKED — do not relax):

  - Direction: CRM is authoritative for the 13 managed companion keys
    (CIP-SPEC-012 §2). The mirror never writes them. Leg B is the
    only writer of ``cip_*.companion_data``.

  - Join key: ``companies.external_ids->>'cip_client_id'`` (CRM) =
    ``cip_clients.id`` (CIP UUID PK — set by Leg A). NOT
    ``cip_clients.source_id``.

  - Role: must connect to CIP as ``cip_twenty_project_silk`` (cip_25).
    The role is ``NOSUPERUSER NOBYPASSRLS``, has SELECT on the 5
    PS-relevant entity tables, and column-level
    ``UPDATE (companion_data)`` only.

  - GUC: ``set_config('app.current_tenant', PS_TENANT_ID, true)`` at
    the top of EACH per-brand transaction. Read-preflight + write
    share the same txn so the txn-local GUC covers both. No GUC =
    zero rows visible (fail-closed via RLS).

  - Merge + change-detect in SQL:
        UPDATE cip_clients
           SET companion_data = companion_data || :managed::jsonb
         WHERE id = :cip_client_id
           AND (companion_data || :managed::jsonb)
                 IS DISTINCT FROM companion_data
    Idempotent no-op when nothing changed (no churny updated_at).

  - Per-UPDATE: assert ``rowcount in (0, 1)``. 1 = changed, 0 = no-op.
    Anything else = LOUD failure (we hit multiple rows, contract broken).

  - Preflight: load the full set of valid PS ``cip_clients.id``s. Any
    CRM-supplied ``cip_client_id`` not in this set is a dangling /
    cross-tenant / Leg-A-bug signal — ALERT, do NOT silently pass.

  - Enum miss = warn + SKIP that one key. Never overwrite a curated
    companion value with ``unknown`` or drop the key. Only clean
    in-enum values are written.

  - ``ps_lead_owner_email`` is DEFERRED — CRM has no users/owners
    table to resolve ``owner_id`` UUID to email. Re-add when CRM
    promotes a users table.

  - Observability: the role cannot write ``cip_sync_runs`` (denied
    by cip_25's REVOKE on that table). Run summary is emitted as a
    structured ``RunSummary`` returned by ``run_writeback``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("cip.sync.crm_companion_writeback")


# Canonical Project Silk tenant — matches cip_26 view bodies + cip_25 role
# scope. Stay aligned if it ever moves.
PS_TENANT_ID = UUID("078a37d6-6ae2-4e22-869e-cc08f6cb2787")

# ── Enum allowlists (CIP-SPEC-012 §3) ─────────────────────────────────────
_PS_SEGMENT_VALUES: frozenset[str] = frozenset({"china_referral"})
_PS_ONBOARDED_STATUS_VALUES: frozenset[str] = frozenset(
    {"prospect", "contracted", "onboarded", "paused", "offboarded"}
)
_PS_ENGAGEMENT_HEALTH_VALUES: frozenset[str] = frozenset(
    {"producing", "green", "yellow", "red", "unknown"}
)
_PS_INVOICE_CADENCE_VALUES: frozenset[str] = frozenset(
    {"monthly", "quarterly", "per-shipment"}
)
# Attribution layer (CIP-SPEC-012 §3.4/§3.5, added 2026-05-25 / cip_34).
_PS_ATTRIBUTION_OWNER_VALUES: frozenset[str] = frozenset(
    {"PS", "unclassified", "Eric", "Adina", "OpenLight", "Oceanwing",
     "Jeremy Dai", "Shallow", "heavy_producer"}
)
# ps_lead_source = same set minus the non-referral values.
_PS_LEAD_SOURCE_VALUES: frozenset[str] = frozenset(
    {"PS", "Eric", "Adina", "OpenLight", "Oceanwing", "Jeremy Dai", "Shallow"}
)
_PS_CONDITIONAL_VALUES: frozenset[str] = frozenset({"finders_fee"})

# CRM ``companies.onboarding_status`` and ``status`` may use slightly
# different vocabulary than CIP-SPEC-012's enum. Map known CRM values to
# the CIP enum. Anything not in this map will fail enum validation and
# the key will be SKIPPED (warn + leave prior curated value alone).
_ONBOARDED_STATUS_CRM_TO_CIP: dict[str, str] = {
    # Direct passthrough (CRM uses the same vocabulary):
    "prospect": "prospect",
    "contracted": "contracted",
    "onboarded": "onboarded",
    "paused": "paused",
    "offboarded": "offboarded",
    # CRM ``status`` column maps (CRM uses 'active'/'churned' etc.):
    "active": "onboarded",
    "churned": "offboarded",
    "on_hold": "paused",
    "suspended": "paused",
    "inactive": "paused",
    "archived": "offboarded",
}

# CRM ``payment_terms`` → ``ps_invoice_cadence`` (when CRM stores a known
# cadence keyword). The CRM column is freeform ``String(30)``; we try to
# normalize. Anything unknown skips the key.
_INVOICE_CADENCE_CRM_TO_CIP: dict[str, str] = {
    "monthly": "monthly",
    "month": "monthly",
    "quarterly": "quarterly",
    "quarter": "quarterly",
    "per-shipment": "per-shipment",
    "per shipment": "per-shipment",
    "shipment": "per-shipment",
}

# ``payment_terms`` may be a free-form string carrying "net 30" / "Net60"
# style values. Pull the integer if present; otherwise drop the key.
_NET_DAYS_RE = re.compile(r"\bnet\s*(\d{1,3})\b", re.IGNORECASE)
_PURE_DAYS_RE = re.compile(r"^\s*(\d{1,3})\s*(days?)?\s*$", re.IGNORECASE)


# ── Run summary (out-of-band observability) ────────────────────────────────

@dataclass
class RunSummary:
    """Structured per-run counters. The role cannot write ``cip_sync_runs``;
    callers log this dict + optionally route it to a metrics sink.

    Fields:
      selected — CRM companies read with non-null cip_client_id
      updated  — UPDATE rowcount=1 (companion_data changed)
      unchanged — UPDATE rowcount=0 (no-op; data already current)
      skipped_no_key — CRM rows without external_ids.cip_client_id
      skipped_dangling — cip_client_id present but not in PS valid set
      enum_coerced_skipped — per-key drops from enum validation (sum across rows)
      partner_skipped_ambiguous — companies with >1 partner via FK; commission_pct dropped
      errors — unexpected per-row errors (logged but tolerated)
    """
    selected: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_no_key: int = 0
    skipped_dangling: int = 0
    enum_coerced_skipped: int = 0
    partner_skipped_ambiguous: int = 0
    errors: int = 0
    dangling_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Field map (pure: CRM row dict → managed companion keys dict) ───────────

def _coerce_enum(
    value: Any,
    allowed: frozenset[str],
    *,
    crm_to_cip: dict[str, str] | None = None,
    key_name: str,
    summary: RunSummary,
    cip_client_id: str | None,
    case_sensitive: bool = False,
) -> str | None:
    """Normalize + validate. Returns the validated CIP value, or None
    if the input is missing/unknown (key will be SKIPPED — i.e. NOT
    included in the managed dict, so the merge keeps prior curated value).

    ``case_sensitive=True`` skips the lower-casing pass — used for the
    attribution values whose canonical form is mixed-case (``Eric``,
    ``Jeremy Dai``, ``PS``); only trim is applied.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    candidate = s if case_sensitive else s.lower()
    if crm_to_cip is not None:
        candidate = crm_to_cip.get(candidate, candidate)
    if candidate in allowed:
        return candidate
    # Enum miss: warn + skip.
    summary.enum_coerced_skipped += 1
    log.warning(
        "enum miss on %s: value=%r not in allowed=%s; skipping key "
        "(cip_client_id=%s) — prior curated value (if any) is preserved",
        key_name, value, sorted(allowed), cip_client_id,
    )
    return None


def _parse_payment_terms_days(value: Any) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _NET_DAYS_RE.search(s)
    if m:
        return int(m.group(1))
    m = _PURE_DAYS_RE.match(s)
    if m:
        return int(m.group(1))
    return None


def _normalize_invoice_cadence(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    return _INVOICE_CADENCE_CRM_TO_CIP.get(s)


def _to_jsonable(value: Any) -> Any:
    """Coerce Python values to JSON-safe primitives.

    ``Decimal`` → ``float``; ``date``/``datetime`` → ISO-8601 string;
    everything else passes through. This is for the per-key clean payload
    we hand to psycopg as ``json.dumps(...)``-ed text — the SQL `||` does
    the actual merge inside Postgres, so we just need JSON-serializable
    primitives here.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_managed_companion(
    crm_company: dict[str, Any],
    partner: dict[str, Any] | None,
    *,
    summary: RunSummary,
) -> dict[str, Any]:
    """Pure: assemble the managed companion-keys dict from a CRM company
    (+ optional partner row for commission). Validates enums; SKIPs keys
    that fail validation (logged via ``summary``).

    Returned dict contains ONLY the managed keys (CIP-SPEC-012 §2 minus
    the deferred ``ps_lead_owner_email``). Keys that are None / missing
    / enum-rejected / partner-ambiguous are OMITTED — they are not
    written, so SQL ``||`` preserves any prior curated value.

    Args:
        crm_company: a row-mapping from CRM ``companies`` table (column
            name → value). Required keys for join detection are checked
            by the caller; this builder is pure on the in-memory dict.
        partner: the chosen ``partners`` row for this company, or None
            if there isn't one. If multiple partners match the company
            and the caller decided ambiguously, pass None — caller
            tracks the ``partner_skipped_ambiguous`` counter.
        summary: mutable counter sink for enum-skip logging.

    Returns:
        ``{managed_key: jsonable_value}`` — possibly empty.
    """
    cid = crm_company.get("external_ids", {}).get("cip_client_id") if isinstance(
        crm_company.get("external_ids"), dict
    ) else None
    cid_str = str(cid) if cid else None
    raw_metadata = crm_company.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    managed: dict[str, Any] = {}

    # ps_segment — v1 pins to 'china_referral' but accepts a metadata
    # override so a future segment can land without a Leg B change.
    seg_raw = metadata.get("ps_segment") or "china_referral"
    seg_val = _coerce_enum(
        seg_raw, _PS_SEGMENT_VALUES,
        key_name="ps_segment", summary=summary, cip_client_id=cid_str,
    )
    if seg_val is not None:
        managed["ps_segment"] = seg_val

    # ps_onboarded_status — try onboarding_status first (more specific),
    # fall back to status.
    onboard_raw = crm_company.get("onboarding_status") or crm_company.get("status")
    onboard_val = _coerce_enum(
        onboard_raw, _PS_ONBOARDED_STATUS_VALUES,
        crm_to_cip=_ONBOARDED_STATUS_CRM_TO_CIP,
        key_name="ps_onboarded_status", summary=summary, cip_client_id=cid_str,
    )
    if onboard_val is not None:
        managed["ps_onboarded_status"] = onboard_val

    # ps_engagement_health — CRM has no typed column for this; carrier is
    # metadata.engagement_health.
    health_raw = metadata.get("engagement_health")
    health_val = _coerce_enum(
        health_raw, _PS_ENGAGEMENT_HEALTH_VALUES,
        key_name="ps_engagement_health", summary=summary, cip_client_id=cid_str,
    )
    if health_val is not None:
        managed["ps_engagement_health"] = health_val

    # ps_local_alias_zh / _en
    alias_zh = metadata.get("alias_zh")
    if isinstance(alias_zh, str) and alias_zh.strip():
        managed["ps_local_alias_zh"] = alias_zh.strip()
    dba = crm_company.get("dba_name")
    if isinstance(dba, str) and dba.strip():
        managed["ps_local_alias_en"] = dba.strip()

    # ps_team_notes
    notes = metadata.get("team_notes")
    if isinstance(notes, str) and notes.strip():
        managed["ps_team_notes"] = notes.strip()

    # ps_commission_pct — from partner.commission_rate (Numeric(5,2)).
    if partner is not None:
        rate = partner.get("commission_rate")
        if rate is not None:
            try:
                rate_f = float(rate)
            except (TypeError, ValueError):
                rate_f = None
            if rate_f is not None:
                managed["ps_commission_pct"] = rate_f

    # ps_billing_currency
    curr = crm_company.get("billing_currency")
    if isinstance(curr, str) and curr.strip():
        managed["ps_billing_currency"] = curr.strip().upper()

    # ps_invoice_cadence — normalized via cadence map
    cadence_val = _normalize_invoice_cadence(crm_company.get("payment_terms"))
    if cadence_val is not None:
        cadence_checked = _coerce_enum(
            cadence_val, _PS_INVOICE_CADENCE_VALUES,
            key_name="ps_invoice_cadence", summary=summary, cip_client_id=cid_str,
        )
        if cadence_checked is not None:
            managed["ps_invoice_cadence"] = cadence_checked

    # ps_payment_terms_days — parse 'net 30' / '30' / '60 days' style
    days = _parse_payment_terms_days(crm_company.get("payment_terms"))
    if days is not None:
        managed["ps_payment_terms_days"] = days

    # ps_first_onboarded_date
    cs = crm_company.get("customer_since")
    if cs is not None:
        managed["ps_first_onboarded_date"] = _to_jsonable(cs)

    # ps_last_reviewed_date — metadata.last_reviewed
    lr = metadata.get("last_reviewed")
    if lr is not None:
        managed["ps_last_reviewed_date"] = _to_jsonable(lr)

    # ── Attribution layer (CIP-SPEC-012 §3.4/§3.5, cip_34) ──────────────
    # CRM carries these as metadata keys (Twenty custom fields). Mixed-case
    # canonical values (Eric / Jeremy Dai / PS), so case_sensitive=True.
    attr_owner = _coerce_enum(
        metadata.get("ps_attribution_owner"), _PS_ATTRIBUTION_OWNER_VALUES,
        key_name="ps_attribution_owner", summary=summary,
        cip_client_id=cid_str, case_sensitive=True,
    )
    if attr_owner is not None:
        managed["ps_attribution_owner"] = attr_owner

    lead_source = _coerce_enum(
        metadata.get("ps_lead_source"), _PS_LEAD_SOURCE_VALUES,
        key_name="ps_lead_source", summary=summary,
        cip_client_id=cid_str, case_sensitive=True,
    )
    if lead_source is not None:
        managed["ps_lead_source"] = lead_source

    conditional = _coerce_enum(
        metadata.get("ps_conditional"), _PS_CONDITIONAL_VALUES,
        key_name="ps_conditional", summary=summary,
        cip_client_id=cid_str, case_sensitive=True,
    )
    if conditional is not None:
        managed["ps_conditional"] = conditional

    # ps_sales_lead / ps_cs_lead — free-form PS staff emails (CRM-owned).
    sales_lead = metadata.get("ps_sales_lead")
    if isinstance(sales_lead, str) and sales_lead.strip():
        managed["ps_sales_lead"] = sales_lead.strip().lower()
    cs_lead = metadata.get("ps_cs_lead")
    if isinstance(cs_lead, str) and cs_lead.strip():
        managed["ps_cs_lead"] = cs_lead.strip().lower()

    return managed


# ── Writer ─────────────────────────────────────────────────────────────────

_SELECT_VALID_IDS_SQL = text(
    """
    SELECT id
    FROM cip_clients
    WHERE id = ANY(:ids ::uuid[])
    """
)

# NOTE: ``updated_at`` is intentionally NOT set here — the
# ``cip_twenty_project_silk`` role only has column-level
# ``UPDATE (companion_data)`` per cip_25, and writing to ``updated_at``
# would fail with permission denied. If the application needs a
# "companion last touched" signal, derive it from a JSONB sub-key
# inside companion_data or add a per-row BEFORE UPDATE trigger that
# the role's UPDATE statement implicitly fires.
_UPDATE_COMPANION_SQL = text(
    """
    UPDATE cip_clients
       SET companion_data = companion_data || CAST(:managed AS jsonb)
     WHERE id = :cip_client_id
       AND (companion_data || CAST(:managed AS jsonb)) IS DISTINCT FROM companion_data
    """
)


def _select_crm_companies(crm_conn: Connection) -> list[dict[str, Any]]:
    """Read PS-mirror-linked CRM companies + their (optional) primary partner.

    Filters to rows that carry the Leg-A linkage marker
    (``external_ids ? 'cip_client_id'`` AND ``data_source = 'cip-mirror'``).
    Soft-deleted rows are excluded.

    Returns a list of dicts (one per company) with ALL columns the field
    map reads + an optional ``_partner`` sub-dict (or None) carrying the
    chosen partner row for commission lookup.

    Partner selection: companies → partners via ``partners.company_id``.
    If exactly one matching partner exists, use it. If >1 exists, pick
    the most-recent by ``updated_at`` (deterministic); if ``updated_at``
    is also tied, the caller will receive None for partner and the
    commission key will be dropped (ambiguous).
    """
    rows = crm_conn.execute(text(
        """
        SELECT id, external_ids, metadata, onboarding_status, status,
               dba_name, billing_currency, payment_terms, customer_since,
               data_source
        FROM companies
        WHERE data_source = 'cip-mirror'
          AND external_ids ? 'cip_client_id'
          AND COALESCE(is_deleted, false) = false
        """
    )).mappings().all()
    companies: list[dict[str, Any]] = [dict(r) for r in rows]
    if not companies:
        return []

    company_ids = [c["id"] for c in companies]
    partner_rows = crm_conn.execute(text(
        """
        SELECT company_id, commission_rate, updated_at
        FROM partners
        WHERE company_id = ANY(:cids ::uuid[])
          AND status = 'active'
        """
    ), {"cids": company_ids}).mappings().all()

    partners_by_company: dict[Any, list[dict[str, Any]]] = {}
    for p in partner_rows:
        partners_by_company.setdefault(p["company_id"], []).append(dict(p))

    for c in companies:
        bucket = partners_by_company.get(c["id"], [])
        if len(bucket) == 1:
            c["_partner"] = bucket[0]
        elif len(bucket) > 1:
            # Deterministic pick: most-recent updated_at, then highest
            # commission_rate as tiebreaker. If still tied, skip.
            bucket.sort(
                key=lambda r: (
                    r.get("updated_at") or datetime.min,
                    r.get("commission_rate") or Decimal("0"),
                ),
                reverse=True,
            )
            top, second = bucket[0], bucket[1]
            if (
                top.get("updated_at") == second.get("updated_at")
                and top.get("commission_rate") == second.get("commission_rate")
            ):
                c["_partner"] = None  # truly ambiguous
                c["_partner_ambiguous"] = True
            else:
                c["_partner"] = top
        else:
            c["_partner"] = None
    return companies


def _set_guc(conn: Connection) -> None:
    """SELECT set_config('app.current_tenant', PS, true) — txn-local GUC.
    MUST be called inside an open txn so SET LOCAL semantics apply.
    """
    conn.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(PS_TENANT_ID)},
    )


def run_writeback(
    *,
    crm_engine: Engine,
    cip_engine: Engine,
) -> RunSummary:
    """Execute one Leg B writeback pass.

    Args:
        crm_engine: SQLAlchemy Engine bound to the CRM Postgres
            (read-only credential — Leg B never writes to CRM).
        cip_engine: SQLAlchemy Engine bound to the CIP Postgres
            authenticated as ``cip_twenty_project_silk`` (column-level
            UPDATE(companion_data) only).

    Returns:
        ``RunSummary`` with per-bucket counts. The caller logs/exports.

    Raises:
        Re-raises any per-brand UPDATE that returns rowcount > 1 (broken
        contract — multiple rows matched a ``WHERE id=:uuid`` PK lookup).
        Other per-row errors are tolerated and counted in ``summary.errors``;
        the next brand is attempted.
    """
    summary = RunSummary()

    import json

    # ── 1. Read CRM batch ─────────────────────────────────────────────────
    with crm_engine.connect() as crm_conn:
        companies = _select_crm_companies(crm_conn)

    summary.selected = len(companies)
    if not companies:
        log.info("crm_companion_writeback: no CRM rows match Leg-A linkage; nothing to do")
        return summary

    # Companies missing the linkage key are NOT returned by the SQL filter,
    # so we don't see them. Track an explicit no-key counter for any row
    # that snuck through (defensive — should always be 0 with the filter).
    candidate_ids: list[str] = []
    for c in companies:
        eid = c.get("external_ids") or {}
        cid = eid.get("cip_client_id") if isinstance(eid, dict) else None
        if not cid:
            summary.skipped_no_key += 1
            continue
        candidate_ids.append(str(cid))

    # ── 2. Single CIP txn: GUC + preflight + per-brand UPDATEs ────────────
    with cip_engine.begin() as cip_conn:
        _set_guc(cip_conn)
        valid_rows = cip_conn.execute(
            _SELECT_VALID_IDS_SQL, {"ids": candidate_ids}
        ).all()
        valid_ids: set[str] = {str(r[0]) for r in valid_rows}

        for c in companies:
            eid = c.get("external_ids") or {}
            cid = eid.get("cip_client_id") if isinstance(eid, dict) else None
            if not cid:
                continue  # already counted as skipped_no_key
            cid_str = str(cid)
            if cid_str not in valid_ids:
                summary.skipped_dangling += 1
                summary.dangling_ids.append(cid_str)
                log.error(
                    "DANGLING cip_client_id from CRM: %s — not in PS valid "
                    "set (Leg-A bug, soft-deleted, or cross-tenant attempt). "
                    "Skipping; investigate.",
                    cid_str,
                )
                continue

            partner = c.get("_partner")
            if c.get("_partner_ambiguous"):
                summary.partner_skipped_ambiguous += 1

            try:
                managed = build_managed_companion(c, partner, summary=summary)
                if not managed:
                    summary.unchanged += 1
                    continue
                result = cip_conn.execute(
                    _UPDATE_COMPANION_SQL,
                    {"cip_client_id": cid_str, "managed": json.dumps(managed)},
                )
                rc = result.rowcount or 0
                if rc == 1:
                    summary.updated += 1
                elif rc == 0:
                    summary.unchanged += 1
                else:
                    # Contract broken — PK lookup matched multiple rows.
                    raise RuntimeError(
                        f"unexpected UPDATE rowcount={rc} for "
                        f"cip_clients.id={cid_str}; PK lookup must "
                        "match exactly 0 or 1 row"
                    )
            except Exception as exc:  # noqa: BLE001
                summary.errors += 1
                log.exception(
                    "row error during writeback (cip_client_id=%s): %s",
                    cid_str, exc,
                )

    log.info(
        "crm_companion_writeback summary: %s",
        summary.to_dict(),
    )
    return summary
