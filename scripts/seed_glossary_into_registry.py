# foundry: kind=script domain=client-intelligence-platform
"""Seed verified glossary entries from the markdown glossary into
`cip_connector_property_registry`.

Per PM scopes `0246851d` (Tenant Property Glossary) + `bfc3d5d0`
(Tenant Manifest): the markdown glossary at
`docs/tenants/<uuid>/GLOSSARY.md` is the editable source-of-truth;
the registry is the queryable materialization that lens views +
agents consume. This script does the markdown → DB sync.

v1: hardcoded list of EcomLever/Wayward verified entries (the ones
Tim confirmed during the 2026-05-16 review). v2 (separate scope)
will parse the markdown directly.

Idempotent — re-running upserts the same rows.

Usage:

    DATABASE_URL=$DATABASE_PUBLIC_URL \\
        SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD \\
        python -u scripts/seed_glossary_into_registry.py
"""
from __future__ import annotations

import os
import re
import sys
from sqlalchemy import create_engine, text

ECOMLEVER_TENANT_ID = "dec814db-722a-4730-8e60-51afc4a5dad9"
WAYWARD_CLIENT_ID = "661ecab4-dddb-5924-a34d-af1c5133132d"

# Verified entries from docs/tenants/dec814db-.../GLOSSARY.md as of 2026-05-16.
# Format: (connector, object_type, cip_table, property_name, property_type,
#          storage_location, column_name, label, plain_english_meaning,
#          confidence, aliases, watch_out_for, is_custom)
VERIFIED_ENTRIES: list[tuple[str, str, str, str, str, str, str | None, str, str, str, list[str], str | None, bool]] = [
    # cip_deals — the affiliate-owner attribution field (the canonical example)
    (
        "hubspot-v1", "deal", "cip_deals", "source",
        "enumeration", "overflow", None,
        "Source",
        "The canonical affiliate-owner attribution field for Wayward. Records who brought the brand to Wayward. Format typically 'China Referral - {person}' for Chinese-brand referrals. Mapping: 'China Referral - Tim' → Tim Jordan; 'China Referral - Eric' → LYTASAUR (Eric is LYTASAUR); 'China Referral - OpenLight' → OpenLight; 'China Referral - Adina' → Adina; 'China Referral - Jeremy Dai' → Jeremy Dai; 'China Referral - Shallow' → Shallow. Non-affiliate sources include 'Organic', 'Paid Marketing', 'Event / Trade Show', 'Hyphen Social Migration', 'Agency Referral', 'Cold Email Outbound', 'Cold LinkedIn Outbound', 'MDS', 'Other'.",
        "verified",
        ["affiliate_owner", "referral_partner", "attribution_source"],
        "Wayward's segment='Chinese Brand' tag is a DIFFERENT field and is severely under-applied (only 37 of 564 producing Chinese-indicator deals tagged). Use `source` for attribution, NOT `segment`.",
        True,
    ),
    # cip_deals — money fields
    (
        "hubspot-v1", "deal", "cip_deals", "lifetime_gmv",
        "number", "overflow", None,
        "Lifetime GMV",
        "Total Gross Merchandise Value (USD) driven by Wayward's program for this deal/brand over the deal's lifetime. The headline 'how much sales did this brand do' metric.",
        "verified",
        ["gmv", "lifetime_sales"], None, True,
    ),
    (
        "hubspot-v1", "deal", "cip_deals", "lifetime_commissions_generated",
        "number", "overflow", None,
        "Lifetime Commissions Generated",
        "Gross commission paid by the brand to Wayward over the deal's lifetime. Typically ~10% of lifetime_gmv. This is NOT the referral partner's cut — it's Wayward's gross commission revenue from the brand.",
        "verified",
        ["wayward_commission_gross"], None, True,
    ),
    (
        "hubspot-v1", "deal", "cip_deals", "lifetime_usage_fees_generated",
        "number", "overflow", None,
        "Lifetime Usage Fees Generated",
        "Wayward's platform fee earned on the deal. Often ~1% of GMV but Tim confirmed 2026-05-16: 'Roborock is at 1% but most brands are charged 3-5%.' This is what Wayward keeps as their cut.",
        "verified",
        ["platform_fee", "wayward_take"], None, True,
    ),
    (
        "hubspot-v1", "deal", "cip_deals", "total_fees_paid",
        "number", "overflow", None,
        "Total Fees Paid",
        "Cumulative fees paid OUT (probably to referral partners and creators). Tim 2026-05-16: 'I get 10% of total_fees_paid per month for Chinese brands attributed to me via the source field that are NOT covered by other China referral affiliates.' THIS is the canonical field for Tim's commission accounting.",
        "verified",
        ["payout", "fees_disbursed", "tim_commission_base"], None, True,
    ),
    # cip_deals — segment (Chinese Brand specifically)
    (
        "hubspot-v1", "deal", "cip_deals", "segment",
        "enumeration", "overflow", None,
        "Segment",
        "Deal-level segmentation tag. The 'Chinese Brand' value tags deals associated with Chinese-region brands. Other enum values seen (`Other`, `LV`, `HyphenSocial - High Pri 1-5`, `Search Arb`) have unknown meanings as of 2026-05-16.",
        "verified",
        ["chinese_brand_tag"],
        "SEVERELY UNDER-APPLIED. Only 37 deals tagged Chinese Brand vs 564 producing Chinese-indicator deals. Do NOT use as canonical 'is Chinese?' signal — use country IN ('CN','China','HK','Hong Kong','TW','Taiwan') on the associated company + source 'China Referral - *' prefix instead.",
        True,
    ),
    # cip_deals — deal_owner (custom enum, internal only)
    (
        "hubspot-v1", "deal", "cip_deals", "deal_owner",
        "enumeration", "overflow", None,
        "Deal Owner",
        "Wayward INTERNAL staff name assigned to the deal. Only values seen: 'Mackenzie Clemens' (340 deals), 'Jake Coburn' (95 deals). NOT for affiliate attribution — that's the `source` field.",
        "verified",
        ["internal_owner", "wayward_staff_owner"], None, True,
    ),
    # cip_deals — amazon_seller_type
    (
        "hubspot-v1", "deal", "cip_deals", "amazon_seller_type",
        "enumeration", "overflow", None,
        "Amazon Seller Type",
        "How the brand sells on Amazon. Enum: '1P' (first-party — Amazon resells the brand's product), '3P' (third-party — brand sells directly via Amazon marketplace), 'Hybrid' (both).",
        "verified",
        ["amazon_1p_3p"], None, True,
    ),
    # cip_companies — Hyphen platform fields
    (
        "hubspot-v1", "company", "cip_companies", "hyphen_gmv_rank",
        "number", "overflow", None,
        "Hyphen GMV Rank",
        "Internal rank of this brand within Hyphen Social's portfolio by GMV. Hyphen Social is a company Wayward purchased; treated as an internal Wayward product/platform.",
        "verified",
        ["internal_gmv_rank", "wayward_gmv_rank"],
        "Computed by the Hyphen platform internally; refresh cadence not externally documented.",
        True,
    ),
    (
        "hubspot-v1", "company", "cip_companies", "hyphen_overlapping_gmv",
        "number", "overflow", None,
        "Hyphen Overlapping GMV",
        "GMV overlap between Hyphen Social affiliate program and other channels for this brand. Hyphen Social = Wayward-purchased internal product.",
        "verified", [],
        "Computed internally by Hyphen platform.",
        True,
    ),
    (
        "hubspot-v1", "company", "cip_companies", "hyphen_units_sold_rank",
        "number", "overflow", None,
        "Hyphen Units Sold Rank",
        "Internal rank of brand by units sold within Hyphen Social portfolio.",
        "verified", [], None, True,
    ),
    # cip_companies — country (verified with caveats)
    (
        "hubspot-v1", "company", "cip_companies", "country",
        "string", "column", "country",
        "Country/Region",
        "Country of the brand. Wayward records this inconsistently — same country can appear as ISO code (`CN`) OR full name (`China`). Chinese-region variants: `Hong Kong`, `Taiwan`, `HK`, `TW`. NULL on ~41% of companies.",
        "verified",
        ["company_country"],
        "Wayward's country tagging is unreliable. 553 producing deals are on companies country-tagged US/Germany/etc. whose contacts have clearly Chinese signals (qq.com, .cn TLD, +86 phones, CJK names). DO NOT use country alone as the canonical 'is Chinese?' signal — combine with contact-side signals.",
        False,
    ),
    # cip_contacts — email (canonical for Chinese detection)
    (
        "zendesk-v1", "contact", "cip_contacts", "email",
        "string", "column", "email",
        "Email",
        "Contact email. For Wayward this includes brand-side reps managing affiliate relationships, Wayward staff, and Zendesk end-users. CRITICAL for Chinese-contact detection: @qq.com (237 contacts), .cn TLD (19), @163.com/@126.com/@sina.com/@sohu.com/@foxmail.com (455 combined) are all strong Chinese signals.",
        "verified",
        ["contact_email", "primary_email"], None, False,
    ),
    # Zendesk via.channel
    (
        "zendesk-v1", "ticket", "cip_tickets", "via_channel",
        "enumeration", "overflow", None,
        "Via Channel",
        "Channel through which the ticket entered Zendesk. Wayward's data shows two values: 'email' (2,012 tickets, 70%) and 'web' (878 tickets, 30%). 100% coverage. No other channels seen (no chat, phone, mobile, etc.).",
        "verified",
        ["ticket_channel", "ingress_channel"], None, False,
    ),
]


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    confirmation = os.environ.get("SEED_CONFIRM", "")
    if re.search(r"\.rlwy\.net|\.railway\.app", url) and confirmation != "YES_I_KNOW_THIS_IS_PROD":
        print(
            "ABORTED: target is prod. Re-run with SEED_CONFIRM=YES_I_KNOW_THIS_IS_PROD",
            file=sys.stderr,
        )
        return 3

    sa_url = (
        url.replace("postgresql://", "postgresql+psycopg://")
           .replace("postgres://", "postgresql+psycopg://")
    )
    engine = create_engine(sa_url, pool_pre_ping=True)

    print(f"Seeding {len(VERIFIED_ENTRIES)} verified glossary entries into the registry...")
    inserted = 0
    updated = 0

    upsert_sql = """
    INSERT INTO cip_connector_property_registry (
        tenant_id, client_id,
        connector, object_type, cip_table,
        property_name, property_type,
        storage_location, column_name,
        label, description,
        plain_english_meaning, confidence,
        aliases, watch_out_for,
        is_custom,
        last_reviewed_at, last_reviewed_by,
        first_seen_at, last_synced_schema_at
    ) VALUES (
        :tid, :cid,
        :connector, :object_type, :cip_table,
        :property_name, :property_type,
        :storage_location, :column_name,
        :label, :label,
        :plain_english_meaning, :confidence,
        :aliases, :watch_out_for,
        :is_custom,
        now(), 'tim+claude (2026-05-16 glossary review)',
        now(), now()
    )
    ON CONFLICT (tenant_id, connector, object_type, property_name) DO UPDATE
    SET label = EXCLUDED.label,
        plain_english_meaning = EXCLUDED.plain_english_meaning,
        confidence = EXCLUDED.confidence,
        aliases = EXCLUDED.aliases,
        watch_out_for = EXCLUDED.watch_out_for,
        last_reviewed_at = EXCLUDED.last_reviewed_at,
        last_reviewed_by = EXCLUDED.last_reviewed_by,
        client_id = EXCLUDED.client_id
    """

    # Check unique constraint exists, else fall back to manual upsert
    with engine.connect() as c:
        has_unique = c.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conname IN ('uq_cip_registry_natural','uq_cip_connector_property_registry_natural') "
                "OR (conrelid='cip_connector_property_registry'::regclass "
                "    AND contype='u'))"
            )
        ).scalar()
    if not has_unique:
        print(
            "  Note: no UNIQUE constraint on (tenant_id, connector, object_type, property_name). "
            "Falling back to manual upsert (SELECT-then-UPDATE/INSERT)."
        )

    with engine.begin() as conn:
        conn.execute(
            text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)")
        )
        for (
            connector, object_type, cip_table, property_name, property_type,
            storage_location, column_name, label, plain_english_meaning,
            confidence, aliases, watch_out_for, is_custom,
        ) in VERIFIED_ENTRIES:
            # Manual upsert pattern (covers the no-unique-constraint case).
            existing = conn.execute(
                text(
                    "SELECT registry_id FROM cip_connector_property_registry "
                    "WHERE tenant_id = :tid AND connector = :connector "
                    "  AND object_type = :object_type AND property_name = :property_name"
                ),
                {
                    "tid": ECOMLEVER_TENANT_ID,
                    "connector": connector,
                    "object_type": object_type,
                    "property_name": property_name,
                },
            ).first()
            params = {
                "tid": ECOMLEVER_TENANT_ID,
                "cid": WAYWARD_CLIENT_ID,
                "connector": connector,
                "object_type": object_type,
                "cip_table": cip_table,
                "property_name": property_name,
                "property_type": property_type,
                "storage_location": storage_location,
                "column_name": column_name,
                "label": label,
                "plain_english_meaning": plain_english_meaning,
                "confidence": confidence,
                "aliases": aliases,
                "watch_out_for": watch_out_for,
                "is_custom": is_custom,
            }
            if existing:
                conn.execute(
                    text(
                        "UPDATE cip_connector_property_registry SET "
                        "  client_id = :cid, label = :label, "
                        "  description = COALESCE(description, :label), "
                        "  plain_english_meaning = :plain_english_meaning, "
                        "  confidence = :confidence, aliases = :aliases, "
                        "  watch_out_for = :watch_out_for, "
                        "  last_reviewed_at = now(), "
                        "  last_reviewed_by = 'tim+claude (2026-05-16 glossary review)' "
                        "WHERE registry_id = :rid"
                    ),
                    {**params, "rid": existing[0]},
                )
                updated += 1
                print(f"  UPDATE {connector:12s} {object_type:8s} {property_name}")
            else:
                conn.execute(
                    text(
                        "INSERT INTO cip_connector_property_registry ("
                        "  tenant_id, client_id, connector, object_type, cip_table, "
                        "  property_name, property_type, storage_location, column_name, "
                        "  label, description, plain_english_meaning, confidence, "
                        "  aliases, watch_out_for, is_custom, "
                        "  last_reviewed_at, last_reviewed_by, "
                        "  first_seen_at, last_synced_schema_at"
                        ") VALUES ("
                        "  :tid, :cid, :connector, :object_type, :cip_table, "
                        "  :property_name, :property_type, :storage_location, :column_name, "
                        "  :label, :label, :plain_english_meaning, :confidence, "
                        "  :aliases, :watch_out_for, :is_custom, "
                        "  now(), 'tim+claude (2026-05-16 glossary review)', "
                        "  now(), now()"
                        ")"
                    ),
                    params,
                )
                inserted += 1
                print(f"  INSERT {connector:12s} {object_type:8s} {property_name}")

    print(f"\nDone. Inserted={inserted}, Updated={updated}.")

    # Re-query confidence distribution as a sanity check
    with engine.connect() as conn:
        conn.execute(text(f"SELECT set_config('app.current_tenant','{ECOMLEVER_TENANT_ID}',true)"))
        print("\nNew confidence distribution for EcomLever:")
        for r in conn.execute(
            text(
                "SELECT confidence, COUNT(*) FROM cip_connector_property_registry "
                "WHERE tenant_id = :t GROUP BY 1 ORDER BY 2 DESC"
            ),
            {"t": ECOMLEVER_TENANT_ID},
        ):
            print(f"  {r[0]}: {r[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
