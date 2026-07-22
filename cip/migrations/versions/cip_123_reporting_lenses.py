# foundry: kind=migration domain=client-intelligence-platform
"""cip_123: reporting lenses G2 + G3 for the Project Silk reporting app.

The reporting frontend (reports.project-silk.com) reads CIP only through the
lens_ps_* surface via ps_reporting_reader (cip_120) — never base tables. Two
Sprint-1 screens route at base tables the reader can't SELECT, so each needs a
PS-scoped lens + grant (REPORTING-REBUILD-PLAN §6.1):

  G2  lens_ps_cash_ledger   — Payments-In (§7.4): what Wayward paid us, per brand,
        with the fee breakdown + the rev-share stated/computed/variance. Over
        ps_payment_events (the manual "Jake" payment feed), verdict-tagged.
  G3  lens_ps_open_invoices — Collections (§7.3): the billed-but-not-collected
        chase list. Over ps_stripe_invoices, status IN ('open','uncollectible')
        only (excludes the 12,267 "paid"-with-remaining anomaly and 1,282 void),
        with amount_remaining, aging bucket, days_outstanding, hosted_invoice_url,
        an is_uncollectible flag, verdict-tagged.

(G8 "freshness heartbeat" needed no migration — lens_ps_source_freshness already
carries mode / status / hours_since / freshness.)

Both views are ADDITIVE and run as owner, so nested base-table/lens reads resolve
under the owner's privileges; the reader needs SELECT on the top-level lens only
(same as cip_120). downgrade() DROPs them. Verified live 2026-07-22: open_invoices
= 1,776 rows / $1,198,878 remaining / 8 uncollectible; cash_ledger = 2,271 rows /
$977,281 paid.

Revision ID: cip_123_reporting_lenses
Revises: cip_122_ps_staff_junk

(Revision id kept short — alembic_version_cip is VARCHAR(32).)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_123_reporting_lenses"
down_revision: str | Sequence[str] | None = "cip_122_ps_staff_junk"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_LENSES = ("lens_ps_cash_ledger", "lens_ps_open_invoices")


def upgrade() -> None:
    # G2 — Payments-In ledger (what Wayward paid us), verdict-tagged.
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_cash_ledger AS
        SELECT
            pe.wayward_brand_id,
            pe.brand_name,
            v.verdict,
            pe.payment_date,
            pe.usage_fees_paid,
            pe.commission_fees_paid,
            pe.saas_fees_paid,
            pe.cc_processing_fees_paid,
            pe.total_amount_paid,
            pe.rev_share_stated,
            pe.rev_share_computed,
            pe.rev_share_variance,
            pe.months_from_signup,
            pe.source_ref
        FROM ps_payment_events pe
        LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = pe.wayward_brand_id;
        """
    )

    # G3 — Collections chase list: billed-but-not-collected (open + uncollectible).
    op.execute(
        """
        CREATE OR REPLACE VIEW lens_ps_open_invoices AS
        SELECT
            i.wayward_brand_id,
            v.verdict,
            i.customer_name,
            i.invoice_number,
            i.status,
            i.amount_due,
            i.amount_paid,
            i.amount_remaining,
            i.total,
            i.currency,
            i.hosted_invoice_url,
            i.created_at_stripe,
            i.due_date,
            (i.status = 'uncollectible') AS is_uncollectible,
            GREATEST(0, (CURRENT_DATE - COALESCE(i.due_date::date, i.created_at_stripe::date))) AS days_outstanding,
            CASE
                WHEN COALESCE(i.due_date, i.created_at_stripe) IS NULL THEN 'unknown'
                WHEN (CURRENT_DATE - COALESCE(i.due_date::date, i.created_at_stripe::date)) >= 180 THEN '6+ months'
                WHEN (CURRENT_DATE - COALESCE(i.due_date::date, i.created_at_stripe::date)) >= 90  THEN '3-6 months'
                WHEN (CURRENT_DATE - COALESCE(i.due_date::date, i.created_at_stripe::date)) >= 30  THEN '1-3 months'
                ELSE '0-1 months'
            END AS aging_bucket
        FROM ps_stripe_invoices i
        LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = i.wayward_brand_id
        WHERE i.status IN ('open', 'uncollectible');
        """
    )

    for lens in _LENSES:
        op.execute(f'GRANT SELECT ON "{lens}" TO {_READER};')
    print(f"cip_123: created + granted {len(_LENSES)} reporting lenses to {_READER}")


def downgrade() -> None:
    for lens in _LENSES:
        op.execute(f'DROP VIEW IF EXISTS "{lens}";')
