# foundry: kind=script domain=client-intelligence-platform
"""Public-repo content guard — a tripwire, not a guarantee.

`foundry-cip` is a PUBLIC repo (see CLAUDE.md's "THIS REPOSITORY IS PUBLIC"
banner). A 1,404-name client roster, revenue CSVs, and 453 third-party email
addresses sat world-readable here for months before being purged, even though
two `.gitignore` path rules existed for exactly this risk — the data landed
in a sibling directory neither rule covered.

This script inspects only ADDED content (new/changed paths and added diff
lines), so pre-existing legacy content already in history never trips it —
that would be noisy, retroactive, and out of scope for a tripwire. It runs
in two places:

  --staged            pre-commit, local, inspects the git INDEX (what's
                       about to be committed). This is the only place
                       PREVENTION is possible on a public repo.
  --range BASE..HEAD   CI (`.github/workflows/public-repo-guard.yml`),
                       inspects a push/PR diff range. On a public repo, by
                       the time CI runs the content is ALREADY public if it
                       was ever pushed — this mode is DETECTION, not
                       prevention. It exists to catch what slipped past a
                       skipped or missing local hook, not to stop the leak.

Be honest about that asymmetry wherever this script is discussed: the
pre-commit hook is the only real gate; CI is a smoke alarm.

NEVER print matched sensitive content. On a public repo, CI logs are public
too. Violations are reported as `RULE  path:line  [domain: x]` only — never
the matched text, never an email local part.

Usage:
    python scripts/check_public_repo_guard.py --staged
    python scripts/check_public_repo_guard.py --range <base-sha>..<head-sha>

Exit codes: 0 = clean, 1 = violation(s) found, 2 = bad invocation.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Rule ids ─────────────────────────────────────────────────────────────
DENIED_PATH = "DENIED_PATH"
DATA_FILE = "DATA_FILE"
THIRD_PARTY_EMAIL = "THIRD_PARTY_EMAIL"
CLIENT_ROSTER_ROW = "CLIENT_ROSTER_ROW"

# A line containing this literal string is skipped by the line-content rules
# (THIRD_PARTY_EMAIL, CLIENT_ROSTER_ROW). This is a conscious, reviewable
# escape hatch, not a silent one: it shows up verbatim in the diff a
# reviewer (human or CI log reader) sees, so using it is a decision someone
# has to own, not a way to quietly disable the guard.
ALLOW_MARKER = "public-repo-guard: allow"

# The one registered exemption under docs/tenants/ (CIP-DIAG-102): a
# governed object mirrored in docs/_registry.yaml. Everything else under
# docs/tenants/ is denied — see DENIED_PATH below and the matching
# .gitignore tree-shaped rule this script backs up.
_EXEMPT_TENANT_PATHS = frozenset(
    {
        "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/GLOSSARY.md",
        "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/MANIFEST.md",
    }
)

_DATA_FILE_EXTS = (
    ".csv", ".tsv", ".xlsx", ".xls", ".gz", ".zip", ".parquet",
    ".db", ".sqlite", ".sqlite3", ".jsonl",
)

# Requires a local part directly adjacent to '@' (no gap), so bare
# domain-only strings like '@163.com' (used in China-signal code without a
# real address attached) do not match, and decorators like
# `@pytest.mark.parametrize` don't either — there's no local-part character
# touching the '@' in either case. Domain must carry a dotted TLD.
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,})(?![\w-])"
)

# Reserved-for-documentation domains (RFC 2606) and their subdomains never
# resolve to a real inbox, so they can't be a real third party.
_RESERVED_EMAIL_BASES = ("example.com", "example.org", "example.net")
_RESERVED_EMAIL_TLDS = frozenset({"test", "example", "invalid", "localhost"})

# Everything else is a deliberate, individually-justified allowlist entry.
# Keep this SMALL. Do NOT add real company or webmail domains (gmail, qq,
# 163, hotmail, outlook, wayward.com, artica.com, etc.) — a new
# real-looking address showing up in a diff is exactly the signal this rule
# exists to catch.
_ALLOWED_EMAIL_DOMAINS = frozenset(
    {
        # GitHub noreply addresses — not personal data, not a leak.
        "users.noreply.github.com",
        "noreply.github.com",
        # Foundry-owned public-facing domains.
        "project-silk.com",
        "meettimjordan.com",
        # Synthetic fixture domains already established in this repo's test
        # suite (connector conformance fixtures, RLS tests, etc.) — not
        # real registrations.
        "x.com", "x.io", "y.com", "ex.com", "b.com", "b.cn",
        "brand.cn", "testbrand.cn", "acme.cn", "other.com", "silk.com",
    }
)

_UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_BACKTICK_UUID_RE = re.compile(rf"^`{_UUID_PATTERN}`$")

_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_ZERO_SHA_RE = re.compile(r"^0+$")

_REMEDIATION = (
    "Move this material to a PRIVATE venture repo (e.g. venture-project-silk,\n"
    "or a client-specific private repo) and reference it from here instead of\n"
    "committing it. See CLAUDE.md's 'THIS REPOSITORY IS PUBLIC' banner.\n"
    "\n"
    "Reminder: on a public repo, prevention only works at the pre-commit\n"
    "hook. If this ran in CI, the content may already be public -- treat it\n"
    "as a real incident (rotate/purge), not just a fix-forward diff."
)


# ── Diff model ───────────────────────────────────────────────────────────

@dataclass
class AddedLine:
    lineno: int
    text: str


@dataclass
class DiffFile:
    path: str | None = None
    old_path: str | None = None
    is_binary: bool = False
    added_lines: list[AddedLine] = field(default_factory=list)


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")
_PLUS_PATH_RE = re.compile(r"^\+\+\+ (?:b/(.*)|/dev/null)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _parse_unified_diff(diff_text: str) -> list[DiffFile]:
    """Parse `git diff -U0` output into per-file added-line records.

    Deliberately minimal: only tracks what the rules below need (the
    resulting path, binary-ness, and added lines with their new-file line
    numbers). Non-matching lines (mode changes, index lines, rename
    markers, "\\ No newline at end of file", etc.) are silently ignored —
    they carry no information any rule cares about.
    """
    files: list[DiffFile] = []
    current: DiffFile | None = None
    new_lineno = 0

    for line in diff_text.splitlines():
        header = _DIFF_HEADER_RE.match(line)
        if header:
            if current is not None:
                files.append(current)
            current = DiffFile(path=header.group(2), old_path=header.group(1))
            new_lineno = 0
            continue

        if current is None:
            continue  # stray output before the first file header

        if line.startswith("Binary files") or line.startswith("GIT binary patch"):
            current.is_binary = True
            continue

        plus_path = _PLUS_PATH_RE.match(line)
        if plus_path:
            # None (=== /dev/null) means this side of the diff is a
            # deletion; --diff-filter=ACMR should already exclude pure
            # deletes, but stay defensive.
            current.path = plus_path.group(1)
            continue

        hunk = _HUNK_HEADER_RE.match(line)
        if hunk:
            new_lineno = int(hunk.group(1))
            continue

        if line.startswith("+++") or line.startswith("---"):
            continue  # already handled above / old-file marker, no-op

        if line.startswith("+"):
            if current.path is not None:
                current.added_lines.append(AddedLine(new_lineno, line[1:]))
            new_lineno += 1
            continue

        if line.startswith("-"):
            continue  # removed line — doesn't advance the new-file counter

    if current is not None:
        files.append(current)
    return files


# ── Rule evaluation ──────────────────────────────────────────────────────

@dataclass
class Violation:
    rule: str
    path: str
    line: int
    detail: str = ""

    def render(self) -> str:
        out = f"{self.rule}  {self.path}:{self.line}"
        if self.detail:
            out += f"  [{self.detail}]"
        return out


def _is_denied_path(path: str) -> bool:
    if path.startswith("WORKBENCH/"):
        return True
    return path.startswith("docs/tenants/") and path not in _EXEMPT_TENANT_PATHS


def _is_data_file(path: str) -> bool:
    if path.startswith("tests/fixtures/"):
        return False
    return path.lower().endswith(_DATA_FILE_EXTS)


def _is_allowed_email_domain(domain: str) -> bool:
    domain_l = domain.lower()
    if domain_l in _ALLOWED_EMAIL_DOMAINS:
        return True
    for base in _RESERVED_EMAIL_BASES:
        if domain_l == base or domain_l.endswith(f".{base}"):
            return True
    tld = domain_l.rsplit(".", 1)[-1]
    return tld in _RESERVED_EMAIL_TLDS


def _is_client_roster_row(line: str) -> bool:
    """Matches the manifest generator's
    `| name | \\`slug\\` | \\`uuid\\` | industry |` row shape."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 4:
        return False
    return bool(_BACKTICK_UUID_RE.match(cells[2]))


def _evaluate(files: list[DiffFile]) -> list[Violation]:
    violations: list[Violation] = []
    for f in files:
        if f.path is None:
            continue  # deletion — out of scope, only ADDED content is checked

        if _is_denied_path(f.path):
            violations.append(Violation(DENIED_PATH, f.path, 1))
        if _is_data_file(f.path):
            violations.append(Violation(DATA_FILE, f.path, 1))

        # Binary files carry no `added_lines` (git emits no +/-  hunks for
        # them), so the loop below is naturally a no-op for them — the path
        # rules above are all that can apply.
        under_tenants = f.path.startswith("docs/tenants/")
        for al in f.added_lines:
            if ALLOW_MARKER in al.text:
                continue
            for match in _EMAIL_RE.finditer(al.text):
                domain = match.group(2)
                if not _is_allowed_email_domain(domain):
                    violations.append(
                        Violation(THIRD_PARTY_EMAIL, f.path, al.lineno, f"domain: {domain}")
                    )
            if under_tenants and _is_client_roster_row(al.text):
                violations.append(Violation(CLIENT_ROSTER_ROW, f.path, al.lineno))

    return violations


# ── Git plumbing ─────────────────────────────────────────────────────────

# Repo content (commit history going back to the monorepo extraction) isn't
# ASCII-only — em dashes, Chinese copy in messaging-work commits, etc. On
# Windows, `subprocess.run(..., text=True)` decodes with the console's
# locale codepage (cp1252) by default, not UTF-8, and raises on the first
# byte it can't map. Force UTF-8 explicitly so this behaves the same on
# every OS pre-commit and CI run on; `errors="replace"` degrades a bad byte
# to U+FFFD instead of crashing the guard entirely — a corrupted character
# is not worth failing open (or failing to run at all) over.
_GIT_KW = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


def _repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=False, **_GIT_KW,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"not inside a git repository: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def _git_diff(repo_root: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "diff", *args], cwd=repo_root, check=False, **_GIT_KW,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git diff {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _merge_base_with_master(repo_root: Path, head: str) -> str | None:
    # Best-effort: origin/master may not be fetched locally yet (shallow
    # checkout, fresh clone). Fetch it; if that fails (no remote, offline,
    # throwaway test repo with no 'origin'), fall through to the empty tree.
    subprocess.run(
        ["git", "fetch", "origin", "master"], cwd=repo_root, check=False, **_GIT_KW,
    )
    proc = subprocess.run(
        ["git", "merge-base", head, "origin/master"], cwd=repo_root, check=False, **_GIT_KW,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def _resolve_range(repo_root: Path, range_arg: str) -> tuple[str, str]:
    if ".." not in range_arg:
        raise ValueError(f"--range expects BASE..HEAD, got: {range_arg!r}")
    base, head = range_arg.split("..", 1)
    if not base or not head:
        raise ValueError(f"--range expects BASE..HEAD, got: {range_arg!r}")
    if _ZERO_SHA_RE.match(base):
        # New-branch push: GitHub sends the all-zeros SHA as `before`.
        # There's no real base commit, so diff against where this branch
        # forked from master (or the empty tree if that's unavailable too).
        base = _merge_base_with_master(repo_root, head) or _EMPTY_TREE_SHA
    return base, head


# ── CLI ───────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_public_repo_guard.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--staged", action="store_true",
        help="Inspect the git index (pre-commit mode).",
    )
    mode.add_argument(
        "--range", metavar="BASE..HEAD",
        help="Inspect ADDED lines/paths introduced in this range (CI mode).",
    )
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed usage/error to stderr; normalize to our
        # documented bad-invocation exit code.
        return 2 if exc.code not in (0, None) else 0

    try:
        repo_root = _repo_root()
        if args.staged:
            diff_text = _git_diff(repo_root, ["--cached", "-U0", "--diff-filter=ACMR"])
        else:
            base, head = _resolve_range(repo_root, args.range)
            diff_text = _git_diff(repo_root, ["-U0", "--diff-filter=ACMR", base, head])
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    files = _parse_unified_diff(diff_text)
    violations = _evaluate(files)

    for v in violations:
        print(v.render())

    if violations:
        print(f"\n{len(violations)} violation(s) found.\n")
        print(_REMEDIATION)
        return 1

    print("0 violations found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
