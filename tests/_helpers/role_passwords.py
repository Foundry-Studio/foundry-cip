# foundry: kind=test-helper domain=client-intelligence-platform
"""Resolve a CIP role's password the SAME WAY the migration that created it does.

WHY THIS EXISTS. Each role-creating migration resolves its password through its
OWN ordered fallback chain, and the chains are not the same. cip_21 has two
links; the rest have one:

    cip_metabase_role          METABASE_DB_PASSWORD                     -> sentinel
    cip_metabase_project_silk  PROJECT_SILK_METABASE_DB_PASSWORD
                                 -> METABASE_DB_PASSWORD               -> sentinel
    cip_twenty_project_silk    TWENTY_PROJECT_SILK_DB_PASSWORD          -> sentinel
    cip_sync_reader            CIP_SYNC_READER_DB_PASSWORD              -> sentinel
    cip_query_reader           CIP_QUERY_READER_DB_PASSWORD             -> sentinel
    ps_reporting_reader        PS_REPORTING_READER_DB_PASSWORD          -> sentinel
    ps_reporting_writer        PS_REPORTING_WRITER_DB_PASSWORD          -> sentinel

Tests connecting as those roles were re-implementing the chain inline, and three
dropped cip_21's middle link, reading only the role-specific variable before
falling through to the sentinel.

That is invisible locally and fatal in CI. Locally no variable is set, so
migration and test both land on the sentinel and agree. CI sets
METABASE_DB_PASSWORD but not PROJECT_SILK_METABASE_DB_PASSWORD, so the migration
created the role with the CI password while the test connected with the
sentinel:

    FATAL: password authentication failed for user "cip_metabase_project_silk"

Four tests failed that way for the entire period CI was red. A test that only
passes when the environment is empty is not testing what it claims to.

Keying the chain by ROLE rather than by a caller-supplied variable name is the
point. A caller that passes the wrong variable, or applies one role's fallback
to another, reintroduces the bug in a new place. The first attempt at this fix
did exactly that: it applied cip_21's METABASE_DB_PASSWORD fallback to every
role and broke cip_query_reader, which has no such link.
"""
from __future__ import annotations

import os

# Matches the literal in every role-creating migration (cip_09/21/25/28/31/120/127).
TEST_PASSWORD_SENTINEL = "pytest_test_password_DO_NOT_USE_IN_PROD"  # noqa: S105

# role -> the env vars its migration reads, IN ORDER. Keep in sync with the
# migration; the migration is the source of truth, this only mirrors it.
_ROLE_ENV_CHAIN: dict[str, tuple[str, ...]] = {
    "cip_metabase_role": ("METABASE_DB_PASSWORD",),
    "cip_metabase_project_silk": (
        "PROJECT_SILK_METABASE_DB_PASSWORD",
        "METABASE_DB_PASSWORD",
    ),
    "cip_twenty_project_silk": ("TWENTY_PROJECT_SILK_DB_PASSWORD",),
    "cip_sync_reader": ("CIP_SYNC_READER_DB_PASSWORD",),
    "cip_query_reader": ("CIP_QUERY_READER_DB_PASSWORD",),
    "ps_reporting_reader": ("PS_REPORTING_READER_DB_PASSWORD",),
    "ps_reporting_writer": ("PS_REPORTING_WRITER_DB_PASSWORD",),
}


def role_password(role: str) -> str:
    """Password for ``role``, resolved exactly as its migration resolves it.

    Unknown roles fall back to the sentinel, which is what a fresh test database
    will have if no env var was set. Empty-string values are skipped, matching
    the migrations' ``or`` chaining rather than ``os.environ.get(name, default)``,
    which would accept "".
    """
    for name in _ROLE_ENV_CHAIN.get(role, ()):
        value = os.environ.get(name)
        if value:
            return value
    return TEST_PASSWORD_SENTINEL
