# foundry: kind=test domain=client-intelligence-platform
"""Smoke tests for ``apply_tenant_context`` (M2 §4.4 binding).

Real Postgres SET LOCAL behavior is exercised by the conformance harness
(test_tenant_scoping.py + test_post_commit_rls_isolation.py) against a
testcontainer. These tests cover the parameterized-SQL contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cip.integration_mesh.tenant_context import apply_tenant_context


def test_executes_set_local_with_uuid_str() -> None:
    db = MagicMock()
    tid = uuid4()
    apply_tenant_context(db, tid)

    db.execute.assert_called_once()
    args, _ = db.execute.call_args
    sql_arg, params = args[0], args[1]
    sql_str = str(sql_arg)
    assert "SET LOCAL app.current_tenant" in sql_str
    assert ":tid" in sql_str
    # UUID is cast to str for Postgres GUC.
    assert params == {"tid": str(tid)}


def test_uses_text_construct_not_raw_string() -> None:
    """Bind value goes through SQLAlchemy text() — no f-string injection."""
    db = MagicMock()
    apply_tenant_context(db, uuid4())
    sql_arg = db.execute.call_args[0][0]
    # text() instances expose .compile()
    assert hasattr(sql_arg, "compile")
