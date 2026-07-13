# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Ingest the Wayward brand-onboarding feed (#amazon-brand-connections) into
ps_brand_observations (cip_41).

The channel is an automated n8n feed: one structured message per new brand
onboarded, carrying Brand ID (= wayward_brand_id), Country, Referral Source,
Logged Deal Source, Usage Fee, HubSpot company/deal ids, contact + email.

DESIGN RULE (Tim, 2026-07-09) — facts vs conclusions:
    This script writes ONLY observations. It NEVER writes nationality_class or any
    other decision column. Slack saying "Country: CN" and HubSpot saying "US" are
    two separate facts; both are recorded with their source, neither supersedes the
    other. The determination is made later, by the decision layer, in
    cip_clients.nationality_class — and nowhere else.

Every observation carries provenance: source_system='slack:amazon-brand-connections'
and source_ref=<clickable Slack permalink>. Append-only + idempotent: re-running
inserts nothing new and rewrites nothing (ON CONFLICT DO NOTHING against the
natural key).

Usage:
  FOUNDRY_SLACK_USER_TOKEN=xoxp-... DATABASE_URL=postgresql+psycopg://... \
      python scripts/ingest_slack_brand_connections.py [--full] [--dry-run]

  --full     page the entire channel history (default: since the newest observation
             already ingested, i.e. incremental)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
CHANNEL_ID = "C092AMXQD9V"          # #amazon-brand-connections
SOURCE_SYSTEM = "slack:amazon-brand-connections"

_SLACK = "https://slack.com/api/"
_BATCH = 1000   # rows per executemany

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


def _api(method: str, token: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{_SLACK}{method}?{q}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


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
    """The n8n workflow credit is appended to the message's LAST field."""
    return re.split(r"\s*_Automated with this", v, maxsplit=1)[0].strip()


def parse_message(text_body: str) -> dict[str, str]:
    """Extract the structured fields. Returns {} for non-brand-connection posts."""
    if "New Amazon Brand Connection" not in text_body:
        return {}
    out: dict[str, str] = {}
    for label, field in _FIELDS.items():
        # *Label*: value   (value runs to end-of-line or the next *Label*:)
        # (.*?) not (.+?): a field can legitimately be EMPTY (e.g. no usage fee is
        # logged on non-China-referral deals). With (.+?) the capture swallowed the
        # NEXT label instead of yielding nothing.
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
    # HubSpot ids live inside the link URLs: /record/0-2/<companyId>, 0-3/<dealId>
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
        field, value, value_normalized,
        source_system, source_ref, observed_at
    ) VALUES (
        :t, 'brand', :wbid, :cid,
        :field, :value, :norm,
        :src, :ref, :obs_at
    )
    ON CONFLICT (tenant_id, subject_type, wayward_brand_id, field,
                 source_system, source_ref) DO NOTHING
    """
)


def run(engine, token: str, *, full: bool, dry_run: bool) -> dict:
    who = _api("auth.test", token)
    if not who.get("ok"):
        raise SystemExit(f"Slack auth failed: {who.get('error')}")
    team_url = who["url"]

    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
        )
        # wayward_brand_id -> cip_clients.id (populated by the Job-2 backfill).
        wbid_map = {
            str(w): str(c)
            for c, w in conn.execute(
                text(
                    "SELECT id, wayward_brand_id FROM cip_clients "
                    "WHERE wayward_brand_id IS NOT NULL"
                )
            ).fetchall()
        }
        oldest = None
        if not full:
            oldest = conn.execute(
                text(
                    "SELECT max(observed_at) FROM ps_brand_observations "
                    "WHERE tenant_id=:t AND source_system=:s"
                ),
                {"t": PS_TENANT, "s": SOURCE_SYSTEM},
            ).scalar()

        cursor = ""
        msgs = 0
        parsed = 0
        obs = 0
        matched = 0
        pending: list[dict] = []
        while True:
            params = {"channel": CHANNEL_ID, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            if oldest:
                params["oldest"] = f"{oldest.timestamp():.6f}"
            page = _api("conversations.history", token, **params)
            if not page.get("ok"):
                raise SystemExit(f"history failed: {page.get('error')}")
            for m in page.get("messages", []):
                msgs += 1
                fields = parse_message(m.get("text") or "")
                if not fields:
                    continue
                wbid = fields.pop("wayward_brand_id", None)
                if not wbid:
                    continue  # no subject key -> can't anchor the facts
                parsed += 1
                cid = wbid_map.get(wbid)
                if cid:
                    matched += 1
                ref = _permalink(team_url, m["ts"])
                observed = datetime.fromtimestamp(float(m["ts"]), UTC)
                # the Brand ID itself is also a fact worth recording
                fields["wayward_brand_id"] = wbid
                for field, value in fields.items():
                    pending.append({
                        "t": PS_TENANT, "wbid": wbid, "cid": cid,
                        "field": field, "value": value,
                        "norm": value.strip().lower(),
                        "src": SOURCE_SYSTEM, "ref": ref, "obs_at": observed,
                    })
                # Batch: one executemany per BATCH rows, not one round-trip per
                # row. (Row-at-a-time over a remote DB made the 18k-row backfill
                # take 40+ minutes in a single open transaction.)
                if not dry_run and len(pending) >= _BATCH:
                    conn.execute(_INSERT, pending)
                    obs += len(pending)
                    pending.clear()
            cursor = (page.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                break
        if pending and not dry_run:
            conn.execute(_INSERT, pending)
            obs += len(pending)
            pending.clear()
        elif dry_run:
            obs += len(pending)
            conn.execute(text("ROLLBACK"))
        # obs counts rows SENT; report what actually landed.
        written = conn.execute(
            text(
                "SELECT count(*) FROM ps_brand_observations "
                "WHERE tenant_id=:t AND source_system=:s"
            ),
            {"t": PS_TENANT, "s": SOURCE_SYSTEM},
        ).scalar() if not dry_run else 0

    return {
        "messages_scanned": msgs,
        "brand_events_parsed": parsed,
        "observations_sent": obs,
        "observations_in_db": written,
        "brands_matched_to_cip_clients": matched,
        "mode": "full" if full else "incremental",
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--token", default=None)
    args = ap.parse_args(argv)

    token = args.token or os.environ.get("FOUNDRY_SLACK_USER_TOKEN")
    if not token:
        print("FOUNDRY_SLACK_USER_TOKEN not set", file=sys.stderr)
        return 2
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        summary = run(engine, token, full=args.full, dry_run=args.dry_run)
    finally:
        engine.dispose()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
