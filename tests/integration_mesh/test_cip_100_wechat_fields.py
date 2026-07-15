# foundry: kind=test domain=client-intelligence-platform
"""cip_100 — WeChat split into wechat_id + wechat_phone on ps_brand_contacts (Tim, 2026-07-15)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.requires_postgres
def test_wechat_columns_split(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'ps_brand_contacts'"
            )).fetchall()
        }
    assert "wechat_id" in cols, "wechat_id (the handle) must exist"
    assert "wechat_phone" in cols, "wechat_phone (the number) must exist"
    assert "wechat" not in cols, "old single wechat column should be renamed to wechat_id"


@pytest.mark.requires_postgres
def test_contact_book_exposes_both(seeded_engine: Engine) -> None:
    with seeded_engine.connect() as conn:
        # SELECT 0 rows: raises if the view doesn't expose these columns
        conn.execute(text("SELECT wechat_id, wechat_phone FROM lens_ps_brand_contact_book LIMIT 0"))
