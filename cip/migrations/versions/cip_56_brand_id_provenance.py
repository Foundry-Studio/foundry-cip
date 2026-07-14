# foundry: kind=migration domain=client-intelligence-platform
"""cip_56: brand_id_source. HOW we know a brand's identity, not just that we do.

THE PROBLEM THIS PREVENTS
-------------------------
cip_55 made wayward_brand_id the identity — a PRIMARY KEY with 12 FKs pointing at it. Good.
But the backfill that FILLS it draws from sources of very different strength:

    Wayward stamped customer.metadata.brandId   -> a FACT. Wayward's own record.
    another Stripe customer, same email, has one -> strong, and still Wayward-sourced.
    the onboarding feed knows that brand's email -> strong, and still Wayward-sourced.
    the name looks like the email's local part   -> a GUESS. Nothing more.

Written into one column with no provenance, all four become indistinguishable the moment the
UPDATE commits. A guess acquires the authority of a fact by sitting in the same cell, and no
later reader — human or agent — can tell which is which. That is precisely the failure the
facts-vs-conclusions architecture exists to prevent (ps_brand_observations records source_system
and source_ref for exactly this reason), and the identity column was quietly exempt from it.

It matters here more than anywhere else, because identity is now UPSTREAM OF ALL MONEY. A wrong
brand id does not produce an error. It produces a confident number attributed to the wrong brand
— which is worse, because it survives review.

So: every filled identity says HOW it was filled. Unknown stays NULL, and NULL still means
"we do not know" — it must never become a number.

WHAT THIS DOES NOT DO
---------------------
It does not fill anything. It does not decide anything. It adds the field that makes the fill
honest, and a lens that shows how much money is resting on an inference rather than a fact.

Revision ID: cip_56_brand_id_provenance
Revises: cip_55_brand_master
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_56_brand_id_provenance"
down_revision: str | Sequence[str] | None = "cip_55_brand_master"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

# Ordered strongest -> weakest. The ONLY legal values.
_SOURCES = (
    "stripe_metadata",     # Wayward stamped customer.metadata.brandId. Authoritative.
    "stripe_email_match",  # another Stripe customer w/ same email carries a brandId.
    "slack_feed_email",    # the brand's email, from the onboarding feed.
    "payment_report",      # Jake's monthly report carried BRAND_ID directly.
    "name_match",          # INFERRED from a name. Never let this drive money unreviewed.
)

_TABLES = ("ps_stripe_invoices", "ps_stripe_invoice_lines", "cip_clients")


def upgrade() -> None:
    allowed = ", ".join(f"'{s}'" for s in _SOURCES)

    for tbl in _TABLES:
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS brand_id_source TEXT")

        # Everything already populated got there from Stripe's own customer metadata at
        # ingest time (ps_stripe_*) or from the brand id the source system carried
        # (cip_clients). Record that, rather than leaving history unattributed.
        seed = (
            "stripe_metadata" if tbl.startswith("ps_stripe") else "payment_report"
        )
        op.execute(
            f"""
            UPDATE {tbl} SET brand_id_source = '{seed}'
             WHERE wayward_brand_id IS NOT NULL AND brand_id_source IS NULL
            """
        )
        op.execute(
            f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS ck_{tbl}_brand_id_source"
        )
        op.execute(
            f"""
            ALTER TABLE {tbl} ADD CONSTRAINT ck_{tbl}_brand_id_source CHECK (
                (wayward_brand_id IS NULL  AND brand_id_source IS NULL)
             OR (wayward_brand_id IS NOT NULL AND brand_id_source IN ({allowed}))
            )
            """
        )
        op.execute(
            f"COMMENT ON COLUMN {tbl}.brand_id_source IS "
            f"'HOW we know this brand''s identity. Identity is UPSTREAM OF ALL MONEY, so a "
            f"wrong brand id does not raise an error — it produces a confident number "
            f"attributed to the wrong brand, which survives review. Strongest to weakest: "
            f"stripe_metadata (Wayward stamped customer.metadata.brandId — a fact) > "
            f"stripe_email_match / slack_feed_email / payment_report (Wayward-sourced, strong) > "
            f"name_match (INFERRED — never let it drive money unreviewed). The CHECK constraint "
            f"makes it impossible to record an identity without saying where it came from.'"
        )

    # How much money is resting on a fact, and how much on an inference?
    op.execute("DROP VIEW IF EXISTS lens_ps_identity_provenance")
    op.execute(
        """
        CREATE VIEW lens_ps_identity_provenance AS
        SELECT
            COALESCE(l.brand_id_source, '(unknown — no identity)') AS brand_id_source,
            CASE COALESCE(l.brand_id_source, 'zzz')
                WHEN 'stripe_metadata'    THEN 'fact'
                WHEN 'stripe_email_match' THEN 'strong'
                WHEN 'slack_feed_email'   THEN 'strong'
                WHEN 'payment_report'     THEN 'strong'
                WHEN 'name_match'         THEN 'INFERRED'
                ELSE 'UNKNOWN'
            END                                                    AS strength,
            count(DISTINCT l.wayward_brand_id)                     AS brands,
            count(*)                                               AS usage_fee_lines,
            round(sum(l.amount), 2)                                AS ps_base_billed,
            round(sum(l.amount) FILTER (WHERE l.invoice_status = 'paid'), 2)
                                                                   AS ps_base_collected
        FROM ps_stripe_invoice_lines l
        WHERE l.is_ps_base
        GROUP BY 1, 2
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_identity_provenance IS "
        "'The PS commission base, split by how confident we are that we know WHOSE it is. "
        "Read it before quoting any number to Wayward: money on an INFERRED or UNKNOWN identity "
        "is not claimable — not because we are not owed it, but because we cannot yet say which "
        "brand it belongs to, and therefore cannot run the China/exclusion tests on it. "
        "The UNKNOWN row is the size of the ask to Jake.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_identity_provenance TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_identity_provenance")
    for tbl in _TABLES:
        op.execute(
            f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS ck_{tbl}_brand_id_source"
        )
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS brand_id_source")
