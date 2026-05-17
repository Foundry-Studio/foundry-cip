# foundry: kind=script domain=client-intelligence-platform
"""Block 1b of M8 — migrate every CIP doc frontmatter to JOS schema v1.5.

Per PM scope 60849328 (M8) + PM decision 859c0bd9 (JOS adoption,
prefix=CIP-). Each governed doc gets:
  id, uuid, title, type, owner, solve_for, stage_label, domain, version,
  created, last_modified, last_reviewed, review_cadence
Plus venture-local extras preserved as-is.

Run once. Also updates docs/_registry.yaml with every registered object.
"""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
import uuid
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).parent.parent
TODAY = datetime.date.today().isoformat()

# Hardcoded per-doc mapping. Each row:
#   relative path → (id, type, jos_domain, stage_label, review_cadence, solve_for)
# stage_label: adopt = production, trial = draft/in-progress, assess = stub/skeleton
# jos_domain values: meta, eng, doc, dat, fin, str, ops, ppl, leg
DOC_MAPPING: dict[str, tuple[str, str, str, str, int, str]] = {
    # --- Operator SOPs (how-to-run-it) ---
    "docs/CONNECTOR-AUTHORING-GUIDE.md": (
        "CIP-SOP-001", "sop", "eng", "adopt", 90,
        "Provide the canonical authoring procedure so every new connector ships against the same Protocol + conformance harness."),
    "docs/MIGRATION-RUNBOOK.md": (
        "CIP-SOP-002", "sop", "eng", "adopt", 90,
        "Operator procedure for applying CIP Alembic migrations safely against dev and prod."),
    "docs/LENS-AUTHORING-GUIDE.md": (
        "CIP-SOP-003", "sop", "dat", "adopt", 90,
        "Procedure for adding new lens views so analysts and agents can author filtered perspectives consistently."),
    "docs/METABASE-OPERATOR-GUIDE.md": (
        "CIP-SOP-004", "sop", "ops", "adopt", 90,
        "Operator guide for running Metabase against CIP under the cip_metabase_role grant pattern."),
    "docs/RLS-SET-LOCAL-OPERATOR-GUIDE.md": (
        "CIP-SOP-005", "sop", "eng", "adopt", 90,
        "How to use SET LOCAL app.current_tenant for safe per-request tenant scoping under RLS."),
    "docs/SYNC-ORCHESTRATOR-GUIDE.md": (
        "CIP-SOP-006", "sop", "eng", "adopt", 90,
        "Operator guide to running the sync orchestrator end-to-end: connector lifecycle, advisory locks, rate-limit handling."),
    "docs/HUBSPOT-CONNECTOR-GUIDE.md": (
        "CIP-SOP-007", "sop", "eng", "adopt", 90,
        "Per-connector operator guide for the HubSpot connector — auth, rate limits, property handling, gotchas."),
    "docs/ZENDESK-CONNECTOR-GUIDE.md": (
        "CIP-SOP-008", "sop", "eng", "adopt", 90,
        "Per-connector operator guide for the Zendesk connector — auth, rate limits, ticket entity coverage, gotchas."),
    "docs/ONBOARDING-A-NEW-TENANT.md": (
        "CIP-SOP-009", "sop", "ops", "adopt", 90,
        "Step-by-step runbook for onboarding a new venture/tenant into CIP, discovery-first with default-take-everything posture."),
    "docs/TENANT-ONBOARDING-CHECKLIST.md": (
        "CIP-SOP-010", "sop", "ops", "adopt", 90,
        "Terse copy-pasteable checklist for standing up a new CIP tenant end-to-end. Pairs with ONBOARDING-A-NEW-TENANT (the why + what-to-investigate runbook)."),
    "docs/FIXTURE-TENANT-HANDBOOK.md": (
        "CIP-SOP-011", "sop", "eng", "adopt", 90,
        "Authoritative reference for CIP's deterministic fixture tenant — what it is, how it's seeded, byte-identical determinism contract, when to regenerate."),
    "docs/DEPLOYING-FOUNDRY-CIP-FOR-A-NEW-VENTURE.md": (
        "CIP-SOP-012", "sop", "ops", "assess", 180,
        "Procedure for deploying foundry-cip as a library into a new venture's monorepo. Stub; fill_when: Phase 2 M3."),
    "docs/EXPORTING-VENTURE-CONNECTORS.md": (
        "CIP-SOP-013", "sop", "eng", "assess", 180,
        "Procedure for promoting a venture-internal connector back into the foundry-cip library. Stub; fill_when: Phase 8."),
    "docs/STANDALONE-INTEGRATION-GUIDE.md": (
        "CIP-SOP-014", "sop", "eng", "assess", 180,
        "Guide for consuming foundry-cip from a non-Foundry codebase. Stub; fill_when: external consumer / PyPI."),
    "docs/TROUBLESHOOTING-AND-INCIDENT-RESPONSE.md": (
        "CIP-SOP-015", "sop", "ops", "assess", 90,
        "Operator playbook for diagnosing and resolving CIP incidents. Filled incrementally as incidents occur."),
    "docs/PROPERTY-GLOSSARY-PATTERN.md": (
        "CIP-SOP-016", "sop", "dat", "adopt", 90,
        "Pattern for authoring tenant-property glossaries — the plain-English semantic layer with confidence levels over connector data."),

    # --- Specs (declarative reference) ---
    "docs/FOUR-ACCESS-PATHS.md": (
        "CIP-SPEC-001", "spec", "doc", "adopt", 180,
        "Spec for the four ways data leaves CIP: structured SQL, knowledge layer, knowledge graph, originals."),
    "docs/PHASE-1-TO-PHASE-2-HANDOFF.md": (
        "CIP-SPEC-002", "spec", "meta", "adopt", 180,
        "Phase boundary handoff doc — enumerates Phase 1 final state and Phase 2 entry criteria. Finalized at M8 close 2026-05-16."),
    "docs/architecture/ARCHITECTURE.md": (
        "CIP-SPEC-003", "spec", "eng", "trial", 180,
        "Authoritative architecture spec — components, data flow, RLS pattern, lens engine, SCD-2 persister, four-paths consumption."),
    "docs/vision/PHASE-1-PLAIN-SPEC.md": (
        "CIP-SPEC-004", "spec", "meta", "adopt", 365,
        "Plain-language acceptance criteria for Phase 1 — what must be true for Phase 1 to be considered complete."),
    "docs/vision/PHASE-1-PLAN.md": (
        "CIP-SPEC-005", "spec", "meta", "adopt", 365,
        "Phase 1 binding plan — milestone-by-milestone execution plan that produced the foundation we have today."),
    "docs/vision/PHASE-2-WAYWARD-WDGLL.md": (
        "CIP-SPEC-006", "spec", "meta", "trial", 180,
        "Phase 2 Wayward 'what does good look like' — the desired end-state for the first non-fixture tenant."),
    "docs/vision/PHASE-2.5-PLAN.md": (
        "CIP-SPEC-007", "spec", "meta", "trial", 180,
        "Phase 2.5 plan — Foundry self-tenant + outbound write-back to Chatwoot/Twenty/Drive."),
    "docs/vision/ROADMAP.md": (
        "CIP-SPEC-008", "spec", "meta", "adopt", 90,
        "CIP roadmap — phase-by-phase sequencing and current state. Updated as phases land."),
    "docs/EXTRACTION-HISTORY.md": (
        "CIP-SPEC-009", "spec", "meta", "adopt", 365,
        "Reference history of how foundry-cip was extracted from the Foundry-Agent-System monorepo, preserved for audit."),

    # --- Frameworks (upstream architectural references) ---
    "docs/vision/VISION.md": (
        "CIP-FW-001", "framework", "meta", "adopt", 180,
        "Top-level CIP product vision — what it is, why it exists, who consumes it, two-layer architecture, ten roadmap phases."),

    # --- Contracts (binding agreements between subsystems) ---
    "docs/CSS-CLASSIFICATION-CONTRACT.md": (
        "CIP-K01", "contract", "doc", "adopt", 180,
        "Contract for how CIP files classify under the CSS dimension — kind/domain/touches declarations, resolution priority, and discoverability-registry coupling."),
    "CLAUDE.md": (
        "CIP-K02", "contract", "meta", "adopt", 90,
        "Agent behavioral standards contract per JOS-R18; carries the jos:begin/end managed block plus venture-specific cognitive profile and operational rules."),
    "docs/_TEMPLATE.md": (
        "CIP-BP-005", "best-practice", "doc", "adopt", 365,
        "Template for authoring new CIP governance docs — frontmatter shape, section ordering, conventions."),

    # --- Diagnostics (calibration / retrospective) ---
    "docs/vision/PHASE-1-RETROSPECTIVE.md": (
        "CIP-DIAG-001", "diagnostic", "meta", "adopt", 365,
        "Phase 1 retrospective — what went right, what went wrong, calibration insights carried into Phase 2. Includes 2026-05-16 addendum covering post-M8 Wayward push + JOS adoption."),

    # --- Scaffolded directory READMEs (JOS-onboarding output) ---
    "docs/README.md": (
        "CIP-BP-001", "best-practice", "doc", "adopt", 365,
        "Top-level docs/ orientation — points contributors at the governance objects and where to put new content."),
    "docs/capabilities/README.md": (
        "CIP-BP-002", "best-practice", "doc", "adopt", 365,
        "Capabilities catalog placeholder; populated as CIP capability declarations are filed under JOS-S15."),
    "docs/catalogue/README.md": (
        "CIP-BP-003", "best-practice", "doc", "adopt", 365,
        "Component catalogue placeholder per JOS-S08; populated as CIP catalog entries land."),
    "docs/features/README.md": (
        "CIP-BP-004", "best-practice", "doc", "adopt", 365,
        "Feature registry placeholder per JOS-S15; populated as CIP features are declared."),

    # --- Tenant operational artifacts (auto-generated per-tenant) ---
    # Treated as venture diagnostics, not governance documents — they're regenerated by
    # scripts/generate_tenant_manifest.py + scripts/seed_glossary_into_registry.py.
    "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/GLOSSARY.md": (
        "CIP-DIAG-101", "diagnostic", "dat", "adopt", 90,
        "Wayward (EcomLever tenant) property glossary — plain-English semantic layer with confidence levels. Hand-maintained source-of-truth; materialized into cip_connector_property_registry via scripts/seed_glossary_into_registry.py."),
    "docs/tenants/dec814db-722a-4730-8e60-51afc4a5dad9/MANIFEST.md": (
        "CIP-DIAG-102", "diagnostic", "dat", "adopt", 90,
        "Wayward (EcomLever tenant) auto-generated data manifest — tenant identity, tables populated, sync health, property catalog. Regenerated by scripts/generate_tenant_manifest.py."),
}

# Files that exist but are intentionally NOT registered as governance objects.
# These get given stage_label: retire frontmatter so jos check passes, but they
# do not enter the active registry. Each entry maps to (id, type, jos_domain).
ARCHIVED_FILES: dict[str, tuple[str, str, str]] = {
    "docs/archive/cip-extraction-plan-v4.2.1.md": ("CIP-SPEC-901", "spec", "meta"),
    "docs/archive/cip-extraction-qc-rounds-1-through-8.md": ("CIP-DIAG-901", "diagnostic", "meta"),
    "docs/archive/cip-m2-deep-plan-v5.2.md": ("CIP-SPEC-902", "spec", "meta"),
    "docs/archive/cip-m2-deep-plan-v5.3.md": ("CIP-SPEC-903", "spec", "meta"),
    "docs/archive/cip-m2-deep-plan-v5.4.md": ("CIP-SPEC-904", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/README.md": ("CIP-SPEC-905", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-0-data-model.md": ("CIP-SPEC-906", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-1-connector-framework.md": ("CIP-SPEC-907", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-2-wayward-pipeline.md": ("CIP-SPEC-908", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-3-knowledge-access.md": ("CIP-SPEC-909", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-4-dashboards-reports.md": ("CIP-SPEC-910", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-5-web-chatbot.md": ("CIP-SPEC-911", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-6-anomaly-detection.md": ("CIP-SPEC-912", "spec", "meta"),
    "docs/archive/stages-superseded-2026-04-20/stages/phase-7-intelligence-layer.md": ("CIP-SPEC-913", "spec", "meta"),
    "docs/notes/01-initial-braindump.md": ("CIP-BP-911", "best-practice", "meta"),
    "docs/notes/02-vision-discussion-outline.md": ("CIP-BP-912", "best-practice", "meta"),
    "docs/notes/03-vision-conversation-log.md": ("CIP-BP-913", "best-practice", "meta"),
    "docs/research/industry-landscape.md": ("CIP-BP-921", "best-practice", "str"),
}


def get_git_created(rel_path: str) -> str | None:
    """Earliest commit date that touched this file, ISO date format."""
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%aI", "--", rel_path],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            lines = [l.strip() for l in out.stdout.strip().splitlines() if l.strip()]
            if lines:
                # last line is the oldest (git log default order is newest-first)
                return lines[-1][:10]
    except Exception:
        pass
    return None


def extract_existing_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) where body excludes the frontmatter block."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text = m.group(1)
    body = text[m.end():]
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def extract_title(body: str, fallback: str) -> str:
    """Find the first H1 heading in the body."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# ") and not line.startswith("# ---"):
            return line[2:].strip()
    return fallback


def build_new_frontmatter(rel_path: str, existing_fm: dict, body: str) -> dict:
    cip_id, jos_type, jos_domain, stage_label, review_cadence, solve_for = DOC_MAPPING[rel_path]
    title_default = Path(rel_path).stem.replace("-", " ").title()
    title = existing_fm.get("title") or extract_title(body, title_default)
    created = (
        existing_fm.get("created")
        or get_git_created(rel_path)
        or TODAY
    )
    if isinstance(created, datetime.date):
        created = created.isoformat()
    last_modified = existing_fm.get("last_updated") or existing_fm.get("last_modified") or TODAY
    if isinstance(last_modified, datetime.date):
        last_modified = last_modified.isoformat()
    owner = existing_fm.get("owner") or "tim"
    # Preserve any existing non-conflicting keys as extras
    preserved_keys = {
        k: v for k, v in existing_fm.items()
        if k not in {
            "kind", "domain", "status", "last_updated", "owner", "created",
            "id", "uuid", "title", "type", "solve_for", "stage_label", "version",
            "last_modified", "last_reviewed", "review_cadence",
        }
    }
    # Preserve uuid if it already exists — JOS-SO-003 says uuids never change
    existing_uuid = existing_fm.get("uuid")
    new_fm = {
        "id": cip_id,
        "uuid": existing_uuid if existing_uuid else str(uuid.uuid4()),
        "title": title,
        "type": jos_type,
        "owner": owner,
        "solve_for": solve_for,
        "stage_label": stage_label,
        "domain": jos_domain,
        "version": existing_fm.get("version", "1.0"),
        "created": created,
        "last_modified": last_modified,
        "last_reviewed": TODAY,
        "review_cadence": review_cadence,
    }
    # Append preserved extras after the required JOS keys
    new_fm.update(preserved_keys)
    return new_fm


def build_archived_frontmatter(rel_path: str, existing_fm: dict, body: str) -> dict:
    cip_id, jos_type, jos_domain = ARCHIVED_FILES[rel_path]
    title_default = Path(rel_path).stem.replace("-", " ").title()
    title = existing_fm.get("title") or extract_title(body, title_default)
    created = existing_fm.get("created") or get_git_created(rel_path) or TODAY
    if isinstance(created, datetime.date):
        created = created.isoformat()
    last_modified = existing_fm.get("last_updated") or existing_fm.get("last_modified") or TODAY
    if isinstance(last_modified, datetime.date):
        last_modified = last_modified.isoformat()
    preserved = {
        k: v for k, v in existing_fm.items()
        if k not in {
            "kind", "domain", "status", "last_updated",
            "id", "uuid", "title", "type", "solve_for", "stage_label", "version",
            "last_modified", "last_reviewed", "review_cadence", "owner", "created",
        }
    }
    existing_uuid = existing_fm.get("uuid")
    new_fm = {
        "id": cip_id,
        "uuid": existing_uuid if existing_uuid else str(uuid.uuid4()),
        "title": title,
        "type": jos_type,
        "owner": existing_fm.get("owner") or "tim",
        "solve_for": f"Retired/archived artifact retained for audit and historical context — {Path(rel_path).name}.",
        "stage_label": "retire",
        "domain": jos_domain,
        "version": existing_fm.get("version", "1.0"),
        "created": created,
        "last_modified": last_modified,
        "last_reviewed": TODAY,
        "review_cadence": 9999,  # effectively never; retired
    }
    new_fm.update(preserved)
    return new_fm


def main() -> int:
    registry_objects: list[dict] = []
    archived_objects: list[dict] = []
    written = 0
    for rel_path in sorted(DOC_MAPPING.keys()):
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            print(f"[SKIP] not found: {rel_path}", file=sys.stderr)
            continue
        text = full_path.read_text(encoding="utf-8")
        existing_fm, body = extract_existing_frontmatter(text)
        new_fm = build_new_frontmatter(rel_path, existing_fm, body)
        out_text = "---\n" + yaml.safe_dump(new_fm, sort_keys=False, default_flow_style=False, allow_unicode=True) + "---\n" + body
        full_path.write_text(out_text, encoding="utf-8")
        registry_objects.append({
            "id": new_fm["id"],
            "uuid": new_fm["uuid"],
            "title": new_fm["title"],
            "type": new_fm["type"],
            "stage_label": new_fm["stage_label"],
            "domain": new_fm["domain"],
            "owner": new_fm["owner"],
            "path": rel_path,
            "last_reviewed": new_fm["last_reviewed"],
        })
        written += 1
        print(f"[OK]    {new_fm['id']:18s} {rel_path}")

    # Pass 2: archived/retired files — get frontmatter for compliance but
    # land in a separate registry section to keep the active list clean.
    for rel_path in sorted(ARCHIVED_FILES.keys()):
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            print(f"[SKIP] not found: {rel_path}", file=sys.stderr)
            continue
        text = full_path.read_text(encoding="utf-8")
        existing_fm, body = extract_existing_frontmatter(text)
        new_fm = build_archived_frontmatter(rel_path, existing_fm, body)
        out_text = "---\n" + yaml.safe_dump(new_fm, sort_keys=False, default_flow_style=False, allow_unicode=True) + "---\n" + body
        full_path.write_text(out_text, encoding="utf-8")
        archived_objects.append({
            "id": new_fm["id"],
            "uuid": new_fm["uuid"],
            "title": new_fm["title"],
            "type": new_fm["type"],
            "stage_label": new_fm["stage_label"],
            "domain": new_fm["domain"],
            "path": rel_path,
        })
        written += 1
        print(f"[ARCH]  {new_fm['id']:18s} {rel_path}")

    # Write registry — active objects + retired sub-list
    registry_path = REPO_ROOT / "docs" / "_registry.yaml"
    all_objects = sorted(registry_objects, key=lambda r: r["id"]) + sorted(archived_objects, key=lambda r: r["id"])
    registry = {
        "schema_version": "1.0",
        "venture": "foundry",
        "id_prefix": "CIP",
        "last_updated": TODAY,
        "objects": all_objects,
    }
    registry_path.write_text(
        "# Venture-local governance registry for foundry-cip (CIP- prefix).\n"
        "# Schema: JOS-D0045 (Registry). Auto-generated by\n"
        "# scripts/migrate_frontmatter_to_jos.py — do not hand-edit; re-run\n"
        "# the script after adding/removing governed docs.\n"
        + yaml.safe_dump(registry, sort_keys=False, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"\nWrote {written} docs + registry ({len(registry_objects)} objects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
