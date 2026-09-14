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
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=path, capture_output=True, text=True,
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

def test_third_party_email_webmail_flagged(tmp_path: Path) -> None:
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


def test_email_local_part_never_printed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    local_part = "totallynotarealuser12345"
    _write(repo, "docs/notes.md", f"Contact: {local_part}@gmail.com\n")
    head = _commit_all(repo, "add contact note")

    result = _run_guard_range(repo, base, head)

    combined = result.stdout + result.stderr
    assert local_part not in combined
    assert "domain: gmail.com" in combined


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
