# foundry: kind=migration domain=client-intelligence-platform
"""cip_84: admit the two LEGAL-RECORD signals. They outrank everything we were guessing at.

External research came back and it works. First result:

    Acupoint -> WNG BRANDS LLC, 11615 Forest Central Drive, Dallas, Texas
    Amazon "Detailed Seller Information" AND USPTO trademark #97782524, agreeing.

Neither of those facts is in our database, and neither could ever be derived from it. They are
PUBLIC LEGAL RECORDS:

    amazon_seller_entity    The INFORM Consumers Act (US, 2023) compels Amazon to verify and
                            publish the business name and registered address of every high-volume
                            third-party seller. This is a legally-mandated disclosure about the
                            exact entity we are trying to identify.

    uspto_trademark_owner   Amazon Brand Registry requires a registered trademark. To own a US
                            trademark, a Chinese company must file under its real legal entity.
                            Shenzhen Street Cat Technology Co., Ltd. cannot hide behind a Delaware
                            LLC on the trademark register.

WHY THESE ARE 'CONFIRMED' AND NOT MERELY 'STRONG'
-------------------------------------------------
Every signal we had before this was a PROXY: a mailbox domain, a phone prefix, a name that looked
like pinyin. Half a day of website crawling produced a 1% hit rate, because a Chinese seller running
a US-facing Shopify store publishes nothing. Meanwhile a US LLC in a footer proves nothing at all —
Chinese sellers register them by the thousand, and we found the Wyoming mail-drops to prove it.

These two are not proxies. They name the entity, under legal compulsion, in public.

BOTH DIRECTIONS
---------------
They point either way, and that is the point. `WNG BRANDS LLC, Dallas, Texas` clears a brand as
firmly as `SHENZHENWEIERCHUANGXINYOUXIANGONGSI` condemns one. The first finding we received was a
NOT_CHINA — which is exactly what an honest instrument looks like.

Revision ID: cip_84_research_signals
Revises: cip_83_brand_reality
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_84_research_signals"
down_revision: str | Sequence[str] | None = "cip_83_brand_reality"
branch_labels = None
depends_on = None

_BASE = (
    "on_exclusion_list", "wayward_country_cn", "cjk_in_name", "chinese_email_domain",
    "chinese_partner", "eric_sheet", "manual_review", "wayward_country_other",
    "phone_+86", "shared_owner_mailbox", "cn_mobile_handle", "qq_handle",
    "cn_company_name_pinyin", "pinyin_name_in_email", "pinyin_contact_name",
)
_NEW = ("amazon_seller_entity", "uspto_trademark_owner")


def _check(values: tuple[str, ...]) -> str:
    return "CHECK (signal = ANY (ARRAY[" + ", ".join(f"'{v}'" for v in values) + "]::text[]))"


def upgrade() -> None:
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _check(_BASE + _NEW)
    )
    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.signal IS "
        "'WHAT was observed. "
        "*** amazon_seller_entity and uspto_trademark_owner are LEGAL RECORDS, not proxies. *** "
        "Amazon is compelled by the INFORM Consumers Act to publish a high-volume seller''s business "
        "name and registered address; the USPTO register names the true owner of the trademark that "
        "Brand Registry requires. Both name the ENTITY, under legal compulsion, in public — and both "
        "point in EITHER direction. Everything else in this table is a proxy: a mailbox domain, a "
        "phone prefix, a name that looks like pinyin. "
        "A Chinese personal name (pinyin_name_in_email, pinyin_contact_name) is a HINT, never a "
        "verdict — a Chinese NAME is not a Chinese COMPANY. BruMate is American; Bob and Brad is "
        "Chinese. Those signals exist to route a brand to a HUMAN. "
        "A US LLC in a website footer proves NOTHING: Chinese sellers register Delaware and Wyoming "
        "shells by the thousand.'"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ps_nationality_signals WHERE signal = ANY (ARRAY["
        + ", ".join(f"'{v}'" for v in _NEW)
        + "]::text[])"
    )
    op.execute("ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check")
    op.execute(
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        + _check(_BASE)
    )
