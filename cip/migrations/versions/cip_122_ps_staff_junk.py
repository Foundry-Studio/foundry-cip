# foundry: kind=migration domain=client-intelligence-platform
"""cip_122: count project-silk.com staff mailboxes as JUNK in brand-reality.

WHY (Tim, 2026-07-20): a live Stripe customer sheila@project-silk.com ("sheila@project-
skill", a typo test from new staff member Sheila) syncs in from WAYWARD's Stripe, which
we cannot delete (not our account). lens_ps_brand_reality already flags staff-mailbox
test brands as JUNK — but only @wayward / @artica. project-silk.com is OUR OWN staff
domain, so it belongs in that same list. This classifies sheila (and any future PS staff
test signup) as JUNK instead of GHOST, so reports can filter JUNK cleanly without dropping
real un-engaged brands. Durable: the lens re-computes each read, so it survives the
re-sync we can't stop at source.

Only change: the staff_mailbox regex `@(wayward|artica)` -> `@(wayward|artica|project-silk)`.
No column changes, so the 2 dependents (china_chase_list, china_companies) are preserved.

Revision ID: cip_122_ps_staff_junk
Revises: cip_121_wechat_handle_signal
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_122_ps_staff_junk"
down_revision: str | Sequence[str] | None = "cip_121_wechat_handle_signal"
branch_labels = None
depends_on = None

_STAFF_NEW = "wayward|artica|project-silk"
_STAFF_OLD = "wayward|artica"


def _lens(staff_domains: str) -> str:
    return f"""
CREATE OR REPLACE VIEW lens_ps_brand_reality AS
 WITH ev AS (
         SELECT b.wayward_brand_id,
            b.brand_name,
            (EXISTS ( SELECT 1
                   FROM ps_stripe_invoice_lines m
                  WHERE m.wayward_brand_id = b.wayward_brand_id AND m.is_ps_base AND m.product_id IS NOT NULL AND m.billing_month IS NOT NULL)) AS ever_billed,
            (EXISTS ( SELECT 1
                   FROM ps_brand_observations o
                  WHERE o.wayward_brand_id = b.wayward_brand_id AND o.source_system LIKE 'slack:%')) AS wayward_onboarded_them,
            (EXISTS ( SELECT 1
                   FROM ps_product_subscriptions s
                  WHERE s.wayward_brand_id = b.wayward_brand_id)) AS has_subscription,
            (EXISTS ( SELECT 1
                   FROM ps_brand_contacts ct
                  WHERE ct.wayward_brand_id = b.wayward_brand_id)) AS has_contact,
            (EXISTS ( SELECT 1
                   FROM ps_excluded_brands x
                  WHERE x.wayward_brand_id = b.wayward_brand_id)) AS on_a_frozen_list,
            b.seen_in_eric_sheets AS on_eric_sheet,
            (EXISTS ( SELECT 1
                   FROM ps_stripe_customers s
                  WHERE s.wayward_brand_id = b.wayward_brand_id AND s.email ~* '@({staff_domains})\\.'::text)) AS staff_mailbox,
            (lower(btrim(COALESCE(b.brand_name, ''::text))) = ANY (ARRAY['1'::text, 'none'::text, 'generic'::text, 'brand'::text, 'brand 2'::text, 'brand co'::text, 'brand test'::text, 'test'::text, 'c'::text, 'country'::text, 'n/a'::text, 'na'::text, '-'::text, '.'::text, 'null'::text, 'x'::text, 'acme'::text, 'adore'::text, 'adores'::text, 'brand_test_2'::text, '1234'::text, '777'::text])) OR b.brand_name ~* '^(test|brand_test|demo|sample)'::text OR b.brand_name IS NULL OR btrim(b.brand_name) = ''::text AS placeholder_name
           FROM ps_brands b
        )
 SELECT wayward_brand_id,
    brand_name,
    ever_billed,
    wayward_onboarded_them,
    has_subscription,
    has_contact,
    on_a_frozen_list,
    on_eric_sheet,
    staff_mailbox,
    placeholder_name,
        CASE
            WHEN ever_billed OR wayward_onboarded_them OR has_subscription OR has_contact OR on_a_frozen_list OR on_eric_sheet THEN 'REAL'::text
            WHEN staff_mailbox OR placeholder_name THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality
   FROM ev
"""


def upgrade() -> None:
    op.execute(_lens(_STAFF_NEW))


def downgrade() -> None:
    op.execute(_lens(_STAFF_OLD))
