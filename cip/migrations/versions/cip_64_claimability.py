# foundry: kind=migration domain=client-intelligence-platform
"""cip_64: claimability. Per brand x PRODUCT x MONTH — because eligibility is not a brand fact.

TIM'S RULINGS, 2026-07-13 (Ali confirmed verbally; ratification to follow, deliberately)
----------------------------------------------------------------------------------------
  1. BOOST is ours on EVERY Chinese brand — including Excluded / Eric / Lysoatur ones.
     Boost is a net-new product and does not inherit a brand's excluded status.

  2. REACTIVATION: a brand dark for 90+ days that starts billing again is ours from that
     month, regardless of who originally referred it — BUT ONLY:
       (a) if the reactivation happened AFTER 2025-11-01, when PS restarted the China push.
           We claim reactivations we caused, not ones that happened on their own; and
       (b) for FLAT-FEE brands only — never a brand where another partner is still earning an
           ongoing 10%. You cannot win back a brand somebody else is actively being paid on.

WHY THIS CANNOT BE A BRAND-LEVEL FLAG
-------------------------------------
The same brand is now simultaneously:
    - NOT claimable on Connect   (it is an Eric flat-fee brand, never reactivated), and
    - claimable on Boost         (ruling 1), and
    - claimable on Connect from March 2026 onward, but not before, if it reactivated then.

Eligibility is therefore a property of (brand, product, month) — not of the brand. Anything
coarser silently rounds one of those three states into another, and each rounding is money.

THE FLAT-FEE / ONGOING-10% SPLIT, FROM THE DATA
-----------------------------------------------
    Eric Flat Fee Brands   582   all flat-fee   -> reactivation applies
    Eric Rev Share Brands  133   all on 10%     -> someone is still earning; hands off
    Heavy Producer          50   contract §1.4(a)
    Jeremy/Caspar, Shallow,
    OpenLight, OceanWing    52   named in the contract as prior partners
Only the first bucket can be won back by reactivation.

  NOTE / OPEN: 'Jeremy  Caspar' (34 brands) carries Eric's flat-fee flag, yet Jeremy Dai is
  NAMED in the contract §1.4(e) as an Other Partner Brand. Tim's rule says flat-fee only and
  "not the heavy producers or other excluded on contract" — those two tests disagree here, so
  the brands are EXCLUDED from reactivation (the conservative reading) and flagged as a
  question rather than silently resolved either way.

Revision ID: cip_64_claimability
Revises: cip_63_rule_b_fix
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_64_claimability"
down_revision: str | Sequence[str] | None = "cip_63_rule_b_fix"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

PUSH_RESTART = "2025-11-01"   # PS restarted the China push. Reactivations before this are not ours.
FLAT_FEE_BUCKET = "Eric Flat Fee Brands"

_BASIS = (
    "boost_all_brands",        # ruling 1 — Boost is ours even on excluded brands
    "rule_a_post_takeover",    # onboarded after the 2025-11-18 freeze
    "rule_b_december",         # onboarded before it, but billing from Dec 2025 (we run the CS)
    "reactivation_flat_fee",   # ruling 2 — 90d dark, reactivated post-2025-11-01, flat-fee only
    "not_claimable_excluded",  # excluded on Connect, never reactivated
    "not_claimable_not_chinese",
    "not_claimable_pre_takeover",
)


def upgrade() -> None:
    # ── reactivation, per brand x product ───────────────────────────────────
    op.execute(
        "ALTER TABLE ps_product_subscriptions ADD COLUMN IF NOT EXISTS reactivated_at DATE"
    )
    op.execute(
        "ALTER TABLE ps_product_subscriptions "
        "ADD COLUMN IF NOT EXISTS reactivation_qualifies BOOLEAN"
    )
    op.execute(
        "COMMENT ON COLUMN ps_product_subscriptions.reactivated_at IS "
        "'The first month this brand billed AGAIN after going 90+ days dark on this product "
        "(a gap of 3 or more months with no usage-fee line). Detected from Stripe billing "
        "months — the only continuous activity signal we hold. NOT itself a claim: see "
        "reactivation_qualifies.'"
    )
    op.execute(
        f"COMMENT ON COLUMN ps_product_subscriptions.reactivation_qualifies IS "
        f"'Does this reactivation earn us anything? TRUE only when it happened AFTER "
        f"{PUSH_RESTART} (when PS restarted the China push — we claim reactivations we caused, "
        f"not ones that happened on their own) AND the brand is a FLAT-FEE brand "
        f"(''{FLAT_FEE_BUCKET}''), where nobody is earning an ongoing commission. A brand on an "
        f"active 10%% rev-share to another partner can NEVER be won back this way — someone is "
        f"still being paid on it.'"
    )

    # ── claimability, per brand x product x MONTH ───────────────────────────
    op.execute("ALTER TABLE ps_monthly_earnings ADD COLUMN IF NOT EXISTS is_claimable BOOLEAN")
    op.execute("ALTER TABLE ps_monthly_earnings ADD COLUMN IF NOT EXISTS claim_basis TEXT")
    allowed = ", ".join(f"'{b}'" for b in _BASIS)
    op.execute(
        "ALTER TABLE ps_monthly_earnings DROP CONSTRAINT IF EXISTS ck_earnings_claim_basis"
    )
    op.execute(
        f"""
        ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_claim_basis CHECK (
            claim_basis IS NULL OR claim_basis IN ({allowed})
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.is_claimable IS "
        "'Are we owed on THIS brand, on THIS product, in THIS month? Not a brand-level fact: the "
        "same brand can be unclaimable on Connect and claimable on Boost in the same month, and "
        "can become claimable on Connect partway through the year by reactivating. Anything "
        "coarser rounds one state into another, and each rounding is money.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_monthly_earnings.claim_basis IS "
        "'WHY this row is (or is not) claimable. boost_all_brands = Boost is ours even on "
        "excluded brands (Tim/Ali, verbal). rule_a_post_takeover = onboarded after the "
        "2025-11-18 freeze. rule_b_december = onboarded before it but billing from Dec 2025, "
        "because we run the CS. reactivation_flat_fee = went 90 days dark and came back after "
        "2025-11-01, on a flat-fee brand where nobody else earns. A number nobody can explain is "
        "a number nobody can collect — every claimable dollar names its rule.'"
    )

    # ── what Wayward owes us and is not paying ──────────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_unclaimed")
    op.execute(
        """
        CREATE VIEW lens_ps_unclaimed AS
        SELECT
            e.claim_basis,
            e.product_id,
            count(DISTINCT e.wayward_brand_id)                       AS brands,
            count(*)                                                 AS brand_months,
            round(sum(e.usage_collected), 2)                         AS usage_collected,
            round(sum(e.ps_gross_owed), 2)                           AS ps_owed,
            round(sum(e.ps_actually_paid), 2)                        AS ps_paid,
            round(sum(e.ps_gross_owed) - sum(e.ps_actually_paid), 2) AS SHORTFALL,
            count(*) FILTER (WHERE e.ps_rate_pct IS NULL)            AS rows_with_unknown_rate
        FROM ps_monthly_earnings e
        WHERE e.is_claimable
        GROUP BY 1, 2
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_unclaimed IS "
        "'What Wayward owes Project Silk, minus what it has actually paid, on the brand-months "
        "we are entitled to — grouped by the RULE that entitles us, so every dollar in the "
        "shortfall can be defended by name. ps_owed is the GROSS (10/6/3 of collected usage "
        "fees); partners are paid by us out of it, not by Wayward. Check rows_with_unknown_rate "
        "before quoting the total: those rows contributed NOTHING, so the figure is a floor, not "
        "a total.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_unclaimed TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_unclaimed")
    op.execute(
        "ALTER TABLE ps_monthly_earnings DROP CONSTRAINT IF EXISTS ck_earnings_claim_basis"
    )
    op.execute("ALTER TABLE ps_monthly_earnings DROP COLUMN IF EXISTS claim_basis")
    op.execute("ALTER TABLE ps_monthly_earnings DROP COLUMN IF EXISTS is_claimable")
    op.execute(
        "ALTER TABLE ps_product_subscriptions DROP COLUMN IF EXISTS reactivation_qualifies"
    )
    op.execute("ALTER TABLE ps_product_subscriptions DROP COLUMN IF EXISTS reactivated_at")
