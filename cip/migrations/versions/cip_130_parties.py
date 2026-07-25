# foundry: kind=migration domain=client-intelligence-platform
"""cip_130: parties & deals (BE-1) — a stable identity spine for platform / product /
referral / customer counterparties, layered NON-BREAKING over the existing schema.

Design of record: WORKBENCH/china-audit/REPORTING-BE0-AUDIT.md ("Migration design", Option A).
This is BE-1. The effective-dated rate store (`ps_partner_rate`, FAS-governed) is BE-2 — the
NEXT migration — so `ps_party_deal.rate_pct` here only DOCUMENTS a deal; it is not the money source.

WHAT THIS ADDS (all additive; nothing renamed, nothing dropped):
  1. ps_party           — the stable id (`party_id`) with a MUTABLE `display_name`. Renames no
                          longer break links: identity is the uuid, not the slug of a name.
  2. ps_party_kind      — (party_id, kind) rows so a party can be many kinds (platform/product/
                          referral/customer) and kinds grow by INSERT, not by ALTER.
  3. ps_party_alias     — generalizes ps_partner_aliases: every raw string a source ever wrote
                          (a name, an invoice-payer string, a handle, a UTM code) -> ONE party.
  4. ps_party_deal      — promotes the orphaned ps_partner_terms shape into a documented deal.
  5. ps_customer_party  — customer bridge at COMPANY grain (Q2 decision): one party per company,
                          keyed on the `ps_brands.canonical_brand_id` spine. Member wayward_brand_ids
                          are reached through that spine (see the bridge note below) — no 2nd table.
  6. ps_partner_credit.party_id (uuid FK, NULL) — additive; `partner_of_record` is UNTOUCHED.

COUNTERPARTY (the "Wayward" product+platform party) is seeded as ONE row with kinds {product,
platform}; its display name is a module const, not an inline literal, and — because display_name is
mutable while party_id is stable — a future rename touches only that column.

NON-BREAKING GUARANTEE: `wayward_brand_id` and the two lens_ps_wayward_* views/columns are NOT
renamed (Q3). The one lens touched (lens_ps_product_eligibility) is changed with CREATE OR REPLACE
VIEW and only APPENDS `party_id` + `display_name` at the end — its existing 10 columns and every
row are byte-for-byte unchanged, so the money lenses that read it (lens_ps_claim via cip_107,
cip_113, cip_114, cip_126) and `sum(ps_claim_owed)` are untouched by construction.

Revision ID: cip_130_parties
Revises: cip_129_widen_lens_grants

(Revision id kept short -- alembic_version_cip is VARCHAR(32); this = 15 chars.)
NOTE (apply-time, not in this file): the shared prod DB carries a foreign monorepo revision, so the
operator must export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir" for env.py's
cross-pollution guard to pass. That guard lives in cip/migrations/env.py; migrations never embed it.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "cip_130_parties"
down_revision: str | Sequence[str] | None = "cip_129_widen_lens_grants"
branch_labels = None
depends_on = None


PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

# The read-role set the lens catalog + cip_129 grant to, PLUS the reporting app's reader.
# ps_reporting_reader (cip_120) only auto-enumerates lens_ps_* VIEWS, so these new BASE tables
# must be granted to it EXPLICITLY here.
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_READER = "ps_reporting_reader"
_WRITER = "ps_reporting_writer"

# Generic seed name for the counterparty party. Held as a const (not an inline literal) and,
# because ps_party.display_name is MUTABLE while party_id is STABLE, a future rename updates only
# this column and breaks no links — the whole point of the party model.
_COUNTERPARTY_DISPLAY_NAME = "Wayward"

# Create parents before children; drop in reverse.
_TABLES: tuple[str, ...] = (
    "ps_party",
    "ps_party_kind",
    "ps_party_alias",
    "ps_party_deal",
    "ps_customer_party",
)

# Writer targets — extend the cip_127 ps_reporting_writer _UPSERT set (INSERT+UPDATE+SELECT).
# ps_customer_party is populated by this migration's backfill and is NOT an app write target.
_WRITE_TARGETS: tuple[str, ...] = ("ps_party", "ps_party_kind", "ps_party_alias", "ps_party_deal")

_DDL: dict[str, str] = {
    # 1. The stable identity. Surrogate PK (party_id) first, tenant_id second — matches the ps_*
    #    table convention (cip_39). display_name is mutable; the id is forever.
    "ps_party": """
        CREATE TABLE ps_party (
            party_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL,
            display_name TEXT NOT NULL,
            legal_name   TEXT,
            country      TEXT,
            status       TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','inactive','prospect')),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    # 2. Row-per-kind so a party is multi-kind and kinds grow by INSERT. The CHECK is the current
    #    closed vocabulary (add a value = a one-line ALTER; adding a kind to a party = an INSERT).
    "ps_party_kind": """
        CREATE TABLE ps_party_kind (
            party_id   UUID NOT NULL REFERENCES ps_party(party_id) ON DELETE CASCADE,
            tenant_id  UUID NOT NULL,
            kind       TEXT NOT NULL
                       CHECK (kind IN ('platform','product','referral','customer')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (party_id, kind)
        )""",
    # 3. Generalizes ps_partner_aliases. alias_kind is intentionally OPEN text (not a CHECK): the
    #    whole point of the generalization is that new kinds ('invoice_payer', 'handle', 'utm', ...)
    #    arrive without a migration. UNIQUE(tenant, alias_kind, alias_value) keeps a raw string
    #    mapping to exactly ONE party — a double-map is a constraint violation, not a silent bug.
    "ps_party_alias": """
        CREATE TABLE ps_party_alias (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL,
            party_id    UUID NOT NULL REFERENCES ps_party(party_id) ON DELETE CASCADE,
            alias_value TEXT NOT NULL,
            alias_kind  TEXT NOT NULL,
            source      TEXT,
            note        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, alias_kind, alias_value)
        )""",
    # 4. Promotes the ps_partner_terms shape into a documented, party-keyed deal. rate_pct is
    #    NULLABLE and DOCUMENTARY only — the effective-dated money source is BE-2 (ps_partner_rate).
    #    effective_from/to are DATE per the BE-1 spec (ps_partner_terms used timestamptz).
    "ps_party_deal": """
        CREATE TABLE ps_party_deal (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL,
            party_id       UUID NOT NULL REFERENCES ps_party(party_id) ON DELETE CASCADE,
            product_id     TEXT,
            basis          TEXT,
            rate_pct       NUMERIC,
            effective_from DATE,
            effective_to   DATE,
            contract_ref   TEXT,
            note           TEXT,
            created_by     TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, party_id, product_id, effective_from)
        )""",
    # 5. Customer bridge at COMPANY grain (Q2). canonical_brand_id is the company spine key =
    #    COALESCE(ps_brands.canonical_brand_id, wayward_brand_id) — always a real ps_brands PK, so
    #    it FKs there. UNIQUE both ways = a strict 1:1 company<->customer-party. Member brands are
    #    reached WITHOUT a second table (see the bridge note in the report): join ps_brands on
    #    COALESCE(canonical_brand_id, wayward_brand_id) = ps_customer_party.canonical_brand_id.
    "ps_customer_party": """
        CREATE TABLE ps_customer_party (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL,
            party_id           UUID NOT NULL REFERENCES ps_party(party_id) ON DELETE CASCADE,
            canonical_brand_id UUID NOT NULL REFERENCES ps_brands(wayward_brand_id),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, canonical_brand_id),
            UNIQUE (tenant_id, party_id)
        )""",
}

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX idx_ps_party_tenant ON ps_party (tenant_id)",
    "CREATE INDEX idx_ps_party_kind_party ON ps_party_kind (tenant_id, party_id)",
    "CREATE INDEX idx_ps_party_alias_party ON ps_party_alias (tenant_id, party_id)",
    "CREATE INDEX idx_ps_party_deal_party ON ps_party_deal (tenant_id, party_id)",
    "CREATE INDEX idx_ps_customer_party_brand ON ps_customer_party (tenant_id, canonical_brand_id)",
    # Supports the new FK + the lens join ps_partner_credit -> ps_party.
    "CREATE INDEX idx_ps_partner_credit_party ON ps_partner_credit (tenant_id, party_id)",
)


def _rls_and_read_grants(table: str) -> None:
    """Match the repo RLS pattern (cip_39/42/44): FORCE tenant-scoped RLS, then GRANT SELECT to the
    three read roles + the reporting reader. Migrations run as the schema owner (BYPASSRLS), so the
    seed/backfill DML below is unaffected by these policies (see env.py)."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {table} TO {role}")


# ── lens_ps_product_eligibility: identical to cip_106, + two appended columns ────────────────────
# cip_106 is the current live definition. It now has DEPENDENTS (lens_ps_claim via cip_107, cip_113,
# cip_114, cip_126), so a DROP would cascade the money lenses — CREATE OR REPLACE VIEW is mandatory,
# which requires the leading columns be preserved verbatim and any new columns appended at the END.
_LENS_WITH_PARTY = """
CREATE OR REPLACE VIEW lens_ps_product_eligibility AS
WITH prods AS (
    SELECT DISTINCT product_id FROM ps_products
),
china AS (
    SELECT wayward_brand_id FROM lens_ps_china_verdict WHERE verdict = 'china'
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_rev_share
    FROM ps_excluded_brands
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY 1
),
deal AS (
    SELECT DISTINCT ON (source_id) source_id,
           NULLIF(properties ->> 'usage_fee', '')::numeric                    AS connect_rate,
           NULLIF(properties ->> 'wayward_boosted_usage_fee_rate', '')::numeric AS boost_rate
    FROM cip_deals
    ORDER BY source_id, refreshed_at DESC NULLS LAST
),
feed_rate AS (
    SELECT o.wayward_brand_id,
           max(d.connect_rate) AS connect_rate,
           max(d.boost_rate)   AS boost_rate
    FROM ps_brand_observations o
    JOIN deal d ON d.source_id = o.value
    WHERE o.field = 'hubspot_deal_id' AND o.value <> ''
    GROUP BY 1
)
SELECT
    b.wayward_brand_id,
    b.brand_name,
    p.product_id,
    COALESCE(ov.ps_rev_share_eligible,
             CASE WHEN e.any_rev_share AND p.product_id = 'connect' THEN false ELSE true END)
        AS ps_rev_share_eligible,
    CASE WHEN ov.ps_rev_share_eligible IS NOT NULL THEN 'manual_override'
         WHEN e.wayward_brand_id IS NULL              THEN 'never_listed'
         WHEN e.any_rev_share AND p.product_id = 'connect' THEN 'rev_share_excl_connect'
         WHEN e.any_rev_share AND p.product_id <> 'connect' THEN 'rev_share_boost_open'
         WHEN e.any_flat_fee                          THEN 'flat_fee_era_eric'
         ELSE 'eligible' END AS basis,
    COALESCE(ov.wayward_fee_rate_override,
             CASE WHEN p.product_id = 'connect' THEN fr.connect_rate
                  WHEN p.product_id = 'boosted' THEN fr.boost_rate END,
             CASE WHEN p.product_id = 'connect' THEN 0.05
                  WHEN p.product_id = 'boosted' THEN 0.10 END)
        AS wayward_client_fee_rate,
    CASE WHEN ov.wayward_fee_rate_override IS NOT NULL THEN 'override'
         WHEN (p.product_id = 'connect' AND fr.connect_rate IS NOT NULL)
           OR (p.product_id = 'boosted' AND fr.boost_rate IS NOT NULL) THEN 'feed'
         ELSE 'standard_default' END AS wayward_fee_rate_basis,
    (pc.partner_of_record IS NOT NULL AND pc.partner_of_record <> 'unassigned')
        AS ps_partner_rev_share_eligible,
    NULLIF(pc.partner_of_record, 'unassigned') AS partner_name,
    pc.partner_rate AS partner_rate_pct,
    -- cip_130 additive columns (APPENDED — CREATE OR REPLACE requires leading cols unchanged):
    -- the referral partner's stable identity alongside the raw partner_name/rate. LEFT JOIN on a
    -- PK (ps_party.party_id) => at most one match => zero row fan-out => existing columns/rows and
    -- every downstream money number are unchanged.
    pty.party_id     AS party_id,
    pty.display_name AS display_name
FROM china cb
JOIN ps_brands b ON b.wayward_brand_id = cb.wayward_brand_id
CROSS JOIN prods p
LEFT JOIN excl e ON e.wayward_brand_id = b.wayward_brand_id
LEFT JOIN feed_rate fr ON fr.wayward_brand_id = b.wayward_brand_id
LEFT JOIN ps_partner_credit pc
       ON pc.wayward_brand_id = b.wayward_brand_id AND pc.product_id = p.product_id
LEFT JOIN ps_product_eligibility ov
       ON ov.wayward_brand_id = b.wayward_brand_id AND ov.product_id = p.product_id
LEFT JOIN ps_party pty ON pty.party_id = pc.party_id
"""

# Downgrade view: revert to the cip_106 body but KEEP party_id/display_name as typed NULLs. Postgres
# CREATE OR REPLACE VIEW cannot DROP columns, and the live dependents forbid a DROP+recreate, so the
# 12-column signature must stay. Crucially this also REMOVES the ps_party join + the pc.party_id
# reference, so the subsequent column/table drops succeed. The two trailing NULL columns are inert.
_LENS_REVERT = """
CREATE OR REPLACE VIEW lens_ps_product_eligibility AS
WITH prods AS (
    SELECT DISTINCT product_id FROM ps_products
),
china AS (
    SELECT wayward_brand_id FROM lens_ps_china_verdict WHERE verdict = 'china'
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_rev_share
    FROM ps_excluded_brands
    WHERE wayward_brand_id IS NOT NULL
    GROUP BY 1
),
deal AS (
    SELECT DISTINCT ON (source_id) source_id,
           NULLIF(properties ->> 'usage_fee', '')::numeric                    AS connect_rate,
           NULLIF(properties ->> 'wayward_boosted_usage_fee_rate', '')::numeric AS boost_rate
    FROM cip_deals
    ORDER BY source_id, refreshed_at DESC NULLS LAST
),
feed_rate AS (
    SELECT o.wayward_brand_id,
           max(d.connect_rate) AS connect_rate,
           max(d.boost_rate)   AS boost_rate
    FROM ps_brand_observations o
    JOIN deal d ON d.source_id = o.value
    WHERE o.field = 'hubspot_deal_id' AND o.value <> ''
    GROUP BY 1
)
SELECT
    b.wayward_brand_id,
    b.brand_name,
    p.product_id,
    COALESCE(ov.ps_rev_share_eligible,
             CASE WHEN e.any_rev_share AND p.product_id = 'connect' THEN false ELSE true END)
        AS ps_rev_share_eligible,
    CASE WHEN ov.ps_rev_share_eligible IS NOT NULL THEN 'manual_override'
         WHEN e.wayward_brand_id IS NULL              THEN 'never_listed'
         WHEN e.any_rev_share AND p.product_id = 'connect' THEN 'rev_share_excl_connect'
         WHEN e.any_rev_share AND p.product_id <> 'connect' THEN 'rev_share_boost_open'
         WHEN e.any_flat_fee                          THEN 'flat_fee_era_eric'
         ELSE 'eligible' END AS basis,
    COALESCE(ov.wayward_fee_rate_override,
             CASE WHEN p.product_id = 'connect' THEN fr.connect_rate
                  WHEN p.product_id = 'boosted' THEN fr.boost_rate END,
             CASE WHEN p.product_id = 'connect' THEN 0.05
                  WHEN p.product_id = 'boosted' THEN 0.10 END)
        AS wayward_client_fee_rate,
    CASE WHEN ov.wayward_fee_rate_override IS NOT NULL THEN 'override'
         WHEN (p.product_id = 'connect' AND fr.connect_rate IS NOT NULL)
           OR (p.product_id = 'boosted' AND fr.boost_rate IS NOT NULL) THEN 'feed'
         ELSE 'standard_default' END AS wayward_fee_rate_basis,
    (pc.partner_of_record IS NOT NULL AND pc.partner_of_record <> 'unassigned')
        AS ps_partner_rev_share_eligible,
    NULLIF(pc.partner_of_record, 'unassigned') AS partner_name,
    pc.partner_rate AS partner_rate_pct,
    NULL::uuid AS party_id,
    NULL::text AS display_name
FROM china cb
JOIN ps_brands b ON b.wayward_brand_id = cb.wayward_brand_id
CROSS JOIN prods p
LEFT JOIN excl e ON e.wayward_brand_id = b.wayward_brand_id
LEFT JOIN feed_rate fr ON fr.wayward_brand_id = b.wayward_brand_id
LEFT JOIN ps_partner_credit pc
       ON pc.wayward_brand_id = b.wayward_brand_id AND pc.product_id = p.product_id
LEFT JOIN ps_product_eligibility ov
       ON ov.wayward_brand_id = b.wayward_brand_id AND ov.product_id = p.product_id
"""


def _grant_lens_reads() -> None:
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON lens_ps_product_eligibility TO {role}")


def _seed_counterparty(bind) -> None:
    """One counterparty party, kinds {product, platform}. Idempotent via its 'name' alias."""
    row = bind.execute(
        text(
            "SELECT party_id FROM ps_party_alias "
            "WHERE tenant_id = :t AND alias_kind = 'name' AND alias_value = :n"
        ),
        {"t": PS_TENANT, "n": _COUNTERPARTY_DISPLAY_NAME},
    ).fetchone()
    if row is not None:
        return
    party_id = bind.execute(
        text(
            "INSERT INTO ps_party (tenant_id, display_name, status) "
            "VALUES (:t, :n, 'active') RETURNING party_id"
        ),
        {"t": PS_TENANT, "n": _COUNTERPARTY_DISPLAY_NAME},
    ).scalar()
    for kind in ("product", "platform"):
        bind.execute(
            text(
                "INSERT INTO ps_party_kind (tenant_id, party_id, kind) "
                "VALUES (:t, :p, :k) ON CONFLICT DO NOTHING"
            ),
            {"t": PS_TENANT, "p": party_id, "k": kind},
        )
    bind.execute(
        text(
            "INSERT INTO ps_party_alias (tenant_id, party_id, alias_value, alias_kind, source) "
            "VALUES (:t, :p, :n, 'name', 'seed:cip_130 counterparty') "
            "ON CONFLICT (tenant_id, alias_kind, alias_value) DO NOTHING"
        ),
        {"t": PS_TENANT, "p": party_id, "n": _COUNTERPARTY_DISPLAY_NAME},
    )


def _backfill_referral_parties(bind) -> None:
    """A referral party per distinct ps_partner_credit.partner_of_record (excluding the sentinels
    'unassigned' / '_default' / ''), + a 'handle' alias for the raw string, + set credit.party_id.
    Idempotent: the 'handle' alias (UNIQUE) is the dedup key; a re-run reuses the existing party."""
    rows = bind.execute(
        text(
            """
            SELECT pc.partner_of_record                         AS handle,
                   COALESCE(max(r.name), pc.partner_of_record)  AS display_name,
                   max(r.country)                               AS country
            FROM ps_partner_credit pc
            LEFT JOIN ps_partner_registry r
                   ON r.tenant_id = pc.tenant_id AND r.partner_id = pc.partner_of_record
            WHERE pc.partner_of_record IS NOT NULL
              AND pc.partner_of_record NOT IN ('unassigned', '_default')
              AND pc.partner_of_record <> ''
            GROUP BY pc.partner_of_record
            """
        )
    ).fetchall()
    for handle, display_name, country in rows:
        existing = bind.execute(
            text(
                "SELECT party_id FROM ps_party_alias "
                "WHERE tenant_id = :t AND alias_kind = 'handle' AND alias_value = :h"
            ),
            {"t": PS_TENANT, "h": handle},
        ).fetchone()
        if existing is not None:
            party_id = existing[0]
        else:
            party_id = bind.execute(
                text(
                    "INSERT INTO ps_party (tenant_id, display_name, country, status) "
                    "VALUES (:t, :dn, :c, 'active') RETURNING party_id"
                ),
                {"t": PS_TENANT, "dn": display_name, "c": country},
            ).scalar()
            bind.execute(
                text(
                    "INSERT INTO ps_party_kind (tenant_id, party_id, kind) "
                    "VALUES (:t, :p, 'referral') ON CONFLICT DO NOTHING"
                ),
                {"t": PS_TENANT, "p": party_id},
            )
            bind.execute(
                text(
                    "INSERT INTO ps_party_alias (tenant_id, party_id, alias_value, alias_kind, source) "
                    "VALUES (:t, :p, :h, 'handle', 'backfill:ps_partner_credit.partner_of_record') "
                    "ON CONFLICT (tenant_id, alias_kind, alias_value) DO NOTHING"
                ),
                {"t": PS_TENANT, "p": party_id, "h": handle},
            )
        bind.execute(
            text(
                "UPDATE ps_partner_credit SET party_id = :p "
                "WHERE tenant_id = :t AND partner_of_record = :h AND party_id IS DISTINCT FROM :p"
            ),
            {"t": PS_TENANT, "p": party_id, "h": handle},
        )


def _backfill_customer_parties(bind) -> None:
    """One customer party per COMPANY (the ps_brands.canonical_brand_id spine). Idempotent via
    ps_customer_party's UNIQUE(tenant_id, canonical_brand_id)."""
    companies = bind.execute(
        text(
            """
            SELECT COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
                   COALESCE(
                     max(b.brand_name) FILTER (
                       WHERE b.wayward_brand_id = COALESCE(b.canonical_brand_id, b.wayward_brand_id)),
                     max(b.brand_name)
                   ) AS company_name
            FROM ps_brands b
            -- Scope to the CHINA book: a company is a customer of THIS app iff it has >=1 china brand.
            -- (QC #1: avoids seeding ~4,500 parties incl JUNK/GHOST; the reporting reads are china-scoped.
            --  The party model stays general — non-china customers are a later backfill if ever needed.)
            WHERE COALESCE(b.canonical_brand_id, b.wayward_brand_id) IN (
                SELECT COALESCE(b2.canonical_brand_id, b2.wayward_brand_id)
                FROM ps_brands b2
                JOIN lens_ps_china_verdict cv ON cv.wayward_brand_id = b2.wayward_brand_id
                WHERE cv.verdict = 'china'
            )
            GROUP BY COALESCE(b.canonical_brand_id, b.wayward_brand_id)
            """
        )
    ).fetchall()
    for company_id, company_name in companies:
        exists = bind.execute(
            text(
                "SELECT 1 FROM ps_customer_party "
                "WHERE tenant_id = :t AND canonical_brand_id = :c"
            ),
            {"t": PS_TENANT, "c": company_id},
        ).fetchone()
        if exists is not None:
            continue
        party_id = bind.execute(
            text(
                "INSERT INTO ps_party (tenant_id, display_name, status) "
                "VALUES (:t, COALESCE(:dn, '(unnamed brand)'), 'active') RETURNING party_id"
            ),
            {"t": PS_TENANT, "dn": company_name},
        ).scalar()
        bind.execute(
            text(
                "INSERT INTO ps_party_kind (tenant_id, party_id, kind) "
                "VALUES (:t, :p, 'customer') ON CONFLICT DO NOTHING"
            ),
            {"t": PS_TENANT, "p": party_id},
        )
        bind.execute(
            text(
                "INSERT INTO ps_customer_party (tenant_id, party_id, canonical_brand_id) "
                "VALUES (:t, :p, :c) ON CONFLICT (tenant_id, canonical_brand_id) DO NOTHING"
            ),
            {"t": PS_TENANT, "p": party_id, "c": company_id},
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Set the tenant GUC (txn-local) so the FORCE-RLS WITH CHECK on the new tables passes for the
    # seed/backfill DML below even if the migration role is NOT BYPASSRLS (defensive — harmless under
    # the owner role; matches the set_config(..., true) pattern used everywhere else).
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    # ── 1. Tables (parents first), indexes, RLS + read grants ────────────────
    for t in _TABLES:
        op.execute(_DDL[t])
    for stmt in _INDEXES:
        op.execute(stmt)
    for t in _TABLES:
        _rls_and_read_grants(t)

    # ── 2. Additive FK on the existing credit table (partner_of_record UNTOUCHED) ─
    op.execute(
        "ALTER TABLE ps_partner_credit "
        "ADD COLUMN IF NOT EXISTS party_id UUID NULL REFERENCES ps_party(party_id)"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.party_id IS "
        "'cip_130 (BE-1): stable referral-party id. ADDITIVE — partner_of_record (the text "
        "FK-by-value) stays the authoritative key until reads are re-pointed. NULL = not yet "
        "linked to a party.'"
    )

    # ── 3. Writer grants — extend the cip_127 ps_reporting_writer _UPSERT set ─
    for t in _WRITE_TARGETS:
        op.execute(f"GRANT INSERT, UPDATE, SELECT ON {t} TO {_WRITER}")

    # ── 4. Seed the counterparty, then backfill referral + customer parties ──
    _seed_counterparty(bind)
    _backfill_referral_parties(bind)
    _backfill_customer_parties(bind)

    # ── 5. Additive lens change: expose party_id + display_name (append-only) ─
    op.execute(_LENS_WITH_PARTY)
    op.execute(
        "COMMENT ON VIEW lens_ps_product_eligibility IS "
        "$c$Effective per-product PS eligibility + Wayward's client fee rate, per CHINA brand x "
        "product (cip_105/106; cip_130 appends party_id + display_name). wayward_client_fee_rate: "
        "override -> feed (cip_deals) -> standard default 0.05 Connect / 0.10 Boost. "
        "partner_name/partner_rate_pct from ps_partner_credit (raw handle + rate). "
        "party_id/display_name (cip_130): the referral partner's STABLE identity via "
        "ps_partner_credit.party_id -> ps_party, alongside the raw handle. ADDITIVE only — the "
        "leading 10 columns and every row are unchanged, so the money lenses reading this view are "
        "untouched.$c$"
    )
    _grant_lens_reads()

    print(
        "cip_130: created ps_party/_kind/_alias/_deal + ps_customer_party (RLS + reads), "
        "added ps_partner_credit.party_id, extended ps_reporting_writer, seeded the counterparty, "
        "backfilled referral + customer parties, appended party_id/display_name to "
        "lens_ps_product_eligibility"
    )


def downgrade() -> None:
    # Revert the view FIRST (drops the ps_party join + pc.party_id reference; keeps the two trailing
    # columns as typed NULLs because CREATE OR REPLACE VIEW cannot drop columns while dependents
    # exist). This lets the column/table drops below succeed.
    op.execute(_LENS_REVERT)
    op.execute(
        "COMMENT ON VIEW lens_ps_product_eligibility IS "
        "$c$Effective per-product PS eligibility + Wayward's client fee rate (cip_105/106). "
        "party_id/display_name are inert NULL placeholders left by the cip_130 downgrade: "
        "CREATE OR REPLACE VIEW cannot drop columns while dependent lenses exist.$c$"
    )
    _grant_lens_reads()

    # Additive FK column off the credit table.
    op.execute("ALTER TABLE ps_partner_credit DROP COLUMN IF EXISTS party_id")

    # Drop the new tables (reverse dependency order). Writer/reader grants and seeds go with them.
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
