# foundry: kind=migration domain=client-intelligence-platform
"""cip_100: split WeChat into wechat_id + wechat_phone on ps_brand_contacts (Tim, 2026-07-15).

Jake's WeChat data mixes two different identifiers in one column: WeChat HANDLES (`w2455623084`,
`lzwws25`) and phone NUMBERS (`18506677375`). They are different things — and a phone has
independent value (callable, and a Chinese mobile is a `phone_+86` nationality signal), so we keep
them apart rather than in one generic field:

  - `wechat` (existing, 0 rows populated) -> renamed `wechat_id`  (the handle)
  - new `wechat_phone`                                            (the WeChat-registered number)

`lens_ps_brand_contact_book` reads the old column, so it is dropped and recreated to expose both.

Revision ID: cip_100_wechat_id_and_phone
Revises: cip_99_comment_source_tables
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_100_wechat_id_and_phone"
down_revision: str | Sequence[str] | None = "cip_99_comment_source_tables"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")


def _contact_book(wechat_cols: str) -> str:
    return f"""
        CREATE VIEW lens_ps_brand_contact_book AS
        SELECT b.wayward_brand_id, b.brand_name,
               c.name, c.role, c.job_title, c.email, c.phone, {wechat_cols},
               c.is_primary, c.source_system, c.refreshed_at,
               st.is_excluded, st.is_winnable, st.someone_else_earning,
               s.dormant_since, s.reactivated_at, s.product_id
        FROM ps_brands b
        LEFT JOIN ps_brand_contacts c ON c.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN ps_product_subscriptions s ON s.wayward_brand_id = b.wayward_brand_id
    """


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_contact_book")
    op.execute("ALTER TABLE ps_brand_contacts RENAME COLUMN wechat TO wechat_id")
    op.execute("ALTER TABLE ps_brand_contacts ADD COLUMN wechat_phone text")
    op.execute("COMMENT ON COLUMN ps_brand_contacts.wechat_id IS "
               "'WeChat handle/username (e.g. w2455623084, lzwws25). NOT a phone — that is "
               "wechat_phone. Renamed from wechat in cip_100.'")
    op.execute("COMMENT ON COLUMN ps_brand_contacts.wechat_phone IS "
               "'Phone number the WeChat account is registered under (often a mobile you can also "
               "call). A +86 value corroborates China. Kept separate from the general phone column.'")
    op.execute(_contact_book("c.wechat_id, c.wechat_phone"))
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_contact_book TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_brand_contact_book")
    op.execute("ALTER TABLE ps_brand_contacts DROP COLUMN wechat_phone")
    op.execute("ALTER TABLE ps_brand_contacts RENAME COLUMN wechat_id TO wechat")
    op.execute(_contact_book("c.wechat"))
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_brand_contact_book TO {r}")
