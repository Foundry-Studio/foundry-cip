# foundry: kind=migration domain=client-intelligence-platform
"""cip_151 - lens_ps_days_to_pay: the earned-month -> paid-date lag (RDL, #43 residual).

The money screens need "average days to pay" (ClaimVM.avgDaysToPay, CashVM.in.avgDaysToPay, the P4a Company
KPIs): how long after PS earns a fee does Wayward actually pay it. The trust batch did not build it (VERIFIED
ABSENT 2026-08-01). The bridge is real and additive:

  ps_payment_events(payment_date, stripe_invoice_ids)  ->  ps_stripe_invoice_lines(stripe_invoice_id,
  billing_month)

A Wayward payment (ps_payment_events) carries the Stripe invoice id(s) it settled; each invoice line carries
its billing_month (the earned month). days_to_pay = payment_date - billing_month, in days. stripe_invoice_ids
is one id per row in the data seen, but is split defensively (comma list) so a multi-invoice payment fans out
to one row per invoice it settled. The earned month for an invoice = the earliest line billing_month.

ROW-GRAIN + NEUTRAL: one row per (payment, invoice) with a signed days_to_pay. It deliberately does NOT floor
or window - a KPI consumer aggregates with a sane filter, e.g. avg(days_to_pay) WHERE days_to_pay BETWEEN 0
AND 365, so prepayments (negative) and stale-invoice matches (huge) never distort the headline. Per-brand and
per-month roll-ups fall out of the same rows.

Additive (new view + grants, no base-table change). Downgrade drops the view. Revision id <=32 (this = 19).

Revision ID: cip_151_days_to_pay
Revises: cip_150_natl_review_state
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_151_days_to_pay"
down_revision: str | Sequence[str] | None = "cip_150_natl_review_state"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_LENS = r"""
CREATE OR REPLACE VIEW lens_ps_days_to_pay AS
WITH invoice_earned AS (
    -- one earned (billing) month per Stripe invoice = the earliest line billing_month
    SELECT stripe_invoice_id, min(billing_month) AS billing_month
    FROM ps_stripe_invoice_lines
    WHERE billing_month IS NOT NULL
    GROUP BY stripe_invoice_id
),
paid AS (
    -- one row per (payment event, Stripe invoice it settled); split the id list defensively
    SELECT pe.wayward_brand_id,
           pe.brand_name,
           pe.payment_date,
           btrim(inv.id) AS stripe_invoice_id
    FROM ps_payment_events pe
    CROSS JOIN LATERAL unnest(string_to_array(pe.stripe_invoice_ids, ',')) AS inv(id)
    WHERE pe.stripe_invoice_ids IS NOT NULL
      AND btrim(pe.stripe_invoice_ids) <> ''
      AND pe.payment_date IS NOT NULL
      AND btrim(inv.id) <> ''
)
SELECT p.wayward_brand_id,
       p.brand_name,
       v.verdict,
       p.stripe_invoice_id,
       ie.billing_month,
       p.payment_date,
       (p.payment_date - ie.billing_month)::int AS days_to_pay
FROM paid p
JOIN invoice_earned ie ON ie.stripe_invoice_id = p.stripe_invoice_id
LEFT JOIN lens_ps_china_verdict v ON v.wayward_brand_id = p.wayward_brand_id;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_LENS)
    op.execute(f"GRANT SELECT ON lens_ps_days_to_pay TO {_READER};")
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_days_to_pay TO {role};")
    print("cip_151: lens_ps_days_to_pay created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_days_to_pay;")
