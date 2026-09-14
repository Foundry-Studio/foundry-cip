# foundry: kind=test domain=client-intelligence-platform
"""Wiring-drift guards for scripts/check_public_repo_guard.py.

Precedent: tests/test_fnd_s14_trailer.py's anti-drift test, which reads the
CI job's own grep patterns rather than restating them, so editing one side
without the other fails here instead of silently diverging. Same idea for
two things that would otherwise be easy to break independently:

  1. The pre-commit hook and the CI workflow both actually invoke this
     script (not some stale copy/rename).
  2. The guard's DENIED_PATH exemption (CIP-DIAG-102) names the SAME
     tenant UUID as the un-ignore line in .gitignore -- if these drift
     apart, either the guard blocks a file .gitignore already allows
     (annoying) or the guard allows something .gitignore still denies
     (the actual incident-shaped failure mode).
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts.check_public_repo_guard import _EXEMPT_TENANT_PATHS

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_precommit_config_invokes_the_guard_script() -> None:
    config = (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: python scripts/check_public_repo_guard.py --staged" in config
    assert "id: public-repo-guard" in config


def test_ci_workflow_invokes_the_guard_script() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "public-repo-guard.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/check_public_repo_guard.py" in workflow
    assert "--range" in workflow


def test_guard_exemption_matches_gitignore_unignore_line() -> None:
    gitignore = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    m = re.search(r"^!docs/tenants/([0-9a-fA-F-]{36})/\s*$", gitignore, re.MULTILINE)
    assert m, ".gitignore's docs/tenants/* un-ignore line not found in expected shape"
    gitignore_uuid = m.group(1)

    guard_uuids = {
        path.split("/")[2] for path in _EXEMPT_TENANT_PATHS
    }
    assert guard_uuids == {gitignore_uuid}, (
        "scripts/check_public_repo_guard.py's _EXEMPT_TENANT_PATHS names a "
        f"different tenant ({guard_uuids}) than .gitignore's un-ignore line "
        f"({gitignore_uuid!r}) -- these must stay in sync or the guard and "
        ".gitignore disagree about which tenant dir is exempt."
    )
