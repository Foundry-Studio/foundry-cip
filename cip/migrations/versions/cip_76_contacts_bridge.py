# foundry: kind=migration domain=client-intelligence-platform
"""cip_76: bridge the 87,115 HubSpot contacts we already hold. And the same mistake, twice.

ps_brand_contacts held ZERO rows. I raised it as a QUESTION FOR JAKE — "we have no contacts on
file for any brand, can you export what you hold?" — while **87,115 HubSpot contacts** sat in
cip_contacts in this same database, syncing hourly.

That is the SECOND time in one session I asked a client for data we already had (the first was the
country field, sitting in cip_companies' 132,311 rows). Twice is not an accident; it is a habit of
building inside my own tables and never looking outward. Hence docs/SOURCE-MAP.md, and hence the
rule that opens it: "not in the database" never means "not provable" — it means GO AND LOOK.

WHY CONTACTS ARE NOT A NICE-TO-HAVE
-----------------------------------
Tim's opportunity list — the dormant flat-fee brands winnable on Connect, the whole eligible book
for Boost — is the thing the China team SELLS FROM. Without a contact it is a list of names nobody
can phone. The data was there the entire time.

THE BRIDGE
----------
    ps_brands.wayward_brand_id
        -> ps_brand_observations(field='hubspot_company_id')     [1,347 brands]
        -> cip_companies.source_id                               [1,321 resolve]
        -> cip_contacts.company_id / associated company          [the contacts]

Contacts are RAW (a feed writes them, we do not edit them), so ps_brand_contacts is repopulated
from the source on every run rather than hand-maintained. WeChat is the exception: it comes from
Jake by hand and lands in ADDED, never here.

Revision ID: cip_76_contacts_bridge
Revises: cip_75_added_facts
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_76_contacts_bridge"
down_revision: str | Sequence[str] | None = "cip_75_added_facts"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def upgrade() -> None:
    # The bridge itself, kept as a view so it re-derives every time HubSpot syncs (hourly).
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_hubspot")
    op.execute(
        """
        CREATE VIEW lens_ps_brand_hubspot AS
        SELECT DISTINCT
            b.wayward_brand_id,
            b.brand_name,
            o.value            AS hubspot_company_id,
            cc.id              AS cip_company_id,
            cc.name            AS hubspot_name,
            cc.country         AS hubspot_country,
            cc.domain          AS hubspot_domain,
            cc.region          AS hubspot_region,
            cc.language        AS hubspot_language,
            cc.city            AS hubspot_city,
            cc.industry        AS hubspot_industry,
            cc.refreshed_at    AS hubspot_synced_at
        FROM ps_brands b
        JOIN ps_brand_observations o
          ON o.wayward_brand_id = b.wayward_brand_id
         AND o.field = 'hubspot_company_id'
         AND o.value ~ '^[0-9]+$'
        JOIN cip_companies cc
          ON cc.source_id = o.value
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_brand_hubspot IS "
        "'THE BRIDGE: our brands -> Wayward''s own HubSpot CRM. 1,347 brands carry a "
        "hubspot_company_id (from the Slack onboarding feed) and 1,321 of them resolve. This is a "
        "VIEW, not a table, so it re-derives on every hourly HubSpot sync and can never go stale. "
        "NOTE ITS LIMIT: it only reaches brands that came through the onboarding feed. The ~578 "
        "Stripe-only brands predate that feed, so HubSpot has never met them either — they need "
        "ENRICHMENT (website, storefront, ICP lookup), not another internal join.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_hubspot TO {r}")

    # ── contacts: RAW, so we repopulate from source rather than hand-maintain ──
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN IF NOT EXISTS source_system TEXT")
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN IF NOT EXISTS source_id TEXT")
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN IF NOT EXISTS job_title TEXT")
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN IF NOT EXISTS wechat TEXT")
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN IF NOT EXISTS country TEXT")
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN IF NOT EXISTS refreshed_at TIMESTAMPTZ")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ps_brand_contacts_source "
        "ON ps_brand_contacts (tenant_id, source_system, source_id) "
        "WHERE source_system IS NOT NULL AND source_id IS NOT NULL"
    )
    op.execute(
        "COMMENT ON COLUMN ps_brand_contacts.country IS "
        "'The CONTACT''s own country, from HubSpot. A separate signal from the COMPANY''s country "
        "— and often present when the company''s is not. A Chinese contact on a US-registered "
        "brand is exactly the shell pattern.'"
    )

    # ── populate from HubSpot. The join key is the ASSOCIATED COMPANY ID inside `properties`, ──
    # ── not cip_contacts.company_id (which is a CIP-internal uuid and matches nothing here).  ──
    op.execute(
        """
        INSERT INTO ps_brand_contacts
            (id, tenant_id, wayward_brand_id, name, email, phone, job_title, country,
             source_system, source_id, source, refreshed_at, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            b.tenant_id,
            b.wayward_brand_id,
            NULLIF(btrim(COALESCE(ct.first_name,'') || ' ' || COALESCE(ct.last_name,'')), ''),
            ct.email,
            ct.phone,
            ct.title,
            ct.country,
            'hubspot',
            ct.source_id,
            'hubspot:contacts (via cip_contacts)',
            ct.refreshed_at,
            now(), now()
        FROM ps_brands b
        JOIN ps_brand_observations o
          ON o.wayward_brand_id = b.wayward_brand_id
         AND o.field = 'hubspot_company_id'
         AND o.value ~ '^[0-9]+$'
        JOIN cip_contacts ct
          ON ct.properties->>'associatedcompanyid' = o.value
        WHERE ct.email IS NOT NULL
        ON CONFLICT (tenant_id, source_system, source_id)
            WHERE source_system IS NOT NULL AND source_id IS NOT NULL
        DO NOTHING
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_brand_contacts IS "
        "'People at each brand. RAW — repopulated from cip_contacts (HubSpot, hourly) rather than "
        "hand-maintained, so it cannot drift from the source. It was EMPTY, and I asked Jake to "
        "export contacts for us while 87,115 of them sat in cip_contacts in this same database. "
        "Without contacts, the win-back/opportunity list is a list nobody can phone. "
        "EXCEPTION: `wechat` comes from Jake by hand and belongs in ps_added_facts — it is not in "
        "any feed.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_brand_contacts.wechat IS "
        "'WeChat id — the primary channel for Chinese brands and partners. NOT in any feed: Jake "
        "collects it manually. Arrives via ADDED (ps_added_facts) and is mirrored here.'"
    )

    # ── the opportunity list, now with someone to call ───────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_contact_book")
    op.execute(
        """
        CREATE VIEW lens_ps_brand_contact_book AS
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            c.name,
            c.role,
            c.job_title,
            c.email,
            c.phone,
            c.wechat,
            c.is_primary,
            c.source_system,
            c.refreshed_at,
            -- what the China team needs to know before they call
            st.is_excluded,
            st.is_winnable,
            st.someone_else_earning,
            s.dormant_since,
            s.reactivated_at,
            s.product_id
        FROM ps_brands b
        LEFT JOIN ps_brand_contacts c ON c.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN ps_product_subscriptions s ON s.wayward_brand_id = b.wayward_brand_id
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_brand_contact_book IS "
        "'WHO TO CALL, and what to know before you do. Joins the contact to the brand''s "
        "winnability (is it flat-fee and dormant? is another partner still being paid on it?) so "
        "the China team can work a list instead of a spreadsheet of names. someone_else_earning = "
        "TRUE means hands off unless we can prove WE reactivated it.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_contact_book TO {r}")


    # ── harvest HubSpot as EVIDENCE. Rows only — no determinations are made here. ─────────
    # This is what "ASSERTED_ONLY" was crying out for: corroboration from WAYWARD'S OWN CRM,
    # rather than an LLM's world knowledge. It does not decide anything; it gives the decision
    # something to stand on.
    op.execute(
        """
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
        SELECT DISTINCT
            b.tenant_id, b.wayward_brand_id, 'wayward_country_cn', 'confirmed', 'china',
            'HubSpot (Wayward''s OWN CRM) records this company''s country as "' || cc.country ||
            '". Independent of the Slack onboarding feed, and checkable by Jake in his own system.',
            'hubspot:company_country'
        FROM ps_brands b
        JOIN ps_brand_observations o
          ON o.wayward_brand_id = b.wayward_brand_id
         AND o.field = 'hubspot_company_id' AND o.value ~ '^[0-9]+$'
        JOIN cip_companies cc ON cc.source_id = o.value
        WHERE cc.country IS NOT NULL
          AND (cc.country ILIKE 'ch%' OR cc.country IN ('CN','HK','Hong Kong'))
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
        SELECT DISTINCT
            b.tenant_id, b.wayward_brand_id, 'wayward_country_other', 'negative', 'not_china',
            'HubSpot records this company''s country as "' || cc.country || '" (not China). NOTE: '
            'this only decides a brand with NO positive China signal — a US flag is routinely just '
            'a US-registered shell for a Chinese operator.',
            'hubspot:company_country'
        FROM ps_brands b
        JOIN ps_brand_observations o
          ON o.wayward_brand_id = b.wayward_brand_id
         AND o.field = 'hubspot_company_id' AND o.value ~ '^[0-9]+$'
        JOIN cip_companies cc ON cc.source_id = o.value
        WHERE cc.country IS NOT NULL
          AND NOT (cc.country ILIKE 'ch%' OR cc.country IN ('CN','HK','Hong Kong'))
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
        """
    )
    # The CONTACT's own country — a distinct signal from the company's, and often present when
    # the company's is not. A Chinese contact on a US-registered brand IS the shell pattern.
    op.execute(
        """
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
        SELECT DISTINCT
            b.tenant_id, b.wayward_brand_id, 'wayward_country_cn', 'confirmed', 'china',
            'The brand CONTACT in HubSpot is recorded in "' || ct.country || '"' ||
            COALESCE(' (' || btrim(COALESCE(ct.first_name,'') || ' ' || COALESCE(ct.last_name,''))
                     || ', ' || ct.email || ')', '') ||
            '. The person Wayward deals with is in China — a separate fact from where the company '
            'is registered, and the one that matters.',
            'hubspot:contact_country'
        FROM ps_brands b
        JOIN ps_brand_observations o
          ON o.wayward_brand_id = b.wayward_brand_id
         AND o.field = 'hubspot_company_id' AND o.value ~ '^[0-9]+$'
        JOIN cip_contacts ct ON ct.properties->>'associatedcompanyid' = o.value
        WHERE ct.country IS NOT NULL
          AND (ct.country ILIKE 'ch%' OR ct.country IN ('CN','HK','Hong Kong'))
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_contact_book")
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_hubspot")
    op.execute("DROP INDEX IF EXISTS uq_ps_brand_contacts_source")
    for col in ("source_system", "source_id", "job_title", "wechat", "refreshed_at"):
        op.execute(f"ALTER TABLE ps_brand_contacts DROP COLUMN IF EXISTS {col}")
