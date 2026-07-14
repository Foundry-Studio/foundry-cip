# foundry: kind=migration domain=client-intelligence-platform
"""cip_68: you cannot take a brand somebody else is being paid on. On ANY product.

TIM CAUGHT THIS (2026-07-13): "check your heavy producers — you listed Roborock just now, and it's
excluded specifically under Eric 10%. your logic is STILL wrong."

He is right, and it is two distinct bugs stacked on each other.

BUG 1 — I failed to generalise the principle
--------------------------------------------
Tim stated the rule for REACTIVATION: "these must ONLY be flat-fee era, not 10% paid to other
brands (the heavy producers or other excluded on contract)." The underlying principle is not about
reactivation at all — it is:

    YOU CANNOT TAKE A BRAND THAT SOMEBODY ELSE IS ACTIVELY BEING PAID ON.

I applied it to reactivation and left BOOST as a blanket "ours on every Chinese brand, excluded or
not". So we were claiming Boost revenue on brands where Eric, Adina, Jeremy, Shallow or OpenLight
still collect an ongoing 10%. Roborock is the clearest case: Heavy Producer bucket, referrer
Eric/Adina, deal_type=rev_share, and we were invoicing its Boost fees.

    Heavy Producer      37 brands   $772.28
    Eric Rev Share      53 brands   $279.30
    Jeremy / Caspar     15 brands    $60.40
    OpenLight            3 brands    $21.91
    Shallow              6 brands     $2.89
    -----------------------------------------
                                  $1,136.78  of Boost we were wrongly claiming

BUG 2 — a brand can be in TWO buckets, and the winnable one was winning
-----------------------------------------------------------------------
ps_excluded_brands holds 817 rows for 807 distinct brands. TEN brands sit in two buckets at once:

    Roborock    Eric Rev Share  +  Heavy Producer     (both hands-off — harmless here)
    Nexiepoch   Eric Flat Fee   +  Shallow            <-- winnable AND hands-off
    YOLIX       Eric Flat Fee   +  Shallow            <-- winnable AND hands-off
    Opuntia, ZOOSIXX, QGGQDD, Showitty   same shape
    BOOJO       Heavy Producer  +  Shallow
    WeCreat     Heavy Producer  +  Jeremy / Caspar
    HLTPRO      Heavy Producer  +  Shallow

The reactivation test was `x.bucket = 'Eric Flat Fee Brands'` over a LEFT JOIN. For Nexiepoch and
YOLIX that matched the FLAT-FEE row and never saw the SHALLOW row — so a brand Shallow is still
earning on qualified as a flat-fee win-back. An equality test against a multi-valued relation is
always wrong; it silently picks whichever row it meets first.

THE FIX — most restrictive wins
-------------------------------
Exclusion status is computed per BRAND, over ALL its bucket rows:

    someone_else_earning := EXISTS a bucket in
        (Eric Rev Share Brands, Heavy Producer Brands, 'Jeremy  Caspar', Shallow, OpenLight,
         OceanWing)
    is_winnable          := on the list AND has an 'Eric Flat Fee Brands' bucket
                            AND NOT someone_else_earning

If ANY bucket says another partner still earns, the brand is hands-off — on Connect, on Boost, and
for reactivation alike. Nobody's revenue gets taken out from under them by a rule we wrote.

Note 'Jeremy  Caspar' carries TWO spaces in the source data. Matching it with one space silently
excludes 34 brands from the hands-off set — exactly the kind of thing that turns into an invoice.

Revision ID: cip_68_someone_else_earning
Revises: cip_67_manual_review_authority
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_68_someone_else_earning"
down_revision: str | Sequence[str] | None = "cip_67_manual_review_authority"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# Buckets where a prior partner STILL COLLECTS an ongoing commission. Hands off, every product.
# NB: 'Jeremy  Caspar' has TWO spaces in the source data.
HANDS_OFF = (
    "Eric Rev Share Brands",
    "Heavy Producer Brands",
    "Jeremy  Caspar",
    "Shallow",
    "OpenLight",
    "OceanWing",
)
WINNABLE = "Eric Flat Fee Brands"   # Eric was paid ONCE. Nobody earns ongoing.


def upgrade() -> None:
    hands_off = ", ".join(f"'{b}'" for b in HANDS_OFF)

    op.execute("DROP VIEW IF EXISTS lens_ps_exclusion_status")
    op.execute(
        f"""
        CREATE VIEW lens_ps_exclusion_status AS
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            (x.buckets IS NOT NULL)                                   AS is_excluded,
            x.buckets,
            COALESCE(x.someone_else_earning, false)                   AS someone_else_earning,
            -- winnable = on the list, flat-fee, and NOBODY else is earning on it
            COALESCE(x.has_flat_fee, false)
                AND NOT COALESCE(x.someone_else_earning, false)       AS is_winnable,
            -- ours to take on any product: never listed at all, OR listed but winnable
            (x.buckets IS NULL)
                OR (COALESCE(x.has_flat_fee, false)
                    AND NOT COALESCE(x.someone_else_earning, false))  AS takeable
        FROM ps_brands b
        LEFT JOIN (
            SELECT wayward_brand_id,
                   string_agg(DISTINCT bucket, ' + ' ORDER BY bucket)      AS buckets,
                   bool_or(bucket IN ({hands_off}))                        AS someone_else_earning,
                   bool_or(bucket = '{WINNABLE}')                          AS has_flat_fee
            FROM ps_excluded_brands
            WHERE wayward_brand_id IS NOT NULL
            GROUP BY wayward_brand_id
        ) x ON x.wayward_brand_id = b.wayward_brand_id
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_exclusion_status IS "
        "'Exclusion status per BRAND, aggregated over ALL its bucket rows — because ten brands sit "
        "in TWO buckets at once and an equality test against a multi-valued relation silently picks "
        "whichever row it meets first. Nexiepoch and YOLIX are BOTH ''Eric Flat Fee'' (winnable) AND "
        "''Shallow'' (someone still earns), and the old test matched the flat-fee row and handed us "
        "a brand Shallow is being paid on. MOST RESTRICTIVE WINS: if any bucket says another partner "
        "still earns, the brand is hands-off on EVERY product.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_exclusion_status.someone_else_earning IS "
        "'A prior partner still collects an ongoing commission on this brand (Eric Rev Share, Heavy "
        "Producer, Jeremy/Caspar, Shallow, OpenLight, OceanWing). Tim''s governing principle: YOU "
        "CANNOT TAKE A BRAND SOMEBODY ELSE IS ACTIVELY BEING PAID ON — not on Connect, not on Boost, "
        "not by reactivation.'"
    )
    op.execute(
        "COMMENT ON COLUMN lens_ps_exclusion_status.takeable IS "
        "'TRUE when the brand is either not excluded at all, or excluded but WINNABLE (Eric flat-fee, "
        "and nobody else earning). This — not ''is it Chinese'' — is the gate on Boost and on "
        "reactivation. Boost being a net-new product does NOT entitle us to revenue on a brand "
        "another partner is still being paid for.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_exclusion_status TO {r}")

    # Reactivation must respect it too — recompute the flag over ALL buckets.
    op.execute(
        """
        UPDATE ps_product_subscriptions s
           SET reactivation_qualifies = (
                s.reactivated_at >= DATE '2025-11-01'
                AND st.is_winnable
           )
          FROM lens_ps_exclusion_status st
         WHERE st.wayward_brand_id = s.wayward_brand_id
           AND s.reactivated_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_exclusion_status")
