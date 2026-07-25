# foundry: kind=migration domain=client-intelligence-platform
"""cip_131: effective-dated partner-rate store (BE-2) — the ONE editable rate we own.

Design of record: WORKBENCH/china-audit/REPORTING-BE0-AUDIT.md ("BE-2") + REPORTING-BACKEND-CHECKPOINT.md §1.
Fixes the "write into a void": today FAS set_rate UPDATEs ps_partner_registry.default_rate (read by
nothing); the money math reads pc.partner_rate (an offline-script column). This adds an append-only,
effective-dated `ps_partner_rate` (party × product) and repoints the money lens to read it AS-OF the
period, falling back to pc.partner_rate. FAS set_rate is rewritten (separately) to INSERT this table.

MONEY-NEUTRAL ON DAY ONE — BY CONSTRUCTION (verified vs the live cip_113 body):
  * The ledger reads the partner rate at exactly one place: `COALESCE(pc.partner_rate, 0) AS
    partner_rate_pct` (cip_113 _LEDGER_NET), used only in `partner_fee_owed = round(usage_collected *
    partner_rate_pct / 100.0, 2)`. usage_collected / mgmt_fee_owed are UNTOUCHED, so `ps_claim_owed`
    (= GREATEST(mgmt_fee_owed − wayward_paid, 0)) — the recovery number — cannot move.
  * The repoint is a one-line swap to `COALESCE(rt.rate_pct, pc.partner_rate, 0)` via a LATERAL as-of
    read of ps_partner_rate.
  * The backfill seeds ps_partner_rate ONLY for (party, product) groups whose pc.partner_rate is
    UNIFORM + POSITIVE across all the party's brands (HAVING count(DISTINCT rate)=1 AND max>0). For
    those, rt.rate_pct == pc.partner_rate → no change. For every mixed/zero group, NO row is seeded →
    rt.rate_pct is NULL → COALESCE falls through to pc.partner_rate → no change. So partner_fee_owed is
    byte-identical. Mixed partners are set deliberately later via the rate editor (owner-approved).
  * Verify (delta==0, NOT equality-to-a-constant — the number moves on the hourly sync):
    sum(lens_ps_claim.ps_claim_owed) china and sum(lens_ps_commission_ledger.partner_fee_owed) china
    must be identical immediately-before vs immediately-after. (Expected ≈ $14,077.02 / $1,041.74.)

UNITS (R21 reconciliation): rate_pct is a PERCENT (e.g. 5.0 = 5%), matching the engine's `/100.0`.
pc.partner_rate is already a percent, so the backfill copies it verbatim. The FAS set_rate rewrite
must accept/store PERCENT too (today it bounds a fraction 0..0.5 — that is the void path; the live
money path is pc.partner_rate percent). Table CHECK is a sane 0..100 percent guard; the tighter
business bound lives at the FAS write layer (defense in depth — and so the backfill never trips it).

Revision ID: cip_131_partner_rate   (20 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_130_parties
APPLY-TIME (not in file): export FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="solo_kimi_k3_engine_dir".
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_131_partner_rate"
down_revision: str | Sequence[str] | None = "cip_130_parties"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_READER = "ps_reporting_reader"
_WRITER = "ps_reporting_writer"
_RATE_EPOCH = "2020-01-01"  # early anchor: before any Stripe data → the seeded rate covers all periods.

_DDL_PARTNER_RATE = """
    CREATE TABLE ps_partner_rate (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id      UUID NOT NULL,
        party_id       UUID NOT NULL REFERENCES ps_party(party_id) ON DELETE CASCADE,
        product_id     TEXT NOT NULL,
        rate_pct       NUMERIC NOT NULL CHECK (rate_pct >= 0 AND rate_pct <= 100),  -- PERCENT
        basis          TEXT,
        effective_from DATE NOT NULL DEFAULT current_date,
        effective_to   DATE,
        set_by         TEXT NOT NULL,
        set_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        write_id       UUID,
        note           TEXT,
        UNIQUE (tenant_id, party_id, product_id, effective_from)
    )"""

_INDEX_ASOF = (
    "CREATE INDEX idx_ps_partner_rate_asof "
    "ON ps_partner_rate (tenant_id, party_id, product_id, effective_from DESC)"
)

# ── lens_ps_commission_ledger — cip_113 _LEDGER_NET verbatim, + a LATERAL as-of read of
#    ps_partner_rate and a one-line COALESCE swap (marked  <<< cip_131). Everything else is byte-
#    identical to cip_113, so usage_collected / mgmt_fee_owed / claimable are unchanged. ────────────
_LEDGER_REPOINTED = r"""CREATE OR REPLACE VIEW lens_ps_commission_ledger AS WITH collected AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           COALESCE(sum(amount) FILTER (WHERE invoice_status = 'paid'), 0) AS usage_collected,
           COALESCE(sum(amount) FILTER (WHERE invoice_status IN ('paid','open')), 0) AS usage_billed
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base AND product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
    GROUP BY 1, 2, 3
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_excluded,
           max(ours_revenue_from)                     AS ours_revenue_from
    FROM ps_excluded_brands WHERE wayward_brand_id IS NOT NULL GROUP BY 1
),
graded AS (
    SELECT
        c.wayward_brand_id, c.product_id, c.period_month,
        c.usage_collected - COALESCE(ra.usage_refund_netted, 0) AS usage_collected, c.usage_billed,
        v.verdict,
        CASE WHEN e.wayward_brand_id IS NULL THEN 'never_listed'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN 'flat_fee_era_eric'
             ELSE 'excluded' END AS ownership,
        CASE WHEN e.wayward_brand_id IS NULL THEN DATE '2025-10-01'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
             ELSE NULL END AS ours_revenue_from,
        CASE WHEN rs.effective_anchor IS NULL THEN 0.10
             WHEN c.period_month < rs.rate_10_until THEN 0.10
             WHEN c.period_month < rs.rate_6_until  THEN 0.06
             ELSE 0.03 END AS mgmt_rate,
        pc.partner_of_record,
        COALESCE(rt.rate_pct, pc.partner_rate, 0) AS partner_rate_pct,   -- <<< cip_131: as-of ps_partner_rate, else pc.partner_rate
        pc.credit_start, pc.credit_end,
        (COALESCE(el.ps_rev_share_eligible, false)
         AND c.period_month >= CASE WHEN e.any_flat_fee AND NOT e.any_excluded
                                    THEN e.ours_revenue_from ELSE DATE '2025-10-01' END) AS claimable
    FROM collected c
    LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
    LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN ps_partner_credit pc
           ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
    LEFT JOIN LATERAL (                                                   -- <<< cip_131: as-of partner rate
        SELECT r.rate_pct
        FROM ps_partner_rate r
        WHERE r.tenant_id = pc.tenant_id
          AND r.party_id = pc.party_id
          AND r.product_id = c.product_id
          AND r.effective_from <= c.period_month
          AND (r.effective_to IS NULL OR r.effective_to > c.period_month)
        ORDER BY r.effective_from DESC
        LIMIT 1
    ) rt ON true
    LEFT JOIN lens_ps_product_eligibility el
           ON el.wayward_brand_id = c.wayward_brand_id AND el.product_id = c.product_id
    LEFT JOIN lens_ps_refund_allocation ra
           ON ra.wayward_brand_id = c.wayward_brand_id AND ra.product_id = c.product_id AND ra.period_month = c.period_month
)
SELECT
    g.wayward_brand_id, g.product_id, g.period_month,
    g.usage_billed, g.usage_collected,
    g.verdict, g.ownership, g.ours_revenue_from, g.mgmt_rate, g.claimable,
    CASE WHEN g.claimable THEN round(g.usage_collected * g.mgmt_rate, 2) ELSE 0 END AS mgmt_fee_owed,
    g.partner_of_record, g.partner_rate_pct,
    CASE WHEN g.claimable
              AND g.period_month >= COALESCE(g.credit_start, g.period_month)
              AND g.period_month <= COALESCE(g.credit_end, g.period_month)
         THEN round(g.usage_collected * g.partner_rate_pct / 100.0, 2)
         ELSE 0 END AS partner_fee_owed,
    CASE WHEN g.verdict = 'china'   THEN 'claimable'
         WHEN g.verdict = 'unknown' THEN 'unknown_nationality'
         ELSE 'not_china' END AS claim_status
FROM graded g"""

# Downgrade target: the exact cip_113 _LEDGER_NET (no LATERAL, plain COALESCE(pc.partner_rate,0)).
_LEDGER_REVERT = r"""CREATE OR REPLACE VIEW lens_ps_commission_ledger AS WITH collected AS (
    SELECT wayward_brand_id, product_id, billing_month::date AS period_month,
           COALESCE(sum(amount) FILTER (WHERE invoice_status = 'paid'), 0) AS usage_collected,
           COALESCE(sum(amount) FILTER (WHERE invoice_status IN ('paid','open')), 0) AS usage_billed
    FROM ps_stripe_invoice_lines
    WHERE is_ps_base AND product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
    GROUP BY 1, 2, 3
),
excl AS (
    SELECT wayward_brand_id,
           bool_or(disposition = 'flat_fee_era_eric') AS any_flat_fee,
           bool_or(disposition = 'excluded')          AS any_excluded,
           max(ours_revenue_from)                     AS ours_revenue_from
    FROM ps_excluded_brands WHERE wayward_brand_id IS NOT NULL GROUP BY 1
),
graded AS (
    SELECT
        c.wayward_brand_id, c.product_id, c.period_month,
        c.usage_collected - COALESCE(ra.usage_refund_netted, 0) AS usage_collected, c.usage_billed,
        v.verdict,
        CASE WHEN e.wayward_brand_id IS NULL THEN 'never_listed'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN 'flat_fee_era_eric'
             ELSE 'excluded' END AS ownership,
        CASE WHEN e.wayward_brand_id IS NULL THEN DATE '2025-10-01'
             WHEN e.any_flat_fee AND NOT e.any_excluded THEN e.ours_revenue_from
             ELSE NULL END AS ours_revenue_from,
        CASE WHEN rs.effective_anchor IS NULL THEN 0.10
             WHEN c.period_month < rs.rate_10_until THEN 0.10
             WHEN c.period_month < rs.rate_6_until  THEN 0.06
             ELSE 0.03 END AS mgmt_rate,
        pc.partner_of_record,
        COALESCE(pc.partner_rate, 0) AS partner_rate_pct,
        pc.credit_start, pc.credit_end,
        (COALESCE(el.ps_rev_share_eligible, false)
         AND c.period_month >= CASE WHEN e.any_flat_fee AND NOT e.any_excluded
                                    THEN e.ours_revenue_from ELSE DATE '2025-10-01' END) AS claimable
    FROM collected c
    LEFT JOIN lens_ps_rate_schedule rs USING (wayward_brand_id, product_id)
    LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN excl e ON e.wayward_brand_id = c.wayward_brand_id
    LEFT JOIN ps_partner_credit pc
           ON pc.wayward_brand_id = c.wayward_brand_id AND pc.product_id = c.product_id
    LEFT JOIN lens_ps_product_eligibility el
           ON el.wayward_brand_id = c.wayward_brand_id AND el.product_id = c.product_id
    LEFT JOIN lens_ps_refund_allocation ra
           ON ra.wayward_brand_id = c.wayward_brand_id AND ra.product_id = c.product_id AND ra.period_month = c.period_month
)
SELECT
    g.wayward_brand_id, g.product_id, g.period_month,
    g.usage_billed, g.usage_collected,
    g.verdict, g.ownership, g.ours_revenue_from, g.mgmt_rate, g.claimable,
    CASE WHEN g.claimable THEN round(g.usage_collected * g.mgmt_rate, 2) ELSE 0 END AS mgmt_fee_owed,
    g.partner_of_record, g.partner_rate_pct,
    CASE WHEN g.claimable
              AND g.period_month >= COALESCE(g.credit_start, g.period_month)
              AND g.period_month <= COALESCE(g.credit_end, g.period_month)
         THEN round(g.usage_collected * g.partner_rate_pct / 100.0, 2)
         ELSE 0 END AS partner_fee_owed,
    CASE WHEN g.verdict = 'china'   THEN 'claimable'
         WHEN g.verdict = 'unknown' THEN 'unknown_nationality'
         ELSE 'not_china' END AS claim_status
FROM graded g"""


def _repoint_eligibility_rate(upgrade: bool) -> str:
    """lens_ps_product_eligibility: change ONLY the partner_rate_pct source line (display column;
    the ledger reads pc.partner_rate directly, not this) — as-of ps_partner_rate on upgrade, plain
    pc.partner_rate on downgrade. Rebuilt from the cip_130 body (the live definition)."""
    if upgrade:
        rate_expr = (
            "COALESCE(rt.rate_pct, pc.partner_rate) AS partner_rate_pct"  # <<< cip_131 as-of (today)
        )
        rate_lateral = (
            "LEFT JOIN LATERAL (SELECT r.rate_pct FROM ps_partner_rate r "
            "WHERE r.tenant_id = pc.tenant_id AND r.party_id = pc.party_id "
            "AND r.product_id = p.product_id AND r.effective_from <= current_date "
            "AND (r.effective_to IS NULL OR r.effective_to > current_date) "
            "ORDER BY r.effective_from DESC LIMIT 1) rt ON true\n"
        )
    else:
        rate_expr = "pc.partner_rate AS partner_rate_pct"
        rate_lateral = ""
    return f"""
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
    {rate_expr},
    pty.party_id     AS party_id,
    pty.display_name AS display_name
FROM china cb
JOIN ps_brands b ON b.wayward_brand_id = cb.wayward_brand_id
CROSS JOIN prods p
LEFT JOIN excl e ON e.wayward_brand_id = b.wayward_brand_id
LEFT JOIN feed_rate fr ON fr.wayward_brand_id = b.wayward_brand_id
LEFT JOIN ps_partner_credit pc
       ON pc.wayward_brand_id = b.wayward_brand_id AND pc.product_id = p.product_id
{rate_lateral}LEFT JOIN ps_product_eligibility ov
       ON ov.wayward_brand_id = b.wayward_brand_id AND ov.product_id = p.product_id
LEFT JOIN ps_party pty ON pty.party_id = pc.party_id
"""


def _rls_and_read_grants(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY cip_tenant_scope ON {table} USING ({_PRED}) WITH CHECK ({_PRED})")
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {table} TO {role}")


def _grant_lens_reads(view: str) -> None:
    for role in (*_READ_ROLES, _READER):
        op.execute(f"GRANT SELECT ON {view} TO {role}")


def upgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")

    # 1. The rate store + as-of index + RLS/read grants + writer grant (FAS set_rate INSERTs here).
    op.execute(_DDL_PARTNER_RATE)
    op.execute(_INDEX_ASOF)
    _rls_and_read_grants("ps_partner_rate")
    op.execute(f"GRANT INSERT, UPDATE, SELECT ON ps_partner_rate TO {_WRITER}")

    # 2. Money-safe backfill: ONLY (party, product) groups whose pc.partner_rate is uniform + positive.
    #    Effective from an early epoch so it covers every period the ledger currently rates.
    op.execute(
        f"""
        INSERT INTO ps_partner_rate (tenant_id, party_id, product_id, rate_pct, basis, effective_from, set_by)
        SELECT pc.tenant_id, pc.party_id, pc.product_id,
               max(pc.partner_rate), 'backfill_uniform', DATE '{_RATE_EPOCH}', 'backfill:cip_131'
        FROM ps_partner_credit pc
        WHERE pc.party_id IS NOT NULL AND pc.product_id IS NOT NULL AND pc.product_id <> ''
        GROUP BY pc.tenant_id, pc.party_id, pc.product_id
        HAVING count(DISTINCT COALESCE(pc.partner_rate, 0)) = 1
           AND max(pc.partner_rate) > 0
           AND max(pc.partner_rate) <= 100
        ON CONFLICT (tenant_id, party_id, product_id, effective_from) DO NOTHING
        """
    )

    # 3. Repoint the money lens (as-of read) + the display-only eligibility rate.
    op.execute(_LEDGER_REPOINTED)
    _grant_lens_reads("lens_ps_commission_ledger")
    op.execute(_repoint_eligibility_rate(upgrade=True))
    _grant_lens_reads("lens_ps_product_eligibility")

    op.execute(
        "COMMENT ON TABLE ps_partner_rate IS $c$BE-2 (cip_131): append-oriented (a supersession sets "
        "effective_to via the writer's UPDATE grant), effective-dated partner "
        "rate (party x product), PERCENT. The ONE rate we own + edit. Read AS-OF the period by "
        "lens_ps_commission_ledger (COALESCE(rt.rate_pct, pc.partner_rate, 0)); a forward edit = a new "
        "row, a retro edit = a row over the window, and history recomputes on read (money is live "
        "views). Seeded only for uniform+positive partners; mixed set deliberately via FAS set_rate.$c$"
    )
    # Refresh the catalog COMMENTs so they describe the NEW as-of rate source (not the pre-repoint body).
    op.execute(
        "COMMENT ON VIEW lens_ps_commission_ledger IS $c$Per brand x product x month commission ledger. "
        "usage_collected is NET of succeeded refunds (cip_113); usage_billed stays gross; mgmt_fee = net "
        "collected x the 10/6/3 ladder when claimable. cip_131: partner_rate_pct = COALESCE(as-of "
        "ps_partner_rate.rate_pct, pc.partner_rate, 0); partner_fee_owed = round(usage_collected x that / "
        "100, 2) — day-1 unchanged (seeded rates equal pc.partner_rate).$c$"
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_product_eligibility IS $c$Effective per-product PS eligibility + Wayward's "
        "client fee rate per CHINA brand x product (cip_105/106; cip_130 appends party_id/display_name). "
        "cip_131: partner_rate_pct now reads the as-of (today) ps_partner_rate else pc.partner_rate — "
        "DISPLAY ONLY (the money ledger reads pc.partner_rate directly, not this column).$c$"
    )
    for _col, _doc in (
        ("effective_from", "as-of date this rate takes effect (inclusive); the read picks the latest effective_from <= period"),
        ("effective_to", "exclusive end of the window; NULL = open. The writer sets it on supersession to bound a retro correction"),
        ("write_id", "governed-write correlation id (FAS set_rate); NULL for the cip_131 backfill"),
        ("basis", "free-text provenance, e.g. backfill_uniform, or the FAS write basis"),
    ):
        op.execute(f"COMMENT ON COLUMN ps_partner_rate.{_col} IS '{_doc}'")

    print(
        "cip_131: created ps_partner_rate (RLS + reads + writer), backfilled uniform+positive "
        "partners, repointed lens_ps_commission_ledger (as-of) + lens_ps_product_eligibility (display)"
    )


def downgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")
    # Restore the exact prior view bodies (removes the ps_partner_rate references) BEFORE dropping it.
    op.execute(_LEDGER_REVERT)
    _grant_lens_reads("lens_ps_commission_ledger")
    op.execute(_repoint_eligibility_rate(upgrade=False))
    _grant_lens_reads("lens_ps_product_eligibility")
    op.execute("DROP TABLE IF EXISTS ps_partner_rate CASCADE")
