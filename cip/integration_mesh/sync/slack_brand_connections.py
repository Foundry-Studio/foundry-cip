# foundry: kind=connector domain=client-intelligence-platform touches=integration,storage
"""ps_slack_brand_connections — the Wayward new-brand onboarding feed.

WHY THIS EXISTS
---------------
`#amazon-brand-connections` is an automated n8n Slack feed: one structured message
per new brand onboarded, carrying Brand ID (= wayward_brand_id), **Country** (the
primary nationality fact for a brand-new brand), Referral Source, Usage Fee, the
HubSpot company/deal ids, contact + email. This is the FRONT DOOR for a new brand's
nationality — a `Country: CN` here is what flips a fresh brand to china.

It was historically a MANUAL script (`scripts/ingest_slack_brand_connections.py`)
that nobody scheduled, so the feed silently went stale (gap found 2026-07-20 — a
week of new Chinese brands never ingested, showing as 'unknown'). This module lifts
the proven parser into the package and makes it a heartbeated, scheduled CIP sync so
that can never happen quietly again — a stale feed now trips the freshness watchdog.

DESIGN RULE (Tim, 2026-07-09) — facts vs conclusions: this writes ONLY observations
(`ps_brand_observations`), never a nationality decision. "Country: CN" (Slack) and
"US" (HubSpot) are two separate facts; the decision layer (signal_harvest ->
lens_ps_china_verdict) reconciles them. Append-only + idempotent (ON CONFLICT DO
NOTHING on the natural key). Incremental by default (since the newest observation).

The operator CLI `scripts/ingest_slack_brand_connections.py` now imports from here.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from cip.integration_mesh.orchestrator import _advisory_lock_key
from cip.integration_mesh.sync_run_recorder import SyncRunRecorder

logger = logging.getLogger(__name__)

CONNECTOR_ID = "slack-brand-connections-v1"
CONNECTOR_NAME = "PS Slack Brand Connections"
CHANNEL_ID = "C092AMXQD9V"  # #amazon-brand-connections
SOURCE_SYSTEM = "slack:amazon-brand-connections"

_SLACK = "https://slack.com/api/"
_BATCH = 1000
# Token env vars, in preference order (user token proven to see the channel; bot
# token works only if the bot is in the channel with history scope).
_TOKEN_ENVS = ("SLACK_USER_TOKEN", "FOUNDRY_SLACK_USER_TOKEN", "SLACK_BOT_TOKEN")

# label in the message  ->  observation field name
_FIELDS = {
    "Brand Name": "brand_name",
    "Website": "website",
    "Contact Name": "contact_name",
    "Email": "email",
    "Connection Event Timestamp": "connection_event_at",
    "Number of Products Synced": "products_synced",
    "Referral Source": "referral_source",
    "Brand ID": "wayward_brand_id",
    "Country": "country",
    "Logged Deal Source": "deal_source",
    "Logged Deal Usage Fee": "usage_fee",
    "Logged Deal SaaS Fee": "saas_fee",
}


def _api(method: str, token: str, **params: Any) -> dict[str, Any]:
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{_SLACK}{method}?{q}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data: dict[str, Any] = json.load(r)
        return data


def _unwrap(v: str) -> str:
    """Slack link syntax: <url|text> / <mailto:a@b|a@b> -> the meaningful part."""
    v = v.strip()
    m = re.fullmatch(r"<mailto:([^|>]+)(?:\|[^>]*)?>", v)
    if m:
        return m.group(1)
    m = re.fullmatch(r"<([^|>]+)(?:\|([^>]*))?>", v)
    if m:
        return m.group(2) or m.group(1)
    return v


def _strip_emoji(v: str) -> str:
    return re.sub(r":[a-z0-9_+\-]+:", "", v).strip()


def _strip_footer(v: str) -> str:
    return re.split(r"\s*_Automated with this", v, maxsplit=1)[0].strip()


def parse_message(text_body: str) -> dict[str, str]:
    """Extract the structured fields. Returns {} for non-brand-connection posts."""
    if "New Amazon Brand Connection" not in text_body:
        return {}
    out: dict[str, str] = {}
    for label, field in _FIELDS.items():
        m = re.search(
            rf"\*{re.escape(label)}\*:\s*(.*?)(?=\s*\*[A-Z][^*]*\*:|$)",
            text_body,
            re.DOTALL,
        )
        if not m:
            continue
        val = _strip_footer(_strip_emoji(_unwrap(m.group(1).split("\n")[0])))
        if val:
            out[field] = val
    m = re.search(r"/record/0-2/(\d+)", text_body)
    if m:
        out["hubspot_company_id"] = m.group(1)
    m = re.search(r"/record/0-3/(\d+)", text_body)
    if m:
        out["hubspot_deal_id"] = m.group(1)
    return out


def _permalink(team_url: str, ts: str) -> str:
    return f"{team_url.rstrip('/')}/archives/{CHANNEL_ID}/p{ts.replace('.', '')}"


_INSERT = text(
    """
    INSERT INTO ps_brand_observations (
        tenant_id, subject_type, wayward_brand_id, client_id,
        field, value, value_normalized, source_system, source_ref, observed_at
    ) VALUES (
        :t, 'brand', :wbid, :cid, :field, :value, :norm, :src, :ref, :obs_at
    )
    ON CONFLICT (tenant_id, subject_type, wayward_brand_id, field,
                 source_system, source_ref) DO NOTHING
    """
)


def resolve_token(token: str | None = None) -> str:
    """The first present env token whose Slack auth.test succeeds."""
    if token:
        return token
    present = [e for e in _TOKEN_ENVS if os.environ.get(e)]
    for env in present:
        try:
            if _api("auth.test", os.environ[env]).get("ok"):
                logger.info("slack-brand-connections: using token from %s", env)
                return os.environ[env]
        except Exception as exc:  # noqa: BLE001
            logger.warning("slack-brand-connections: %s auth failed: %s", env, exc)
    raise RuntimeError(
        f"No working Slack token (tried {present or _TOKEN_ENVS}). Set SLACK_USER_TOKEN "
        "(xoxp, must see #amazon-brand-connections) or a bot token in the channel."
    )


def ingest(engine: Engine, token: str, tenant: str, *, full: bool = False) -> dict[str, Any]:
    """Core parse-and-upsert loop. Reused by the sync + the operator CLI. Facts only."""
    who = _api("auth.test", token)
    if not who.get("ok"):
        raise RuntimeError(f"Slack auth failed: {who.get('error')}")
    team_url = who["url"]

    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": tenant})
        wbid_map = {
            str(w): str(cid)
            for cid, w in conn.execute(
                text("SELECT id, wayward_brand_id FROM cip_clients "
                     "WHERE wayward_brand_id IS NOT NULL")
            ).fetchall()
        }
        oldest = None
        if not full:
            oldest = conn.execute(
                text(
                    "SELECT max(observed_at) FROM ps_brand_observations "
                    "WHERE tenant_id=:t AND source_system=:s"
                ),
                {"t": tenant, "s": SOURCE_SYSTEM},
            ).scalar()

        cursor, msgs, parsed, obs, matched = "", 0, 0, 0, 0
        pending: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"channel": CHANNEL_ID, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            if oldest:
                params["oldest"] = f"{oldest.timestamp():.6f}"
            page = _api("conversations.history", token, **params)
            if not page.get("ok"):
                raise RuntimeError(f"history failed: {page.get('error')}")
            for m in page.get("messages", []):
                msgs += 1
                fields = parse_message(m.get("text") or "")
                if not fields:
                    continue
                wbid = fields.pop("wayward_brand_id", None)
                if not wbid:
                    continue
                parsed += 1
                cid = wbid_map.get(wbid)
                if cid:
                    matched += 1
                ref = _permalink(team_url, m["ts"])
                observed = datetime.fromtimestamp(float(m["ts"]), UTC)
                fields["wayward_brand_id"] = wbid
                for field, value in fields.items():
                    pending.append({
                        "t": tenant, "wbid": wbid, "cid": cid, "field": field,
                        "value": value, "norm": value.strip().lower(),
                        "src": SOURCE_SYSTEM, "ref": ref, "obs_at": observed,
                    })
                if len(pending) >= _BATCH:
                    conn.execute(_INSERT, pending)
                    obs += len(pending)
                    pending.clear()
            cursor = (page.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                break
        if pending:
            conn.execute(_INSERT, pending)
            obs += len(pending)

    return {
        "messages_scanned": msgs, "brand_events_parsed": parsed,
        "observations_sent": obs, "brands_matched_to_cip_clients": matched,
        "mode": "full" if full else "incremental",
    }


def run_slack_brand_connections_sync(
    engine: Engine,
    *,
    tenant_id: UUID | str,
    token: str | None = None,
    full: bool = False,
    now: datetime | None = None,  # noqa: ARG001 — parity with the sibling syncs
) -> dict[str, Any]:
    """Scheduled sync entry: advisory-locked + heartbeated, wrapping ``ingest``."""
    tenant_uuid = UUID(str(tenant_id))
    tenant_str = str(tenant_uuid)
    tok = resolve_token(token)

    lock_key = _advisory_lock_key(tenant_uuid, CONNECTOR_ID)
    lock_conn = engine.connect()
    try:
        got = lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
        lock_conn.commit()
        if not got:
            with SyncRunRecorder(
                engine, tenant_id=tenant_uuid, client_id=None,
                connector_id=CONNECTOR_ID, connector_name=CONNECTOR_NAME, sync_mode="incremental",
            ) as run:
                run.counters.error_detail = {"skipped": "lock-held"}
            return {"status": "skipped", "reason": "lock-held", "tenant_id": tenant_str}
        with SyncRunRecorder(
            engine, tenant_id=tenant_uuid, client_id=None,
            connector_id=CONNECTOR_ID, connector_name=CONNECTOR_NAME,
            sync_mode="full" if full else "incremental",
        ) as run:
            counts = ingest(engine, tok, tenant_str, full=full)
            run.counters.rows_received = counts["observations_sent"]
            run.counters.rows_created = counts["observations_sent"]
        return {"status": run.final_status, "sync_run_id": str(run.run_id),
                "tenant_id": tenant_str, **counts}
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            lock_conn.commit()
        except Exception as unlock_err:  # noqa: BLE001
            logger.warning("slack-brand-connections unlock failed (conn GC): %s", unlock_err)
        lock_conn.close()
