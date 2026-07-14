# foundry: kind=migration domain=client-intelligence-platform
"""cip_60: deal_source. Whose BOOK a brand is in, which is not the same as who gets PAID.

TWO FACTS, ONE COLUMN — the mistake this fixes
----------------------------------------------
Wayward's onboarding feed carries two separate referral fields, and they are not duplicates.
They stack:

    deal_source      "China Referral - Tim"      <- WHOSE BOOK. The umbrella relationship.
    referral_source  "referral(xq)"              <- WHO ACTUALLY REFERRED. Earns a cut.

The cross-tab makes the distinction unarguable:

    China Referral - Tim  x  (self-serve)     268 brands   ours, no partner, PS keeps all 10%
    China Referral - Tim  x  referral(xq)      50 brands   ours, but Kerry referred -> Kerry
                                                           earns out of OUR 10%
    China Referral - Tim  x  referral(Adina)   68 brands   ours, Adina referred
    China Referral - Eric x  (self-serve)     179 brands   Eric's book
    China Referral - Eric x  referral(xq)     101 brands   Eric's book, Kerry referred
    Other                 x  (self-serve)     261 brands   not a China referral at all

Collapsing these into one column loses the 50 brands that are OURS but owe a partner a share —
which is exactly the population the whole partner-split model exists to describe ("we split the
10% total"). So deal_source gets its own column, kept VERBATIM as Wayward stated it, and
partner_of_record continues to mean only one thing: who we pay.

deal_source is EVIDENCE (Wayward said it). partner_of_record is a DECISION (we concluded it).
Same discipline as everywhere else in this schema: they do not get to overwrite each other.

Revision ID: cip_60_deal_source
Revises: cip_59_identity_not_null
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_60_deal_source"
down_revision: str | Sequence[str] | None = "cip_59_identity_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ps_partner_credit ADD COLUMN IF NOT EXISTS deal_source TEXT")
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.deal_source IS "
        "'WHOSE BOOK this brand is in, verbatim from Wayward''s onboarding feed: "
        "''China Referral - Tim'' (431 brands — ours), ''China Referral - Eric'' (389), "
        "''China Referral - Adina'' (70), ''China Referral - Shallow'' (5), or ''Other'' (451, "
        "not a China referral at all). This is EVIDENCE — what Wayward said — and it is NOT the "
        "same fact as partner_of_record, which is who we PAY. A brand can be in Tim''s book AND "
        "owe Kerry a referral cut; 50 brands are exactly that. Collapsing the two would erase "
        "the entire population the partner-split model exists for.'"
    )
    op.execute(
        "ALTER TABLE ps_partner_credit ADD COLUMN IF NOT EXISTS deal_source_raw TEXT"
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.deal_source_raw IS "
        "'The referral_source free text exactly as Wayward stored it — ''referral(xq)'', "
        "''other(朋友推荐)'', ''referral(friend)''. Kept raw and never cleaned, because the "
        "canonicalisation of this field is where partners get merged or lost: ''xq'' IS Xueqiu "
        "IS 雪球 IS Snowball IS Kerry, and a canonicaliser that missed it credited 150 brands to "
        "a partner who does not exist. If the mapping is ever wrong again, the truth is still "
        "here.'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_partner_credit_deal_source "
        "ON ps_partner_credit (tenant_id, deal_source)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ps_partner_credit_deal_source")
    op.execute("ALTER TABLE ps_partner_credit DROP COLUMN IF EXISTS deal_source_raw")
    op.execute("ALTER TABLE ps_partner_credit DROP COLUMN IF EXISTS deal_source")
