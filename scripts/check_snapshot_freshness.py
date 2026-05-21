# foundry: kind=script domain=meta touches=registry

"""Check whether CIP's .jos/components/snapshot.yaml is stale.

Per JOS-SPEC-026 v1.1 freshness-check contract.

CIP is file-authored, so the source is the set of
docs/pillars/*/components.yaml files (not a single components.yaml).
The snapshot's source_commit must descend from the LATEST commit
across any of those files.

Usage:
    python scripts/check_snapshot_freshness.py
    python scripts/check_snapshot_freshness.py --quiet

Exit codes:
    0 — fresh
    1 — stale (re-run scripts/components_snapshot.py)
    2 — IO / config error
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PILLAR_GLOB = "docs/pillars/*/components.yaml"
SNAPSHOT_FILE = REPO_ROOT / ".jos" / "components" / "snapshot.yaml"


# =============================================================================
# Pure helpers (testable in isolation)
# =============================================================================


def is_descendant(ancestor_sha: str, descendant_sha: str, *, cwd: Path) -> bool:
    """git merge-base --is-ancestor wrapper. Self-ancestor short-circuits to True."""
    if ancestor_sha == descendant_sha:
        return True
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def stale_reason(
    source_commit: str | None,
    latest_pillar_commit: str | None,
    *,
    cwd: Path,
) -> str | None:
    """Snapshot is fresh when source_commit descends from latest_pillar_commit."""
    if source_commit is None:
        return "snapshot.yaml missing source_commit field"
    if source_commit == "unknown":
        return "snapshot.yaml source_commit is 'unknown' (no git context at generation)"
    if latest_pillar_commit is None:
        return (
            "no pillar components.yaml has any git history "
            "(untracked or never committed)"
        )
    if not is_descendant(latest_pillar_commit, source_commit, cwd=cwd):
        return (
            f"latest pillar commit ({latest_pillar_commit[:8]}) is NOT in "
            f"snapshot's source_commit history ({source_commit[:8]}); "
            "regenerate the snapshot"
        )
    return None


# =============================================================================
# I/O
# =============================================================================


def _load_snapshot_source_commit() -> str | None:
    if not SNAPSHOT_FILE.exists():
        print(f"ERROR: {SNAPSHOT_FILE} not found", file=sys.stderr)
        sys.exit(2)
    import yaml

    try:
        data = yaml.safe_load(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"ERROR: failed to parse {SNAPSHOT_FILE}: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        return None
    return data.get("source_commit")


def _latest_pillar_commit() -> str | None:
    """Latest commit SHA across ANY pillar components.yaml file."""
    pillar_paths = sorted(REPO_ROOT.glob(PILLAR_GLOB))
    if not pillar_paths:
        return None
    cmd = ["git", "log", "-1", "--format=%H", "--"] + [
        str(p) for p in pillar_paths
    ]
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


# =============================================================================
# Entry point
# =============================================================================


def run(quiet: bool = False) -> int:
    source_commit = _load_snapshot_source_commit()
    latest = _latest_pillar_commit()

    if not quiet:
        print(f"snapshot source_commit:     {source_commit}", file=sys.stderr)
        print(f"latest pillar components.yaml commit: {latest}", file=sys.stderr)

    reason = stale_reason(source_commit, latest, cwd=REPO_ROOT)
    if reason is None:
        if not quiet:
            print("OK: snapshot is fresh.", file=sys.stderr)
        return 0
    print(f"STALE: {reason}", file=sys.stderr)
    print(
        "Remediation: python scripts/components_snapshot.py",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational stderr output; rely on exit code",
    )
    args = parser.parse_args(argv)
    return run(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
