# foundry: kind=script domain=meta touches=registry

"""Generate CIP's snapshot.yaml from per-pillar components.yaml files.

Per JOS-D0088 + JOS-SPEC-026:
- Each JOS-bound venture owns + serves a snapshot.yaml at the locked
  path .jos/components/snapshot.yaml
- The snapshot is the PUBLIC-IN-PORTFOLIO subset of components
  (the cross-venture-visible projection)
- The fleet aggregator (in another venture) reads this file to
  resolve cross-venture refs

CIP is FILE-AUTHORED (per JOS-D0085 Q1=b). Component declarations
live distributed across docs/pillars/<pillar>/components.yaml. This
generator walks all pillar files, merges + filters per SPEC-026, and
writes a single snapshot at .jos/components/snapshot.yaml.

Per JOS-SPEC-026 normative filter:
- Keep ONLY visibility == public-in-portfolio
- Keep ONLY status in (shipped, deprecated)
- Drop venture-internal fields per the SPEC-026 filter table

Usage:
    python scripts/components_snapshot.py
    python scripts/components_snapshot.py --dry-run

Exit codes:
    0 — snapshot written
    1 — no pillar components.yaml found
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PILLAR_GLOB = "docs/pillars/*/components.yaml"
OUTPUT_DIR = REPO_ROOT / ".jos" / "components"
SNAPSHOT_FILE = OUTPUT_DIR / "snapshot.yaml"

VENTURE_SLUG = "foundry-cip"
GENERATOR_TOOL = "scripts/components_snapshot.py"
SNAPSHOT_VERSION = "1.0"

INTERNAL_FIELDS_TO_DROP = {
    "description",
    "governance_refs",
    "provenance",
    "code_path",
    "storage_path",
    "container",
    "created",
    "last_modified",
    "shipped_date",
}

RELATIONS_KEEP = {
    "delivers_features",
    "uses_components",
    "composes_components",
    "external_dependencies",
    "replaces",
}

STATUS_KEEP = {"shipped", "deprecated"}


# =============================================================================
# Pure helpers
# =============================================================================


def filter_component(component: dict[str, Any]) -> dict[str, Any] | None:
    """Project a single component dict into snapshot form.

    Returns the filtered dict OR None if it fails the visibility/status
    filter (should be DROPPED).
    """
    if component.get("visibility") != "public-in-portfolio":
        return None
    if component.get("status") not in STATUS_KEEP:
        return None

    out: dict[str, Any] = {}
    for key, value in component.items():
        if key in INTERNAL_FIELDS_TO_DROP:
            continue
        if key == "relations" and isinstance(value, dict):
            kept = {k: v for k, v in value.items() if k in RELATIONS_KEEP}
            if kept:
                out["relations"] = kept
            continue
        out[key] = value
    return out


def project_components(
    source_components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for comp in source_components:
        projected = filter_component(comp)
        if projected is not None:
            kept.append(projected)
    return kept


def compute_coverage(
    source: list[dict[str, Any]], kept: list[dict[str, Any]]
) -> dict[str, Any]:
    omitted_by_visibility: dict[str, int] = {
        "tenant-scoped": 0,
        "by-request": 0,
        "external-paid": 0,
        "internal-only": 0,
    }
    omitted_by_status: dict[str, int] = {
        "planned": 0,
        "in-progress": 0,
        "retired": 0,
    }
    for c in source:
        v = c.get("visibility")
        s = c.get("status")
        if v != "public-in-portfolio":
            if v in omitted_by_visibility:
                omitted_by_visibility[v] += 1
            continue
        if s not in STATUS_KEEP and s in omitted_by_status:
            omitted_by_status[s] += 1
    return {
        "total_source_components": len(source),
        "public_components": len(kept),
        "omitted_by_visibility": omitted_by_visibility,
        "omitted_by_status": omitted_by_status,
    }


def content_hash(components: list[dict[str, Any]]) -> str:
    canonical = json.dumps(components, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =============================================================================
# I/O
# =============================================================================


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def load_all_pillar_components() -> list[dict[str, Any]]:
    """Walk docs/pillars/*/components.yaml, gather components from each."""
    import yaml

    components: list[dict[str, Any]] = []
    pillar_paths = sorted(REPO_ROOT.glob(PILLAR_GLOB))
    for path in pillar_paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(f"WARN: failed to parse {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        pillar_components = data.get("components") or []
        for comp in pillar_components:
            components.append(comp)
    return components


def emit_yaml(
    *,
    components: list[dict[str, Any]],
    coverage: dict[str, Any],
    source_commit: str,
) -> str:
    import yaml

    today = datetime.now(UTC).date().isoformat()
    payload = {
        "declared_thing": VENTURE_SLUG,
        "snapshot_version": SNAPSHOT_VERSION,
        "last_modified": today,
        "source_commit": source_commit,
        "generator": {
            "tool": GENERATOR_TOOL,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_components_yaml": "docs/pillars/*/components.yaml",
            "content_hash": content_hash(components),
        },
        "coverage": coverage,
        "components": components,
    }
    header = (
        "# foundry-cip components SNAPSHOT\n"
        "# AUTO-GENERATED by scripts/components_snapshot.py per JOS-SPEC-026 v1.0.\n"
        "# DO NOT EDIT BY HAND. This is the cross-venture-visible projection of\n"
        "# docs/pillars/*/components.yaml — only public-in-portfolio entries appear.\n\n"
    )
    return header + yaml.safe_dump(
        payload,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )


# =============================================================================
# Entry point
# =============================================================================


def run(dry_run: bool = False) -> int:
    print(f"Walking {PILLAR_GLOB}...", file=sys.stderr)
    source = load_all_pillar_components()
    if not source:
        print("ERROR: no pillar components.yaml found", file=sys.stderr)
        return 1
    print(f"  → {len(source)} source components across all pillars", file=sys.stderr)

    kept = project_components(source)
    coverage = compute_coverage(source, kept)
    print(
        f"  → {len(kept)} components kept (public-in-portfolio + shipped/deprecated)",
        file=sys.stderr,
    )
    print(f"  → omitted by visibility: {coverage['omitted_by_visibility']}", file=sys.stderr)
    print(f"  → omitted by status: {coverage['omitted_by_status']}", file=sys.stderr)

    yaml_text = emit_yaml(
        components=kept, coverage=coverage, source_commit=_git_sha()
    )

    if dry_run:
        print(yaml_text)
        print(
            f"\nDRY-RUN: would write {len(yaml_text)} bytes to {SNAPSHOT_FILE}",
            file=sys.stderr,
        )
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(yaml_text, encoding="utf-8")
    print(
        f"Wrote {SNAPSHOT_FILE} ({len(yaml_text)} bytes, {len(kept)} components)",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print to stdout instead of writing the file",
    )
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
