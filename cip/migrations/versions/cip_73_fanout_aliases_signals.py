# foundry: kind=migration domain=client-intelligence-platform
"""cip_73: the lenses were fanning out, one brand had two identities, and we ignored a real signal.

Three findings from an adversarial audit, all verified independently.

DEFECT 1 — THE LENSES FAN OUT. EVERY SUMMARY I HAVE PRINTED WAS INFLATED.
------------------------------------------------------------------------
lens_ps_china_verdict and lens_ps_eligibility both do a raw
`LEFT JOIN ps_excluded_brands ON wayward_brand_id`. That table holds 817 rows for 807 DISTINCT
brands — ten brands are listed under two buckets (Roborock is Eric Rev Share AND Heavy Producer).
The join duplicates them.

    lens_ps_china_verdict   1,752 rows for 1,742 brands   -> 10 phantom rows
    sum(usage_collected)    $2,325,757.42 vs the true $2,142,374.01
    INFLATED BY             $183,383.41   (+8.6%)

Roborock alone double-counted $172,379.62. harvest_nationality_signals.py and
manual_china_review_2026_07_13.py both print their summaries FROM this view, so every number those
scripts have reported was wrong. The claim itself was NOT affected — ps_monthly_earnings is clean,
and reconciles to Stripe to the cent — but every SUMMARY was.

Fixed by joining lens_ps_exclusion_status (cip_68), which already aggregates one row per brand.
The dedupe existed; the lenses just did not use it.

DEFECT 2 — ONE BRAND, TWO IDENTITIES, AND WE WOULD HAVE INVOICED FOR SETTLED MONEY
----------------------------------------------------------------------------------
    SpaceAid   572baf79...   $8,870.45 collected   we claim $511.18   Wayward paid $0.00
    Spaceaid   ebfa1982...       $0.00 collected   we claim   $0.00   Wayward paid $846.21

Same company. Usage billed against one brand id, the REV SHARE PAID against the other. The spine
sees an unpaid brand and would invoice $511.18 for a brand Wayward has ALREADY settled with
$846.21 — the single most damaging error available to us under §4.4, where their records are
"conclusive and controlling".

It is the only case with money on both sides (checked all 689 duplicate-name groups), but a
mechanism is needed, not a one-off UPDATE: ps_brands.canonical_brand_id, so payments and usage
reconcile across every identity a brand happens to have.

DEFECT 3 — WE IGNORED A HARD SIGNAL AND RELIED ON PROSE INSTEAD
---------------------------------------------------------------
ps_stripe_customers.address_country has been sitting there since cip_57, unread by the harvester.
It independently confirms SOUTH KOREA ULIKE GROUP as CN — a brand I had called Chinese on the
strength of a pinyin contact name and world knowledge. Wayward's own record said so all along.

Nine unknown brands carry address_country IN ('CN','HK') worth ~$645.67, and one carries a +86
phone. Free, checkable, and the kind of evidence that survives being asked "how do you know?" —
which prose about Shenzhen manufacturers does not.

Revision ID: cip_73_fanout_aliases_signals
Revises: cip_72_unknown_is_not_zero
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_73_fanout_aliases_signals"
down_revision: str | Sequence[str] | None = "cip_72_unknown_is_not_zero"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

FREEZE = "2025-11-18"
RULE_B = "2025-12-01"


def upgrade() -> None:
    # ── DEFECT 2: one brand may hold several ids ────────────────────────────
    op.execute("ALTER TABLE ps_brands ADD COLUMN IF NOT EXISTS canonical_brand_id UUID")
    op.execute(
        "COMMENT ON COLUMN ps_brands.canonical_brand_id IS "
        "'When one real company holds SEVERAL wayward_brand_ids, this points every id at the one "
        "that carries the money. SpaceAid had its usage billed against one id and its rev share "
        "PAID against another, so the spine saw an unpaid brand and would have invoiced $511.18 "
        "for a brand Wayward had already settled with $846.21 — the most damaging error available "
        "under §4.4. NULL means the brand is its own canonical (the normal case).'"
    )
    # Point every duplicate name at whichever id carries the money.
    op.execute(
        """
        WITH grp AS (
            SELECT b.wayward_brand_id,
                   lower(btrim(b.brand_name)) AS nm,
                   COALESCE((SELECT sum(usage_collected) FROM ps_monthly_earnings m
                              WHERE m.wayward_brand_id = b.wayward_brand_id), 0)
                 + COALESCE((SELECT sum(rev_share_stated) FROM ps_payment_events p
                              WHERE p.wayward_brand_id = b.wayward_brand_id), 0) AS money
            FROM ps_brands b
            WHERE b.brand_name IS NOT NULL AND btrim(b.brand_name) <> ''
        ),
        winner AS (
            SELECT DISTINCT ON (nm) nm, wayward_brand_id AS canon
            FROM grp
            WHERE nm IN (SELECT nm FROM grp GROUP BY nm HAVING count(*) > 1)
            ORDER BY nm, money DESC, wayward_brand_id
        )
        UPDATE ps_brands b
           SET canonical_brand_id = w.canon
          FROM grp g
          JOIN winner w ON w.nm = g.nm
         WHERE g.wayward_brand_id = b.wayward_brand_id
           AND w.canon <> b.wayward_brand_id
        """
    )

    # ── DEFECT 3: harvest the signals we were ignoring ──────────────────────
    op.execute(
        """
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
        SELECT DISTINCT s.tenant_id, s.wayward_brand_id, 'wayward_country_cn', 'confirmed', 'china',
               'Stripe customer address_country = ' || s.address_country ||
               '. Wayward''s OWN billing record places this brand in China/HK — a checkable '
               'artifact, not an inference. This column has existed since cip_57 and the harvester '
               'never read it.',
               'stripe:address_country'
        FROM ps_stripe_customers s
        WHERE s.wayward_brand_id IS NOT NULL
          AND s.address_country IN ('CN', 'HK')
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
        SELECT DISTINCT s.tenant_id, s.wayward_brand_id, 'chinese_email_domain', 'strong', 'china',
               'Chinese phone number on the Stripe customer: ' || s.phone,
               'stripe:phone_+86'
        FROM ps_stripe_customers s
        WHERE s.wayward_brand_id IS NOT NULL AND s.phone LIKE '+86%'
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
        """
    )
    # .cn / .hk / .com.cn domains, and the vip.qq / vip.163 subdomains the old regex missed.
    op.execute(
        r"""
        INSERT INTO ps_nationality_signals
            (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
        SELECT DISTINCT s.tenant_id, s.wayward_brand_id, 'chinese_email_domain', 'strong', 'china',
               'Chinese domain on the brand contact: ' || s.email ||
               '. The original regex was anchored to the first label after @ and had no .cn TLD at '
               'all, so vip.qq.com, hoto.com.cn and ezink.cn all slipped through.',
               'stripe:cn_domain'
        FROM ps_stripe_customers s
        WHERE s.wayward_brand_id IS NOT NULL
          AND (s.email ~* '\.(cn|hk)$' OR s.email ~* '\.(com|net|org)\.(cn|hk)$'
               OR s.email ~* '@(vip\.)?(qq|163|126)\.')
        ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
        """
    )

    # ── DEFECT 1: rebuild BOTH lenses without the fan-out ───────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_conflicts")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility CASCADE")

    op.execute(
        f"""
        CREATE VIEW lens_ps_eligibility AS
        WITH billed AS (
            SELECT wayward_brand_id,
                   min(billing_month)                        AS first_billed_month,
                   max(billing_month)                        AS last_billed_month,
                   bool_or(billing_month >= DATE '{RULE_B}') AS bills_in_our_era,
                   max(client_id::text)::uuid                AS client_id
            FROM ps_stripe_invoice_lines
            WHERE is_ps_base AND amount > 0
              AND billing_month IS NOT NULL AND wayward_brand_id IS NOT NULL
            GROUP BY wayward_brand_id
        ),
        obs AS (
            SELECT wayward_brand_id,
                   max(client_id::text)::uuid                      AS client_id,
                   max(value) FILTER (WHERE field = 'brand_name')  AS brand_name,
                   max(value) FILTER (WHERE field = 'country')     AS wayward_country,
                   max(value) FILTER (WHERE field = 'deal_source') AS deal_source
            FROM ps_brand_observations
            GROUP BY wayward_brand_id
        )
        SELECT
            br.wayward_brand_id,
            COALESCE(b.client_id, obs.client_id)                   AS client_id,
            COALESCE(obs.brand_name, br.brand_name)                AS brand_name,
            b.first_billed_month,
            b.last_billed_month,
            b.bills_in_our_era,
            br.signup_date                                         AS onboarded,
            br.signup_date_source                                  AS onboarded_source,
            obs.deal_source,
            obs.wayward_country,
            c.nationality_class,
            st.buckets                                             AS excluded_bucket,
            st.is_excluded,
            st.someone_else_earning,
            st.is_winnable,
            (c.nationality_class IN ('chinese_confirmed','chinese_suspected')
             OR obs.wayward_country = 'CN')                        AS is_chinese,
            (br.signup_date > DATE '{FREEZE}')                     AS post_takeover,
            CASE
                WHEN st.is_excluded                       THEN 'excluded'
                WHEN NOT (c.nationality_class IN ('chinese_confirmed','chinese_suspected')
                          OR obs.wayward_country = 'CN')  THEN 'not_chinese'
                WHEN br.signup_date > DATE '{FREEZE}'     THEN 'eligible_rule_a'
                WHEN b.bills_in_our_era                   THEN 'eligible_rule_b'
                WHEN b.first_billed_month IS NULL         THEN 'never_billed'
                ELSE 'stopped_billing_pre_december'
            END                                                    AS eligibility,
            CASE
                WHEN st.is_excluded                       THEN NULL
                WHEN br.signup_date > DATE '{FREEZE}'     THEN b.first_billed_month
                WHEN b.bills_in_our_era                   THEN DATE '{RULE_B}'
                ELSE NULL
            END                                                    AS credit_starts
        FROM ps_brands br
        -- ONE row per brand. The raw join to ps_excluded_brands duplicated the ten brands that
        -- sit in two buckets and inflated every summary built on this view by 8.6%.
        JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = br.wayward_brand_id
        LEFT JOIN billed b   ON b.wayward_brand_id   = br.wayward_brand_id
        LEFT JOIN obs        ON obs.wayward_brand_id = br.wayward_brand_id
        LEFT JOIN cip_clients c ON c.id = COALESCE(b.client_id, obs.client_id)
        """
    )
    op.execute(
        f"COMMENT ON VIEW lens_ps_eligibility IS "
        f"'Is this brand ours? Rule A: ONBOARDED after {FREEZE}. Rule B: onboarded before it but "
        f"BILLING from {RULE_B} onward. Joins lens_ps_exclusion_status (one row per brand) rather "
        f"than ps_excluded_brands directly — the raw join duplicated the ten brands that sit in two "
        f"buckets. NOTE its is_chinese is the LEGACY signal and disagrees with lens_ps_china_verdict; "
        f"the claim engine uses the VERDICT. Do not filter money on this column.'"
    )

    op.execute(
        """
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT wayward_brand_id,
                   bool_or(signal='manual_review' AND points_to='china')     AS manual_china,
                   bool_or(signal='manual_review' AND points_to='not_china') AS manual_not_china,
                   count(*) FILTER (WHERE points_to='china')     AS china_signals,
                   count(*) FILTER (WHERE points_to='not_china') AS not_china_signals,
                   max(CASE strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                                     WHEN 'strong' THEN 4 WHEN 'moderate' THEN 3
                                     WHEN 'weak' THEN 2 ELSE 1 END)
                       FILTER (WHERE points_to='china')          AS best_china_rank,
                   string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to='china')     AS china_evidence,
                   string_agg(DISTINCT signal, ', ') FILTER (WHERE points_to='not_china') AS not_china_evidence,
                   max(evidence)    FILTER (WHERE signal='manual_review') AS manual_rationale,
                   max(asserted_by) FILTER (WHERE signal='manual_review') AS manual_by
            FROM ps_nationality_signals
            GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT wayward_brand_id,
                   sum(usage_collected)                              AS collected,
                   sum(ps_gross_owed)                                AS gross_if_claimable,
                   sum(ps_gross_owed)    FILTER (WHERE is_claimable) AS ps_owed,
                   sum(ps_actually_paid) FILTER (WHERE is_claimable) AS ps_paid
            FROM ps_monthly_earnings
            GROUP BY wayward_brand_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            b.signup_date,
            CASE
                WHEN a.manual_not_china                  THEN 'not_china'
                WHEN a.manual_china                      THEN 'china'
                WHEN COALESCE(a.china_signals,0) > 0     THEN 'china'
                WHEN COALESCE(a.not_china_signals,0) > 0 THEN 'not_china'
                ELSE 'unknown'
            END                                          AS verdict,
            CASE
                WHEN a.manual_not_china OR a.manual_china THEN 'manual'
                ELSE CASE a.best_china_rank
                        WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed' WHEN 4 THEN 'strong'
                        WHEN 3 THEN 'moderate' WHEN 2 THEN 'weak' ELSE NULL END
            END                                          AS verdict_strength,
            a.china_evidence,
            a.not_china_evidence,
            a.manual_rationale,
            a.manual_by,
            (COALESCE(a.china_signals,0) > 0 AND COALESCE(a.not_china_signals,0) > 0) AS has_conflict,
            st.is_excluded,
            st.buckets                                   AS excluded_buckets,
            round(m.collected, 2)                        AS usage_collected,
            round(COALESCE(m.ps_owed, 0), 2)             AS ps_owed_claimable,
            round(COALESCE(m.ps_paid, 0), 2)             AS ps_paid,
            round(COALESCE(m.ps_owed,0) - COALESCE(m.ps_paid,0), 2) AS shortfall,
            round(m.gross_if_claimable, 2)               AS hypothetical_if_all_claimable
        FROM ps_brands b
        JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN agg   a ON a.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
        -- NOT `WHERE collected > 0`: that dropped 213 brands (112 of them WITH china signals) out
        -- of the view entirely, so a LEFT JOIN elsewhere turned them into NULL -> 'unknown', and
        -- 51 brands sitting on the EXCLUSION LIST were being reported as "nationality unknown".
        WHERE m.wayward_brand_id IS NOT NULL
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_verdict IS "
        "'THE CHINA CALL, derived from ps_nationality_signals. Precedence: manual_review (a named "
        "human, EITHER direction) > on_exclusion_list > CHINA WINS > not_china > unknown. "
        "One row per brand — it now joins lens_ps_exclusion_status rather than ps_excluded_brands, "
        "which was duplicating the ten dual-bucket brands and inflating every summary built on this "
        "view by $183,383 (8.6%). ps_owed_claimable is the REAL debt; "
        "hypothetical_if_all_claimable is NOT.'"
    )
    op.execute(
        """
        CREATE VIEW lens_ps_nationality_conflicts AS
        SELECT v.wayward_brand_id, v.brand_name, v.verdict, v.verdict_strength,
               v.china_evidence, v.not_china_evidence, v.manual_rationale,
               v.excluded_buckets, v.usage_collected, v.ps_owed_claimable,
               v.hypothetical_if_all_claimable
        FROM lens_ps_china_verdict v
        WHERE v.has_conflict
        ORDER BY v.ps_owed_claimable DESC NULLS LAST, v.usage_collected DESC
        """
    )
    # ── the claim, reconciled across EVERY id a brand holds ─────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_reconciliation")
    op.execute(
        """
        CREATE VIEW lens_ps_claim_reconciliation AS
        WITH canon AS (
            -- Collapse split identities. SpaceAid billed its usage against one id and was PAID
            -- against another; without this the spine sees an unpaid brand and we invoice for
            -- money Wayward has already sent.
            SELECT wayward_brand_id,
                   COALESCE(canonical_brand_id, wayward_brand_id) AS canon_id
            FROM ps_brands
        ),
        owed AS (
            SELECT c.canon_id,
                   sum(e.ps_gross_owed)   FILTER (WHERE e.is_claimable) AS ps_owed,
                   sum(e.usage_collected) FILTER (WHERE e.is_claimable) AS collected,
                   string_agg(DISTINCT e.claim_basis, ', ')
                       FILTER (WHERE e.is_claimable)                    AS claim_basis
            FROM ps_monthly_earnings e
            JOIN canon c ON c.wayward_brand_id = e.wayward_brand_id
            GROUP BY c.canon_id
        ),
        paid AS (
            -- ALL of it. No product filter, no month matching: Jake pays 1-3 months in arrears,
            -- so only the BRAND total is comparable.
            SELECT c.canon_id, sum(p.rev_share_stated) AS ps_paid
            FROM ps_payment_events p
            JOIN canon c ON c.wayward_brand_id = p.wayward_brand_id
            GROUP BY c.canon_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            COALESCE(o.ps_owed, 0)                                  AS ps_owed,
            COALESCE(p.ps_paid, 0)                                  AS ps_paid,
            round(COALESCE(o.ps_owed,0) - COALESCE(p.ps_paid,0), 2) AS balance,
            CASE
                WHEN COALESCE(o.ps_owed,0) > 0 AND COALESCE(p.ps_paid,0) = 0
                     THEN 'owed_never_paid'
                WHEN COALESCE(o.ps_owed,0) > COALESCE(p.ps_paid,0) + 0.01 THEN 'underpaid'
                WHEN COALESCE(p.ps_paid,0) > COALESCE(o.ps_owed,0) + 0.01
                     AND COALESCE(o.ps_owed,0) > 0                  THEN 'OVERPAID'
                WHEN COALESCE(o.ps_owed,0) = 0 AND COALESCE(p.ps_paid,0) > 0
                     THEN 'PAID_ON_A_BRAND_WE_DO_NOT_CLAIM'
                ELSE 'square'
            END                                                     AS status,
            round(o.collected, 2)                                   AS usage_collected,
            o.claim_basis,
            st.is_excluded,
            st.buckets AS excluded_buckets
        FROM ps_brands b
        LEFT JOIN owed o ON o.canon_id = b.wayward_brand_id
        LEFT JOIN paid p ON p.canon_id = b.wayward_brand_id
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        WHERE b.canonical_brand_id IS NULL          -- one row per REAL company
          AND (COALESCE(o.ps_owed,0) <> 0 OR COALESCE(p.ps_paid,0) <> 0)
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_claim_reconciliation IS "
        "'*** THE CLAIM. Per REAL COMPANY — split identities collapsed via canonical_brand_id. *** "
        "SpaceAid billed its usage against one brand id and was PAID against another, so the spine "
        "saw an unpaid brand and we would have invoiced $511.18 for a company Wayward had already "
        "settled with $846.21. Jake also pays 1-3 months in arrears, so owed (indexed by USAGE "
        "month) and paid (by PAYMENT month) are only comparable in total. READ status BEFORE "
        "QUOTING A NUMBER: we are underpaid on some brands and OVERPAID on many others — mostly the "
        "excluded flat-fee book Wayward pays us on voluntarily, owing nothing. Net, they have paid "
        "us MORE than the contract requires, and §4.4 gives them 30 days and conclusive records.'"
    )

    for v in ("lens_ps_eligibility", "lens_ps_china_verdict", "lens_ps_nationality_conflicts",
              "lens_ps_claim_reconciliation"):
        for r in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {v} TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_conflicts")
    # lens_ps_claim_reconciliation reads canonical_brand_id, so it must go before the column does.
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_reconciliation")
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict CASCADE")
    op.execute("DROP VIEW IF EXISTS lens_ps_eligibility CASCADE")
    op.execute("ALTER TABLE ps_brands DROP COLUMN IF EXISTS canonical_brand_id")
