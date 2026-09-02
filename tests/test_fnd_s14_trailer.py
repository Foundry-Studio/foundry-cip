"""FND-S14 commit-msg guard (scripts/check_fnd_s14_trailer.py).

The guard's whole value is that it accepts EXACTLY what the CI `trailer-check`
job accepts. If the two drift, the guard goes green locally and master still
turns red, which is the failure this was written to stop. So the last test
here reads the acceptance patterns straight out of `.github/workflows/test.yml`
and asserts they still match the ones the script uses.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.check_fnd_s14_trailer import has_trailer, main

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Accepted ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", ["A", "B", "C", "D"])
def test_accepts_every_declared_tier(tier: str) -> None:
    msg = f"fix(x): something\n\nBody.\n\nLocal-Verified: {tier} (evidence here)\n"
    assert has_trailer(msg)


def test_accepts_bypass() -> None:
    msg = "fix(x): something\n\nLocal-Verify-Bypass: hotfix, prod down\n"
    assert has_trailer(msg)


def test_accepts_trailer_alongside_other_trailers() -> None:
    """Co-Authored-By and friends must not displace the check."""
    msg = (
        "fix(x): something\n\n"
        "Local-Verified: B (pytest clean; mypy strict; ruff clean)\n"
        "Co-Authored-By: Someone <someone@example.com>\n"
    )
    assert has_trailer(msg)


# ── Rejected ──────────────────────────────────────────────────────────────

def test_rejects_missing_trailer() -> None:
    assert not has_trailer("fix(x): something\n\nNo trailer at all.\n")


def test_rejects_lowercase_tier() -> None:
    """CI greps [ABCD]; 'b' would pass a sloppy guard and fail CI."""
    assert not has_trailer("fix(x): y\n\nLocal-Verified: b (evidence)\n")


def test_rejects_tier_without_following_space() -> None:
    """CI's pattern requires a space after the tier letter."""
    assert not has_trailer("fix(x): y\n\nLocal-Verified: B(evidence)\n")


def test_rejects_trailer_not_at_line_start() -> None:
    """CI anchors with ^; an inline mention must not satisfy it."""
    assert not has_trailer("fix(x): y\n\nsee Local-Verified: B (evidence)\n")


def test_rejects_unknown_tier_letter() -> None:
    assert not has_trailer("fix(x): y\n\nLocal-Verified: E (evidence)\n")


def test_comment_lines_cannot_satisfy_the_check(tmp_path: Path) -> None:
    """Git strips '#' lines, so they must not count.

    Otherwise the template text git shows during `git commit` could satisfy
    the guard locally while CI, reading the stored message, sees nothing.
    """
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "fix(x): y\n\n# Local-Verified: B (this is a comment, not a trailer)\n",
        encoding="utf-8",
    )
    assert main(["prog", str(msg)]) == 1


# ── CLI contract ──────────────────────────────────────────────────────────

def test_main_returns_zero_when_trailer_present(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(x): y\n\nLocal-Verified: A (docs only)\n", encoding="utf-8")
    assert main(["prog", str(msg)]) == 0


def test_main_returns_two_on_bad_invocation() -> None:
    assert main(["prog"]) == 2


def test_main_returns_two_on_unreadable_path(tmp_path: Path) -> None:
    assert main(["prog", str(tmp_path / "does-not-exist")]) == 2


# ── The anti-drift test ───────────────────────────────────────────────────

def test_guard_matches_the_ci_job_patterns() -> None:
    """The local guard must accept exactly what CI accepts.

    Parses the grep patterns out of the trailer-check job rather than
    restating them, so editing CI without editing the guard fails here.
    """
    workflow = (_REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )
    patterns = set(re.findall(r"grep -qE '(\^Local-[^']+)'", workflow))

    assert patterns, "could not find trailer-check grep patterns in test.yml"
    assert patterns == {"^Local-Verified: [ABCD] ", "^Local-Verify-Bypass: "}, (
        "CI trailer-check patterns changed; update "
        "scripts/check_fnd_s14_trailer.py to match. Found: " + repr(sorted(patterns))
    )

    # And prove the guard actually honours each of them.
    assert has_trailer("x\n\nLocal-Verified: C (evidence)\n")
    assert has_trailer("x\n\nLocal-Verify-Bypass: reason\n")
