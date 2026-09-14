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

  --staged             pre-commit, local, inspects the git INDEX (what's
                        about to be committed). This is the only place
                        PREVENTION is possible on a public repo. Violation
                        detail (e.g. an email's domain) IS shown here —
                        it's your own terminal, not a public log.
  --range BASE..HEAD    CI (`.github/workflows/public-repo-guard.yml`),
                        inspects EVERY commit in the range individually
                        (each against its own first parent, not just a net
                        BASE..HEAD diff — see _scan_range), so an
                        add-then-remove within one push still gets caught.
                        On a public repo, by the time CI runs the content is
                        ALREADY public if it was ever pushed — this mode is
                        DETECTION, not prevention. Domain detail is
                        SUPPRESSED in this mode: CI logs on a public repo
                        are public too, and for B2B content the domain is
                        often the identifying half.

Be honest about that asymmetry wherever this script is discussed: the
pre-commit hook is the only real gate; CI is a smoke alarm.

NEVER print matched sensitive content. Violations are reported as
`RULE  path:line` (plus `[domain: x]` ONLY in --staged mode) — never the
matched text, never an email local part.

Usage:
    python scripts/check_public_repo_guard.py --staged
    python scripts/check_public_repo_guard.py --range <base-sha>..<head-sha>
    python scripts/check_public_repo_guard.py --range <base>..<head> --all
        (--all permits falling back to a full-history scan when no
        comparable base exists at all — see _scan_range. Without it, an
        unresolvable base means "nothing to scan", never "scan everything".)

Exit codes: 0 = clean (or nothing to scan), 1 = violation(s) found, 2 = bad
invocation.
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
GITIGNORE_WEAKENED = "GITIGNORE_WEAKENED"

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

# Case-insensitive, slash-boundary match — catches `WORKBENCH/`,
# `workbench/`, and `docs/WORKBENCH/notes.md` alike. The .gitignore rule it
# backs up (`WORKBENCH/`) is itself case-sensitive-on-disk but the ORIGINAL
# incident was two rules that were narrower than the real risk; widen here
# rather than repeat that mistake.
_WORKBENCH_RE = re.compile(r"(^|/)workbench/", re.IGNORECASE)

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

# Shapes that match _EMAIL_RE but are not really third-party email addresses.
#
# 1. Filename-style TLDs: `logo@2x.png`, `favicon@2x.svg`, `report@final.csv`
#    read as local="logo", domain="2x.png" — a real dotted "domain" whose
#    final component happens to be a file extension, not a TLD.
_FILENAME_EXTENSION_TLDS = frozenset(
    {"png", "jpg", "jpeg", "svg", "json", "md", "py", "csv", "txt", "yml", "yaml"}
)
# 2. URL basic-auth credentials: `https://user:pass@host/...` — the regex's
#    local part lands on the password, not a person.
_URL_CREDENTIAL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s/@]+:[^\s/@]+@")

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
        "foundry-studio.com",  # the org's own domain (CONTRIBUTING.md, SECURITY.md, pyproject.toml)
        # Synthetic fixture domains already established in this repo's test
        # suite (connector conformance fixtures, RLS tests, etc.) — not
        # real registrations.
        "x.com", "x.io", "y.com", "ex.com", "b.com", "b.cn",
        "brand.cn", "testbrand.cn", "acme.cn", "other.com", "silk.com",
    }
)

_UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_BACKTICK_UUID_RE = re.compile(rf"^`{_UUID_PATTERN}`$")
# The manifest/cheatsheet generators' bullet-list row shape:
#   `slug` — Name · *industry* — `uuid`
# Matched anywhere in the repo (not just under docs/tenants/) — the exact
# incident this rule exists for (docs/CIP-CHEATSHEET.md) is a sibling file,
# not a tenant-dir file.
_BULLET_CLIENT_ROW_RE = re.compile(rf"`[^`\n]+`\s*—\s*.+—\s*`{_UUID_PATTERN}`")

# .gitignore lines that must never be silently removed/narrowed. Substring
# match against a REMOVED line (stripped) — deliberately simple: the point
# isn't to parse gitignore syntax, it's to notice when a known-good deny
# rule disappears from the diff, whatever replaces it.
_GITIGNORE_GUARD_SIGNATURES = ("WORKBENCH/", "docs/tenants/*")

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
class DiffLine:
    lineno: int
    text: str


@dataclass
class DiffFile:
    path: str | None = None
    old_path: str | None = None
    is_binary: bool = False
    added_lines: list[DiffLine] = field(default_factory=list)
    removed_lines: list[DiffLine] = field(default_factory=list)


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")
_PLUS_PATH_RE = re.compile(r"^\+\+\+ (?:b/(.*)|/dev/null)$")
# Captures BOTH the old-side and new-side starting line numbers so removed
# lines (needed by GITIGNORE_WEAKENED) can be numbered too, not just added
# ones.
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _parse_unified_diff(diff_text: str) -> list[DiffFile]:
    """Parse `git diff -U0` output into per-file added/removed-line records.

    Tracks explicit HUNK STATE (`in_headers`) because "+++ ..." / "--- ..."
    are only meaningful as the file's path headers BEFORE the first hunk
    starts. A prior version of this parser matched those prefixes
    unconditionally, so a line of CONTENT that happened to start with
    "++ " (which `git diff` renders as "+++ ..." once its own leading '+'
    is added) was misread as a "+++ /dev/null" deletion marker mid-hunk,
    which set `path = None` and silently dropped every rule for the rest
    of that file. Once `in_headers` is False (i.e. we're past the first
    "@@" line), every "+"/"-" prefixed line is content, full stop.
    """
    files: list[DiffFile] = []
    current: DiffFile | None = None
    new_lineno = 0
    old_lineno = 0
    in_headers = False

    for line in diff_text.splitlines():
        header = _DIFF_HEADER_RE.match(line)
        if header:
            if current is not None:
                files.append(current)
            current = DiffFile(path=header.group(2), old_path=header.group(1))
            new_lineno = 0
            old_lineno = 0
            in_headers = True
            continue

        if current is None:
            continue  # stray output before the first file header

        # A hunk header can appear multiple times per file (multiple
        # non-contiguous changes) — always honour it, in or out of
        # "headers" state, and it always ends the headers state.
        hunk = _HUNK_HEADER_RE.match(line)
        if hunk:
            old_lineno = int(hunk.group(1))
            new_lineno = int(hunk.group(2))
            in_headers = False
            continue

        if in_headers:
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
            # Everything else here ("--- a/...", "index ...", "new file
            # mode ...", "rename from/to ...", "similarity index ...")
            # carries no information any rule needs.
            continue

        # Inside a hunk: every '+'/'-' prefixed line is CONTENT, even if it
        # spells "+++ ..." or "--- ..." — see docstring above.
        if line.startswith("+"):
            if current.path is not None:
                current.added_lines.append(DiffLine(new_lineno, line[1:]))
            new_lineno += 1
            continue

        if line.startswith("-"):
            current.removed_lines.append(DiffLine(old_lineno, line[1:]))
            old_lineno += 1
            continue

        # "\ No newline at end of file" and similar — no-op.

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
    # True only for detail that's itself sensitive (an email domain) and
    # must be suppressed outside --staged (local) mode. Non-sensitive
    # detail (e.g. which .gitignore guard line was removed) is always safe
    # to print.
    sensitive_detail: bool = False

    def render(self, *, reveal_sensitive_detail: bool) -> str:
        out = f"{self.rule}  {self.path}:{self.line}"
        if self.detail and (reveal_sensitive_detail or not self.sensitive_detail):
            out += f"  [{self.detail}]"
        return out


def _is_denied_path(path: str) -> bool:
    if _WORKBENCH_RE.search(path):
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


def _is_url_credential_span(line: str, start: int) -> bool:
    return any(
        cred.start() <= start < cred.end() for cred in _URL_CREDENTIAL_RE.finditer(line)
    )


def _is_not_really_an_email(line: str, match: re.Match, domain: str) -> bool:
    """Heuristics for _EMAIL_RE matches that are not third-party addresses:
    filenames (`logo@2x.png`), URL basic-auth credentials, and SCP-style git
    remotes (`git@github.com:org/repo.git`)."""
    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in _FILENAME_EXTENSION_TLDS:
        return True
    if _is_url_credential_span(line, match.start()):
        return True
    # SCP-style remote: `user@host:path`. A real email is essentially never
    # immediately followed by ':' with no space.
    return match.end() < len(line) and line[match.end()] == ":"


def _is_pipe_table_client_row(line: str) -> bool:
    """Matches the tenant-manifest generator's
    `| name | \\`slug\\` | \\`uuid\\` | industry |` row shape."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 4:
        return False
    return bool(_BACKTICK_UUID_RE.match(cells[2]))


def _is_client_roster_row(line: str) -> bool:
    if _is_pipe_table_client_row(line):
        return True
    return bool(_BULLET_CLIENT_ROW_RE.search(line))


def _evaluate(files: list[DiffFile]) -> list[Violation]:
    violations: list[Violation] = []
    for f in files:
        if f.path is not None:
            if _is_denied_path(f.path):
                violations.append(Violation(DENIED_PATH, f.path, 1))
            if _is_data_file(f.path):
                violations.append(Violation(DATA_FILE, f.path, 1))

            # Binary files carry no `added_lines` (git emits no +/- hunks
            # for them), so this loop is naturally a no-op for them — the
            # path rules above are all that can apply.
            for al in f.added_lines:
                if ALLOW_MARKER in al.text:
                    continue
                for match in _EMAIL_RE.finditer(al.text):
                    domain = match.group(2)
                    if _is_not_really_an_email(al.text, match, domain):
                        continue
                    if not _is_allowed_email_domain(domain):
                        violations.append(
                            Violation(
                                THIRD_PARTY_EMAIL, f.path, al.lineno,
                                f"domain: {domain}", sensitive_detail=True,
                            )
                        )
                if _is_client_roster_row(al.text):
                    violations.append(Violation(CLIENT_ROSTER_ROW, f.path, al.lineno))

        # .gitignore weakening check runs on REMOVED lines, independent of
        # `f.path` (a rename away from ".gitignore" is still worth flagging
        # via old_path, though --diff-filter=ACMR makes that rare).
        gitignore_path = f.path if f.path is not None else f.old_path
        if gitignore_path == ".gitignore":
            for rl in f.removed_lines:
                stripped = rl.text.strip()
                for sig in _GITIGNORE_GUARD_SIGNATURES:
                    # Exact match only. `startswith` would also fire on
                    # narrower PRE-EXISTING rules like
                    # "WORKBENCH/china-audit/intake/" -- verified false
                    # positive: the commit that replaced exactly those two
                    # narrow rules with the broad tree-shaped "WORKBENCH/"
                    # line (a STRENGTHENING, the origin incident's actual
                    # fix) flagged as if it were a weakening.
                    if stripped == sig:
                        violations.append(
                            Violation(GITIGNORE_WEAKENED, ".gitignore", rl.lineno,
                                      f"removed guard: {sig}")
                        )
                        break

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

# `-c core.quotepath=false` on every invocation: by default git renders any
# path byte >= 0x80 as a C-style octal escape inside double quotes (e.g.
# `"exports/\345\256\242...csv"`), which breaks every path-prefix/suffix
# check in this file for non-ASCII filenames. With quotepath off, git
# writes the raw UTF-8 bytes instead, which `_GIT_KW`'s utf-8 decoding
# already handles.
_GIT_BASE = ["git", "-c", "core.quotepath=false"]


def _repo_root() -> Path:
    proc = subprocess.run([*_GIT_BASE, "rev-parse", "--show-toplevel"], check=False, **_GIT_KW)
    if proc.returncode != 0:
        raise RuntimeError(f"not inside a git repository: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def _git_diff(repo_root: Path, args: list[str]) -> str:
    proc = subprocess.run([*_GIT_BASE, "diff", *args], cwd=repo_root, check=False, **_GIT_KW)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _commit_exists(repo_root: Path, sha: str) -> bool:
    proc = subprocess.run(
        [*_GIT_BASE, "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=repo_root, check=False, **_GIT_KW,
    )
    return proc.returncode == 0


def _merge_base_with_master(repo_root: Path, head: str) -> str | None:
    # Best-effort: origin/master may not be fetched locally yet (shallow
    # checkout, fresh clone). Fetch it; if that fails (no remote, offline,
    # throwaway test repo with no 'origin'), the caller decides what to do.
    subprocess.run([*_GIT_BASE, "fetch", "origin", "master"], cwd=repo_root, check=False, **_GIT_KW)
    proc = subprocess.run(
        [*_GIT_BASE, "merge-base", head, "origin/master"],
        cwd=repo_root, check=False, **_GIT_KW,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def _first_parent_or_empty_tree(repo_root: Path, commit: str) -> str:
    proc = subprocess.run(
        [*_GIT_BASE, "rev-parse", f"{commit}^"], cwd=repo_root, check=False, **_GIT_KW,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return _EMPTY_TREE_SHA  # commit is a root commit — nothing came before it


def _first_parent_commits(repo_root: Path, base: str | None, head: str) -> list[str]:
    """Commits reachable from `head`, first-parent only, oldest first.

    `base=None` means "every ancestor of head" (full-history scan — only
    reached when the caller has already required --all). Otherwise, the
    usual `base..head` range.
    """
    rev_args = ["--first-parent", "--reverse", head if base is None else f"{base}..{head}"]
    proc = subprocess.run(
        [*_GIT_BASE, "rev-list", *rev_args], cwd=repo_root, check=False, **_GIT_KW,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-list failed: {proc.stderr.strip()}")
    return [c for c in proc.stdout.splitlines() if c.strip()]


def _scan_range(
    repo_root: Path, range_arg: str, *, allow_full_repo_scan: bool
) -> list[Violation] | None:
    """Returns the unioned violations across every first-parent commit in
    the range, or None if there is genuinely nothing to scan.

    Diffs each commit against its OWN parent (not a single net BASE..HEAD
    diff) so an add-then-remove within one push is still caught — the net
    diff of "add a roster CSV, then delete it" is empty, but the roster
    blob was still pushed and is still public.
    """
    if ".." not in range_arg:
        raise ValueError(f"--range expects BASE..HEAD, got: {range_arg!r}")
    base, head = range_arg.split("..", 1)
    if not base or not head:
        raise ValueError(f"--range expects BASE..HEAD, got: {range_arg!r}")

    # HEAD all-zeros = GitHub's `after` SHA for a branch-deletion push.
    # An unresolvable HEAD (any other reason) means the same thing for our
    # purposes: there is no tree to inspect.
    if _ZERO_SHA_RE.match(head) or not _commit_exists(repo_root, head):
        return None

    resolved_base: str | None = base
    if _ZERO_SHA_RE.match(base) or not _commit_exists(repo_root, base):
        # New-branch push (all-zeros `before`) or a `before` that's no
        # longer reachable (force-push rewrote history). Try to recover a
        # meaningful base from where this branch forked off master; if
        # that's not available either, DO NOT silently fall back to
        # scanning the entire repository — that's a much bigger, slower,
        # noisier scan than anyone asked for, and (pre the --staged-only
        # domain suppression fix) is exactly how a false "full repo scan"
        # printed real domains into a CI log. Require an explicit --all.
        merge_base = _merge_base_with_master(repo_root, head)
        if merge_base:
            resolved_base = merge_base
        elif allow_full_repo_scan:
            resolved_base = None  # sentinel: full history from head
        else:
            return None

    commits = _first_parent_commits(repo_root, resolved_base, head)

    all_violations: list[Violation] = []
    seen: set[tuple[str, str, int, str]] = set()
    for commit in commits:
        parent = _first_parent_or_empty_tree(repo_root, commit)
        diff_text = _git_diff(repo_root, ["-U0", "--diff-filter=ACMR", parent, commit])
        for v in _evaluate(_parse_unified_diff(diff_text)):
            key = (v.rule, v.path, v.line, v.detail)
            if key in seen:
                continue
            seen.add(key)
            all_violations.append(v)
    return all_violations


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
        help="Inspect every first-parent commit introduced in this range (CI mode).",
    )
    parser.add_argument(
        "--all", action="store_true",
        help=(
            "Only meaningful with --range: permit falling back to a full-history "
            "scan when no comparable base exists at all (no merge-base with "
            "origin/master either). Without this flag, an unresolvable base means "
            "'nothing to scan', not 'scan everything'."
        ),
    )
    return parser


def main(argv: list[str]) -> int:
    # A non-ASCII path (see MUST-FIX 5) can otherwise raise UnicodeEncodeError
    # the moment this script tries to print it back out, on a machine whose
    # stdout is a legacy codepage (e.g. cp1252 on plain `python.exe` on
    # Windows) rather than UTF-8. Force UTF-8 on our OWN output streams,
    # same reasoning as `_GIT_KW` for git's output; `errors="replace"`
    # degrades an unrepresentable byte rather than crashing the guard on
    # its own output. `reconfigure` is Python 3.7+ on real TextIOWrapper
    # streams; guard the attribute in case stdout has been swapped for
    # something else (e.g. certain test/CI harnesses).
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

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
            violations: list[Violation] | None = _evaluate(_parse_unified_diff(diff_text))
            reveal_sensitive_detail = True
        else:
            violations = _scan_range(repo_root, args.range, allow_full_repo_scan=args.all)
            reveal_sensitive_detail = False
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if violations is None:
        print("0 violations found. (nothing to scan — deleted ref or no comparable base)")
        return 0

    for v in violations:
        print(v.render(reveal_sensitive_detail=reveal_sensitive_detail))

    if violations:
        print(f"\n{len(violations)} violation(s) found.\n")
        print(_REMEDIATION)
        return 1

    print("0 violations found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
