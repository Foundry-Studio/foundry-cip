# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Load ADDED facts — what a human tells us. The intake path for human knowledge.

Tim, 2026-07-14: "its not that my word is first class. its also that the final decision is
applied and sticks unless it is manually changed again."

This is how Tim's knowledge, Rhea's partner roster, Jake's WeChat list, the decoded referrer
codes, and every "WE brought this brand to Boost" claim get into the system as FIRST-CLASS
EVIDENCE — outranking every automated signal, and PINNED so no machine can overturn them.

WHY THIS EXISTS AT ALL
  The old system had no home for human knowledge. So when Tim said "Grownsy is Chinese", it had
  nowhere to live — and I graded it "ASSERTED_ONLY, cannot be defended" because no matching row
  existed in the tables I had built. Grownsy's Chinese product library was, at that moment,
  already ingested into our own knowledge base.

  "Not in the database" never means "not provable." It means GO GET IT — or, when a human already
  knows, WRITE IT DOWN HERE.

USAGE
  Facts live in a YAML/JSON file so they are reviewable in a PR, not buried in a script:

    python scripts/load_added_facts.py --file data/added/2026-07-14-tim.yaml [--apply]

  Or seed the confirmations Tim has already given:

    python scripts/load_added_facts.py --seed-tim [--apply]

FILE FORMAT (one fact per entry)
  - subject_type: brand          # brand | partner | deal
    subject:      "Grownsy"      # brand NAME (resolved to id) or a wayward_brand_id, or partner_id
    product:      null           # 'connect' | 'boost' — only for DEAL-level facts
    field:        china_status
    value:        confirmed_yes
    rationale:    "Tim confirms..."
    asserted_by:  "Tim Jordan"
    source_ref:   "chat 2026-07-14"
    pinned:       true
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

# Confirmations Tim has already given in conversation. Seeded so they are never lost again.
TIM_SEED: list[dict] = [
    {
        "subject_type": "brand",
        "subject": "Selgrownsy",
        "field": "china_status",
        "value": "confirmed_yes",
        "rationale": (
            "Tim: 'Grownsy is FOR SURE chinese.' Grownsy is a Project Silk CLIENT — we ingested "
            "their entire product library into the Foundry knowledge base on 2026-07-10 (83 of 87 "
            "files, English + 中文, searchable). It appears in 10 knowledge chunks in this very "
            "database. The evidence was never missing; nobody had looked outside the ps_* tables."
        ),
        "asserted_by": "Tim Jordan",
        "source_ref": "chat 2026-07-14; cip_knowledge_chunks; KB source c3129e67",
    },
    {
        "subject_type": "brand",
        "subject": "Tiny Land",
        "field": "china_status",
        "value": "confirmed_yes",
        "rationale": (
            "Tim: 'Tinyland is KNOWN chinese, form us, and was never in our payment reports.' "
            "Contact is Bruce Gao. NOTE: Wayward's country field for this brand was corrupted by a "
            "parser bug — it contains the string 'Impersonate Account button View Contact in "
            "Intercom button *Hubspot Sync Information*', HubSpot page furniture scraped into the "
            "country column. That single bug sent the brand to unknown-nationality and zeroed it."
        ),
        "asserted_by": "Tim Jordan",
        "source_ref": "chat 2026-07-13",
    },
    {
        "subject_type": "brand",
        "subject": "BrüMate",
        "field": "china_status",
        "value": "confirmed_no",
        "rationale": (
            "Tim: 'brumate is american for sure... american but referred by a chinese partner.' "
            "A Colorado drinkware company. It sits on the frozen exclusion list (OceanWing bucket) "
            "because a CHINESE PARTNER REFERRED IT — which is the key insight: the exclusion list "
            "asserts a REFERRAL CHANNEL, not a nationality. Overwhelmingly those are Chinese "
            "brands; occasionally, as here, they are not. This is why a human must be able to "
            "overrule the list."
        ),
        "asserted_by": "Tim Jordan",
        "source_ref": "chat 2026-07-14",
    },
]

RESOLVE_BRAND = text("""
    SELECT wayward_brand_id::text
    FROM ps_brands
    WHERE tenant_id = :t
      AND (wayward_brand_id::text = :s OR lower(btrim(brand_name)) = lower(btrim(:s)))
    ORDER BY (wayward_brand_id::text = :s) DESC,
             (SELECT count(*) FROM ps_monthly_earnings m
               WHERE m.wayward_brand_id = ps_brands.wayward_brand_id) DESC
    LIMIT 1
""")

# A new fact SUPERSEDES the previous live one for the same subject+field. Facts are never
# edited or deleted — the history of a decision, including its wrong turns, must survive.
SUPERSEDE = text("""
    UPDATE ps_added_facts
       SET superseded_by = :new_id
     WHERE tenant_id = :t
       AND subject_type = :subject_type
       AND subject_id = :subject_id
       AND field = :field
       AND product_id IS NOT DISTINCT FROM :product
       AND superseded_by IS NULL
       AND id <> :new_id
""")

INSERT = text("""
    INSERT INTO ps_added_facts
        (tenant_id, subject_type, subject_id, product_id, field, value,
         rationale, asserted_by, source_ref, pinned)
    VALUES
        (CAST(:t AS uuid), :subject_type, :subject_id, :product, :field, :value,
         :rationale, :asserted_by, :source_ref, :pinned)
    RETURNING id
""")


def run(conn, facts: list[dict], *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {"loaded": [], "unresolved": []}

    for f in facts:
        subject_type = f.get("subject_type", "brand")
        raw = str(f["subject"])
        subject_id = raw

        if subject_type == "brand":
            row = conn.execute(RESOLVE_BRAND, {"t": PS_TENANT, "s": raw}).fetchone()
            if not row:
                # NEVER invent an id. An unresolvable subject is reported, not guessed.
                out["unresolved"].append(raw)
                continue
            subject_id = row[0]

        params = {
            "t": PS_TENANT,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "product": f.get("product"),
            "field": f["field"],
            "value": str(f["value"]),
            "rationale": f["rationale"],
            "asserted_by": f["asserted_by"],
            "source_ref": f.get("source_ref"),
            "pinned": bool(f.get("pinned", True)),
        }
        new_id = conn.execute(INSERT, params).scalar()
        conn.execute(SUPERSEDE, {**params, "new_id": new_id})
        out["loaded"].append(
            f"{subject_type}:{raw} -> {f['field']}={f['value']} (by {f['asserted_by']})"
        )

    out["live_facts"] = [
        dict(zip(("brand", "field", "value", "by"), r, strict=False))
        for r in conn.execute(text("""
            SELECT COALESCE(brand_name, subject_id), field, value, asserted_by
            FROM lens_ps_added_current ORDER BY asserted_at
        """)).fetchall()
    ]
    if not apply:
        conn.execute(text("ROLLBACK"))
    out["applied"] = apply
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="YAML/JSON file of facts")
    ap.add_argument("--seed-tim", action="store_true", help="load Tim's known confirmations")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args(argv)

    facts: list[dict] = []
    if args.seed_tim:
        facts.extend(TIM_SEED)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            if args.file.endswith((".yaml", ".yml")):
                import yaml  # noqa: PLC0415
                facts.extend(yaml.safe_load(fh) or [])
            else:
                facts.extend(json.load(fh))
    if not facts:
        print("nothing to load — pass --seed-tim or --file", file=sys.stderr)
        return 2

    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            out = run(conn, facts, apply=args.apply)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
