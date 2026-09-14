# foundry: kind=test domain=client-intelligence-platform
"""scripts/check_public_repo_guard.py — one throwaway git repo per test.

Builds a real (tiny) git repository under tmp_path and drives the guard
via subprocess, exactly how pre-commit (--staged) and CI (--range) invoke
it. No mocking of git plumbing: the whole point of this script is correct
diff parsing, so the tests exercise the real thing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_public_repo_guard.py"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "master"], path)
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "Test"], path)
    # A commit so HEAD exists before any test-specific content lands.
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "seed"], path)


def _write(path: Path, rel: str, content: str) -> None:
    p = path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _commit_all(path: Path, message: str) -> str:
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", message], path)
    return _git(["rev-parse", "HEAD"], path).stdout.strip()


def _run_guard(path: Path, *args: str) -> subprocess.CompletedProcess:
    # encoding=utf-8: the guard now forces UTF-8 on its own stdout/stderr
    # (see main()'s reconfigure() call) precisely so non-ASCII paths print
    # correctly instead of "?"-mangling; decode this side the same way, or
    # a Windows test runner's default codepage would mangle it right back.
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _run_guard_range(path: Path, base: str, head: str) -> subprocess.CompletedProcess:
    return _run_guard(path, "--range", f"{base}..{head}")


def _run_guard_staged(path: Path) -> subprocess.CompletedProcess:
    return _run_guard(path, "--staged")


# ── DENIED_PATH ──────────────────────────────────────────────────────────

def test_denied_path_workbench_hit(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "WORKBENCH/china-audit/notes.md", "internal notes\n")
    head = _commit_all(repo, "add workbench notes")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DENIED_PATH  WORKBENCH/china-audit/notes.md:1" in result.stdout


def test_denied_path_tenants_sibling_dir_hit(tmp_path: Path) -> None:
    """The original leak: content landed in a SIBLING dir under docs/tenants/
    that neither of the two prior .gitignore rules covered. Any tenant dir
    other than the one registered exemption must be denied."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "docs/tenants/11111111-1111-1111-1111-111111111111/MANIFEST.md", "roster\n")
    head = _commit_all(repo, "add sibling tenant manifest")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    expected = "DENIED_PATH  docs/tenants/11111111-1111-1111-1111-111111111111/MANIFEST.md:1"
    assert expected in result.stdout


def test_denied_path_tenants_exempt_file_miss(tmp_path: Path) -> None:
    """The exact registered exemption (CIP-DIAG-102) must NOT be denied."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/MANIFEST.md",
        "# Tenant Manifest\n\n## Clients (3)\n",
    )
    head = _commit_all(repo, "add exempt manifest")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "DENIED_PATH" not in result.stdout


def test_denied_path_tenants_same_dir_other_file_hit(tmp_path: Path) -> None:
    """Only the two named files are exempt — a different file in the SAME
    exempt tenant dir must still be denied."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/EXPORT.csv",
        "name,client_id\n",
    )
    head = _commit_all(repo, "add stray export in exempt dir")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DENIED_PATH" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        "workbench/notes.md",           # lowercase
        "docs/WORKBENCH/notes.md",      # nested, upper, not a prefix match
        "exports/Workbench/x.md",       # mixed case, nested
    ],
)
def test_denied_path_workbench_case_and_nesting_widened(tmp_path: Path, path: str) -> None:
    """MUST-FIX 10: the original incident was deny rules narrower than the
    real risk. Match (^|/)workbench/ case-insensitively, not just a literal
    leading 'WORKBENCH/' prefix."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, path, "internal\n")
    head = _commit_all(repo, "add workbench-shaped path")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DENIED_PATH" in result.stdout


# ── DATA_FILE ────────────────────────────────────────────────────────────

def test_data_file_csv_hit(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "exports/revenue.csv", "amount\n100\n")
    head = _commit_all(repo, "add revenue export")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DATA_FILE  exports/revenue.csv:1" in result.stdout


def test_data_file_under_fixtures_allowed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "tests/fixtures/sample.csv", "a,b\n1,2\n")
    head = _commit_all(repo, "add fixture csv")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "DATA_FILE" not in result.stdout


# ── THIRD_PARTY_EMAIL ────────────────────────────────────────────────────

def test_third_party_email_webmail_flagged_in_range_mode(tmp_path: Path) -> None:
    """--range (CI) mode flags it, but per MUST-FIX 6 never prints the
    domain -- only --staged (local) mode does. See the paired test below."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    # Fictional fixture address — the guard's own escape hatch marks it as a
    # conscious exception so THIS commit doesn't trip the guard that's
    # scanning IT, while the sub-repo the test builds still sees the bare
    # line (without the marker) and is asserted to flag it below.
    _write(repo, "docs/notes.md", "Contact: someone@gmail.com\n")  # public-repo-guard: allow
    head = _commit_all(repo, "add contact note")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "THIRD_PARTY_EMAIL  docs/notes.md:1" in result.stdout
    assert "gmail.com" not in result.stdout  # domain suppressed in --range mode


def test_third_party_email_webmail_flagged_with_domain_in_staged_mode(tmp_path: Path) -> None:
    """--staged (local, your own terminal) mode DOES show the domain --
    that's the useful triage signal for the person about to commit it."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, "docs/notes.md", "Contact: someone@gmail.com\n")  # public-repo-guard: allow
    _git(["add", "-A"], repo)

    result = _run_guard_staged(repo)

    assert result.returncode == 1
    assert "THIRD_PARTY_EMAIL  docs/notes.md:1  [domain: gmail.com]" in result.stdout


def test_third_party_email_allowlisted_synthetic_domain_passes(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "tests/fixtures/connector_conformance/data.py", 'EMAIL = "person@x.com"\n')
    head = _commit_all(repo, "add fixture email")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_pytest_mark_decorator_not_matched_as_email(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "tests/test_something.py",
        '@pytest.mark.parametrize("x", [1, 2])\ndef test_x(x):\n    assert x\n',
    )
    head = _commit_all(repo, "add parametrized test")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_bare_at_domain_not_matched_as_email(tmp_path: Path) -> None:
    """China-signal code checks for bare '@163.com'-shaped strings with no
    local part; that must not be mistaken for a real address."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "cip/china_signals.py",
        'CHINA_EMAIL_DOMAINS = ("@163.com", "@qq.com")\n',
    )
    head = _commit_all(repo, "add china signal domains")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_preexisting_unchanged_email_line_not_flagged(tmp_path: Path) -> None:
    """Only ADDED lines are in scope — legacy content already in history
    must never trip the guard, or every existing leak becomes un-fixable
    without also editing unrelated lines."""
    # Fictional fixture address (see marker note in the webmail test above).
    repo = tmp_path / "r"
    _init_repo(repo)
    note_v1 = "Contact: realperson@somecompany.com\nline two\n"  # public-repo-guard: allow
    _write(repo, "docs/notes.md", note_v1)
    base = _commit_all(repo, "pre-existing note with a real address")

    note_v2 = "Contact: realperson@somecompany.com\nline two changed\n"  # public-repo-guard: allow
    _write(repo, "docs/notes.md", note_v2)
    head = _commit_all(repo, "unrelated edit to the same file")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_email_local_part_never_printed_range_mode(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    local_part = "totallynotarealuser12345"
    _write(repo, "docs/notes.md", f"Contact: {local_part}@gmail.com\n")
    head = _commit_all(repo, "add contact note")

    result = _run_guard_range(repo, base, head)

    combined = result.stdout + result.stderr
    assert local_part not in combined
    assert "gmail.com" not in combined  # --range suppresses domain too


def test_email_local_part_never_printed_staged_mode(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    local_part = "totallynotarealuser12345"
    _write(repo, "docs/notes.md", f"Contact: {local_part}@gmail.com\n")
    _git(["add", "-A"], repo)

    result = _run_guard_staged(repo)

    combined = result.stdout + result.stderr
    assert local_part not in combined
    assert "domain: gmail.com" in combined  # --staged DOES show the domain


# ── CLIENT_ROSTER_ROW ────────────────────────────────────────────────────

def test_client_roster_row_hit(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/MANIFEST.md",
        "| Client name | Slug | client_id | Industry |\n"
        "|---|---|---|---|\n"
        "| Acme Corp | `acme-corp` | `123e4567-e89b-12d3-a456-426614174000` | retail |\n",
    )
    head = _commit_all(repo, "add manifest with a roster row")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    expected = "CLIENT_ROSTER_ROW  docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/MANIFEST.md:3"
    assert expected in result.stdout


def test_client_roster_row_header_and_separator_not_matched(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/MANIFEST.md",
        "| Client name | Slug | client_id | Industry |\n"
        "|---|---|---|---|\n"
        "## Clients (0)\n",
    )
    head = _commit_all(repo, "add manifest header only")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "CLIENT_ROSTER_ROW" not in result.stdout


def test_client_roster_row_bullet_shape_hit(tmp_path: Path) -> None:
    """MUST-FIX 1: docs/CIP-CHEATSHEET.md wrote the SECOND real roster --
    the generator's bullet shape (`slug` — Name · *industry* — `uuid`), not
    the manifest's pipe-table shape. Must be caught too."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "docs/CIP-CHEATSHEET.md",
        "  - `wayward-china-100030771899` — iDaPro · *n/a* — "
        "`59054012-e9e2-520f-98ef-f3adee8899ad`\n",
    )
    head = _commit_all(repo, "add cheatsheet with a roster bullet")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "CLIENT_ROSTER_ROW  docs/CIP-CHEATSHEET.md:1" in result.stdout


def test_client_roster_row_matched_outside_docs_tenants(tmp_path: Path) -> None:
    """MUST-FIX 1: path-independent -- not gated to docs/tenants/. A roster
    row anywhere in the repo (a stray export, a debug dump, ...) counts."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "scripts/debug_dump.md",
        "| Acme Corp | `acme-corp` | `123e4567-e89b-12d3-a456-426614174000` | retail |\n",
    )
    head = _commit_all(repo, "add stray roster row outside docs/tenants")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "CLIENT_ROSTER_ROW  scripts/debug_dump.md:1" in result.stdout


# ── Escape hatch ─────────────────────────────────────────────────────────

def test_allow_marker_skips_email_line(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "docs/notes.md",
        "Contact: someone@gmail.com  # public-repo-guard: allow\n",
    )
    head = _commit_all(repo, "add allowed contact note")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


# ── --staged mode ────────────────────────────────────────────────────────

def test_staged_mode_flags_indexed_content(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, "WORKBENCH/x/notes.md", "internal\n")
    _git(["add", "-A"], repo)  # staged, NOT committed

    result = _run_guard_staged(repo)

    assert result.returncode == 1
    assert "DENIED_PATH  WORKBENCH/x/notes.md:1" in result.stdout


def test_staged_mode_clean_when_nothing_staged(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)

    result = _run_guard_staged(repo)

    assert result.returncode == 0


# ── Exit codes / bad invocation ──────────────────────────────────────────

def test_clean_repo_range_exits_zero(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "docs/harmless.md", "nothing to see here\n")
    head = _commit_all(repo, "harmless change")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "0 violations found." in result.stdout


def test_no_mode_flag_is_bad_invocation(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)

    result = _run_guard(repo)

    assert result.returncode == 2


def test_both_mode_flags_is_bad_invocation(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    result = _run_guard(repo, "--staged", "--range", f"{base}..{base}")

    assert result.returncode == 2


# ── Diff-parser hunk-state regression (MUST-FIX 4) ──────────────────────
#
# A content line that itself starts with "++ " becomes "+++ ..." once git
# prefixes it with its own leading '+'. A parser that treats ANY "+++ ..."
# line as a path header (valid only OUTSIDE a hunk, i.e. before the first
# "@@") misreads it as a "+++ /dev/null" deletion marker mid-hunk, sets
# path=None, and silently drops every rule for the REST of that file.
# Verified before the fix: a roster CSV starting with such a line produced
# 0 violations; a control file produced 2.

def test_plus_plus_content_line_does_not_drop_the_whole_file(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "exports/roster.csv", "++ /dev/null\nname,client_id\nAcme,123\n")
    head = _commit_all(repo, "add csv whose first line looks like a diff marker")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DATA_FILE  exports/roster.csv:1" in result.stdout


def test_plus_plus_content_line_does_not_drift_line_numbers(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    # Fictional fixture address (see marker note in the webmail test above).
    content = "++ /dev/null\nContact: someone@gmail.com\n"  # public-repo-guard: allow
    _write(repo, "docs/notes.md", content)
    head = _commit_all(repo, "add file whose first line looks like a diff marker")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "THIRD_PARTY_EMAIL  docs/notes.md:2" in result.stdout


# ── Non-ASCII filenames (MUST-FIX 5) ─────────────────────────────────────

def test_non_ascii_filename_still_matches_path_rules(tmp_path: Path) -> None:
    """Without `-c core.quotepath=false`, git renders non-ASCII path bytes
    as octal-escaped inside quotes (e.g. `"exports/\\345\\256..."`), which
    breaks every startswith/endswith path check. Verified before the fix:
    a Chinese-named .csv was missed while a sibling .xlsx was caught."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "exports/客户名单.csv", "name,client_id\n")
    head = _commit_all(repo, "add non-ascii named export")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DATA_FILE  exports/客户名单.csv:1" in result.stdout


# ── Per-commit replay: add-then-remove (MUST-FIX 3) ──────────────────────

def test_add_then_remove_within_range_still_flagged(tmp_path: Path) -> None:
    """The net BASE..HEAD diff of 'add a roster export, then delete it' is
    EMPTY -- but the blob was pushed and is still public the moment it
    landed. Scanning must be per-commit (each against its own parent), not
    a single net diff, or this is exactly the 'add an export then tidy up'
    case that goes undetected."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    _write(repo, "exports/roster.csv", "name,client_id\nAcme,123\n")
    _commit_all(repo, "oops, add a roster export")

    (repo / "exports" / "roster.csv").unlink()
    head = _commit_all(repo, "remove roster export")

    # Sanity check: the net diff really is empty.
    net_diff = _git(["diff", "-U0", "--diff-filter=ACMR", base, head], repo).stdout
    assert net_diff.strip() == ""

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "DATA_FILE  exports/roster.csv:1" in result.stdout


def test_unrelated_commits_in_range_are_not_duplicated(tmp_path: Path) -> None:
    """A violation introduced once and never touched again should be
    reported once, not once per commit in the range."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    _write(repo, "exports/roster.csv", "name,client_id\nAcme,123\n")
    _commit_all(repo, "add roster export")
    _write(repo, "docs/unrelated.md", "harmless change 1\n")
    _commit_all(repo, "unrelated commit 1")
    _write(repo, "docs/unrelated.md", "harmless change 2\n")
    head = _commit_all(repo, "unrelated commit 2")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert result.stdout.count("exports/roster.csv:1") == 1


# ── Range resolution edge cases (MUST-FIX 7) ─────────────────────────────

def test_head_all_zeros_is_nothing_to_scan(tmp_path: Path) -> None:
    """GitHub sends the all-zeros SHA as `after` on a branch-deletion push.
    Must exit 0 ("nothing to scan"), not fail red for an unrelated reason."""
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    zero = "0" * 40

    result = _run_guard_range(repo, base, zero)

    assert result.returncode == 0
    assert "nothing to scan" in result.stdout.lower()


def test_unresolvable_head_is_nothing_to_scan(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    bogus_head = "abcdef1234567890abcdef1234567890abcdef12"

    result = _run_guard_range(repo, base, bogus_head)

    assert result.returncode == 0
    assert "nothing to scan" in result.stdout.lower()


def test_base_all_zeros_no_merge_base_no_all_flag_is_nothing_to_scan(tmp_path: Path) -> None:
    """No 'origin' remote at all in this throwaway repo, so there's no
    merge-base to recover. Without --all this must be 'nothing to scan',
    NOT a silent full-repository scan (which, pre-fix, printed 59
    violations including real email domains on a bare `--range` push)."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, "WORKBENCH/x.md", "internal\n")
    head = _commit_all(repo, "add workbench file")
    zero = "0" * 40

    result = _run_guard_range(repo, zero, head)

    assert result.returncode == 0
    assert "nothing to scan" in result.stdout.lower()
    assert "DENIED_PATH" not in result.stdout


def test_base_all_zeros_with_all_flag_scans_full_history(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, "WORKBENCH/x.md", "internal\n")
    head = _commit_all(repo, "add workbench file")
    zero = "0" * 40

    result = _run_guard(repo, "--range", f"{zero}..{head}", "--all")

    assert result.returncode == 1
    assert "DENIED_PATH  WORKBENCH/x.md:1" in result.stdout


def test_unreachable_base_falls_back_to_merge_base_with_origin_master(tmp_path: Path) -> None:
    """A force-push can make the old `before` SHA unreachable. Recover by
    diffing from where this branch forked off origin/master instead of
    failing red for an unrelated reason (verified pre-fix: 'fatal: bad
    object')."""
    origin = tmp_path / "origin.git"
    _git(["init", "-q", "--bare", "-b", "master", str(origin)], tmp_path)

    repo = tmp_path / "r"
    _init_repo(repo)
    _git(["remote", "add", "origin", str(origin)], repo)
    _git(["push", "-q", "origin", "master"], repo)

    _write(repo, "docs/unrelated.md", "harmless\n")
    _commit_all(repo, "harmless commit")
    _write(repo, "WORKBENCH/x.md", "internal\n")
    head = _commit_all(repo, "add workbench file")

    bogus_base = "1234567890abcdef1234567890abcdef12345678"  # never existed

    result = _run_guard_range(repo, bogus_base, head)

    assert result.returncode == 1
    assert "DENIED_PATH  WORKBENCH/x.md:1" in result.stdout


# ── False-positive fixes (MUST-FIX 8) ────────────────────────────────────

def test_foundry_studio_domain_allowlisted(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "SECURITY.md", "Report security issues to security@foundry-studio.com\n")
    head = _commit_all(repo, "add security contact")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_url_basic_auth_credential_not_matched_as_email(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(
        repo,
        "scripts/config_example.py",
        'DSN = "postgresql://admin:s3cr3tpw@internal-db.acme-corp.io:5432/db"\n',
    )
    head = _commit_all(repo, "add example DSN")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_scp_style_git_remote_not_matched_as_email(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "README.md", "Clone via: git@github.com:Foundry-Studio/foundry-cip.git\n")
    head = _commit_all(repo, "add clone instructions")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


def test_filename_style_at_suffix_not_matched_as_email(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _write(repo, "docs/assets.md", "![logo](assets/logo@2x.png)\n")
    head = _commit_all(repo, "add asset reference")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "THIRD_PARTY_EMAIL" not in result.stdout


# ── .gitignore weakening (MUST-FIX 9) ────────────────────────────────────

def test_gitignore_weakened_workbench_line_removed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, ".gitignore", "WORKBENCH/\nother/\n")
    base = _commit_all(repo, "add gitignore with workbench deny")

    _write(repo, ".gitignore", "other/\n")
    head = _commit_all(repo, "accidentally narrow gitignore")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "GITIGNORE_WEAKENED  .gitignore" in result.stdout


def test_gitignore_weakened_tenants_line_removed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    exempt = "!docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/\n"
    _write(repo, ".gitignore", f"docs/tenants/*\n{exempt}")
    base = _commit_all(repo, "add gitignore with tenants deny")

    _write(repo, ".gitignore", "!docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/\n")
    head = _commit_all(repo, "accidentally drop the tenants deny line")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "GITIGNORE_WEAKENED  .gitignore" in result.stdout


def test_gitignore_weakened_fires_even_when_narrowed_not_just_deleted(tmp_path: Path) -> None:
    """Replacing the broad deny line with a narrower one is still a
    weakening -- the rule fires on the REMOVAL of the known-good line,
    regardless of what (if anything) replaces it."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, ".gitignore", "WORKBENCH/\n")
    base = _commit_all(repo, "add broad workbench deny")

    _write(repo, ".gitignore", "WORKBENCH/china-audit/\n")
    head = _commit_all(repo, "narrow workbench deny to one subdir")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 1
    assert "GITIGNORE_WEAKENED  .gitignore" in result.stdout


def test_gitignore_edit_that_does_not_touch_guard_lines_not_flagged(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo, ".gitignore", "WORKBENCH/\ndocs/tenants/*\n")
    base = _commit_all(repo, "add gitignore")

    _write(repo, ".gitignore", "WORKBENCH/\ndocs/tenants/*\n*.log\n")
    head = _commit_all(repo, "add an unrelated ignore rule")

    result = _run_guard_range(repo, base, head)

    assert result.returncode == 0
    assert "GITIGNORE_WEAKENED" not in result.stdout
