# foundry: kind=test domain=client-intelligence-platform
"""Applying a migration must not silence the application's logging.

``logging.config.fileConfig`` defaults ``disable_existing_loggers`` to True,
which disables every logger that exists when it runs. Migrations are applied
IN-PROCESS, and every module creates its logger at import time, so the default
means: run a migration, lose all logging for the rest of the process.

This was found the honest way. A retriever test asserting that a degraded
rerank emits a WARNING passed in isolation and failed in the full suite,
because a Postgres-backed test had applied migrations first. The assertion was
correct; the log record no longer existed.

The consequence outside tests is worse than inside. This repo's recurring
failure mode is defects that are detectable but undetected: CI red for four
months with nobody reading it, a feed outage that alerted 104 times and was
still missed, a knowledge corpus frozen since May. Disabling the loggers is
that failure mode at its root, because it removes the evidence for all the
others.
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_ini_fileconfig_does_not_disable_existing_loggers() -> None:
    """The real mechanism, exercised directly against the real alembic.ini."""
    name = "cip.test.canary.logger"
    canary = logging.getLogger(name)
    assert not canary.disabled

    ini = REPO_ROOT / "alembic.ini"
    assert ini.is_file(), f"expected alembic.ini at {ini}"

    logging.config.fileConfig(str(ini), disable_existing_loggers=False)
    assert not canary.disabled, (
        "fileConfig disabled a pre-existing logger; env.py must pass "
        "disable_existing_loggers=False"
    )


def test_env_py_passes_the_flag() -> None:
    """Source guard.

    The behavioural test above proves the flag works; this proves env.py
    actually passes it. Without this, someone could drop the argument and the
    test above would still pass while production logging died again.
    """
    src = (REPO_ROOT / "cip" / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "fileConfig(config.config_file_name)" not in src, (
        "env.py calls fileConfig without disable_existing_loggers=False, which "
        "silences every logger created before the migration ran"
    )
    assert "disable_existing_loggers=False" in src


def test_default_behaviour_is_genuinely_destructive() -> None:
    """Negative control: prove the default really does disable loggers.

    Without this, the two tests above could both pass against a version of
    Python or logging where the default changed, and we would be guarding
    against nothing.
    """
    name = "cip.test.canary.control"
    canary = logging.getLogger(name)
    canary.disabled = False

    ini = REPO_ROOT / "alembic.ini"
    logging.config.fileConfig(str(ini))  # default: disable_existing_loggers=True
    was_disabled = canary.disabled

    # Restore so this test cannot poison the rest of the session.
    logging.config.fileConfig(str(ini), disable_existing_loggers=False)
    canary.disabled = False

    assert was_disabled, (
        "the default no longer disables existing loggers; if that is genuinely true, "
        "the guard in env.py is now belt-and-braces rather than load-bearing "
        "and this test should be revisited"
    )
