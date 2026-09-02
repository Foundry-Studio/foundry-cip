# foundry: kind=script domain=client-intelligence-platform
"""FND-S14 Local-Verified trailer check, enforced at commit time.

Master is live on this repo, so `.github/workflows/test.yml`'s `trailer-check`
job gates every push to master on an FND-S14 trailer. That job is correct but
it fires LATE: it is guarded by `github.ref == 'refs/heads/master'`, so a
missing trailer is invisible until the commit has already landed and turned
master red. There was no local guard, so the only way to learn you had
violated FND-S14 was to violate it.

This script is that local guard. It runs as a `commit-msg` hook (see
`.pre-commit-config.yaml`) and applies the SAME two acceptance patterns the CI
job applies, so local and CI cannot disagree:

    ^Local-Verified: [ABCD] <evidence>     -> pass
    ^Local-Verify-Bypass: <reason>         -> pass (acknowledged skip)
    neither                                -> fail

Keep `_ACCEPT_VERIFIED` / `_ACCEPT_BYPASS` byte-for-byte equivalent to the
grep patterns in the `trailer-check` job. If you change one, change the other
in the same commit, or the guard silently stops matching what CI enforces.

Usage (pre-commit passes the message path as argv[1]):

    python scripts/check_fnd_s14_trailer.py .git/COMMIT_EDITMSG

Exit codes: 0 = trailer present, 1 = missing, 2 = bad invocation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Mirrors: grep -qE '^Local-Verified: [ABCD] '   (test.yml, trailer-check job)
_ACCEPT_VERIFIED = re.compile(r"^Local-Verified: [ABCD] ", re.MULTILINE)
# Mirrors: grep -qE '^Local-Verify-Bypass: '
_ACCEPT_BYPASS = re.compile(r"^Local-Verify-Bypass: ", re.MULTILINE)

_FAILURE_HELP = """\
FND-S14 violation - commit message is missing its verification trailer.

Add ONE of these as a trailer line in the commit body:

  Local-Verified: <A|B|C|D> (<short evidence>)
  Local-Verify-Bypass: <one-line reason>

Tier guide (take the HIGHER tier when a change spans several):

  A  docs, frontmatter, README, governance prose, CHANGELOG
     -> no check required

  B  cip/, tests/, scripts/, config (pyproject.toml, ruff/mypy config)
     -> pytest clean + mypy cip/ + ruff check

  C  cip/migrations/, runtime deps, alembic.ini, requirements-dev.txt
     -> Tier B + alembic upgrade head against local Postgres
        + uv pip compile --check

  D  not applicable to this library-shape repo

Examples:

  Local-Verified: A (docs only; no code paths touched)
  Local-Verified: B (pytest tests/integration_mesh clean; mypy strict; ruff clean)
  Local-Verified: C (alembic upgrade head clean on local pg:16-alpine; pytest green)

Bypasses are legitimate but visible: they surface in PM weekly review, and
more than two in seven days raises a yellow flag (FND-S14 Rule 5).

See CLAUDE.md section "FND-S14 - Local-Verified discipline".\
"""


def has_trailer(message: str) -> bool:
    """True when `message` carries an FND-S14 trailer CI would accept."""
    return bool(_ACCEPT_VERIFIED.search(message) or _ACCEPT_BYPASS.search(message))


def _strip_comments(message: str) -> str:
    """Drop git's scissors/comment lines so they can't satisfy the check.

    `git commit` appends instructional lines starting with '#'. They are
    stripped before the message is stored, so matching against them would
    let a commit pass locally and then fail in CI, which is precisely the
    local-vs-CI disagreement this guard exists to prevent.
    """
    return "\n".join(
        line for line in message.splitlines() if not line.startswith("#")
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            f"usage: {Path(__file__).name} <commit-msg-file>",
            file=sys.stderr,
        )
        return 2

    msg_path = Path(argv[1])
    try:
        raw = msg_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read commit message file {msg_path}: {exc}", file=sys.stderr)
        return 2

    if has_trailer(_strip_comments(raw)):
        return 0

    print(_FAILURE_HELP, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
