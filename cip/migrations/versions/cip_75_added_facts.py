# foundry: kind=migration domain=client-intelligence-platform
"""cip_75: ADDED — what humans tell us. First-class, pinned, and it outranks the machine.

PHASE 0 of the data-first reset (Tim, 2026-07-14).

THE FAILURE THIS FIXES
----------------------
The old system had no home for human knowledge. Tim saying "Grownsy is Chinese" had nowhere to
live, so it was either lost or smuggled in as an LLM assertion — and then I GRADED IT
"ASSERTED_ONLY / cannot be defended", because no matching row existed in the tables I had built.

Grownsy's Chinese product library was, at that moment, already ingested into our own knowledge
base. 132,311 HubSpot company records carrying a COUNTRY field were sitting in this same
database, synced hourly, unread.

    "Not in the database" NEVER means "not provable."

Absence of evidence is an INGESTION GAP or a RESEARCH TASK. It is never a verdict, and it is
certainly not grounds to overrule the people who actually know the answer.

WHAT ADDED IS
-------------
The fifth compartment: facts a HUMAN supplies that no feed carries.

    Tim's determinations       "Grownsy is Chinese." "Tiny Land is ours."
    Rhea's partner roster      who the partners are, their real commission rates
    Jake's manual lists        WeChat ids, the decoded referrer codes
    Negotiated changes         a fee increase, a Boost activation we drove
    Attribution evidence       "WE brought this brand to Boost, here's the Slack link"

Every row names its author. A decision is never anonymous.

PINNING — the rule that makes a decision a decision
---------------------------------------------------
A pinned fact CANNOT be overturned by automated evidence. New evidence may RAISE A FLAG in the
conflicts queue; it may never flip the value. Only another human act moves it (a superseding
row).

Tim's words: "the final decision is applied and sticks unless it is manually changed again."

Without this, a decision is just the most recent guess. The derivation layer reads ADDED FIRST
and stops there — machine evidence only ever fills the gaps a human has not spoken to.

Revision ID: cip_75_added_facts
Revises: cip_74_defensible_vs_asserted
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_75_added_facts"
down_revision: str | Sequence[str] | None = "cip_74_defensible_vs_asserted"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_SUBJECTS = ("brand", "partner", "deal")


def upgrade() -> None:
    subjects = ", ".join(f"'{s}'" for s in _SUBJECTS)

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS ps_added_facts (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL,
            subject_type  TEXT NOT NULL CHECK (subject_type IN ({subjects})),
            subject_id    TEXT NOT NULL,
            product_id    TEXT,
            field         TEXT NOT NULL,
            value         TEXT NOT NULL,
            rationale     TEXT NOT NULL,
            asserted_by   TEXT NOT NULL,
            asserted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            source_ref    TEXT,
            pinned        BOOLEAN NOT NULL DEFAULT true,
            superseded_by UUID REFERENCES ps_added_facts (id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_added_facts_subject "
        "ON ps_added_facts (tenant_id, subject_type, subject_id, field) "
        "WHERE superseded_by IS NULL"
    )
    op.execute("ALTER TABLE ps_added_facts ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY ps_added_facts_tenant ON ps_added_facts
            USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
        """
    )

    op.execute(
        "COMMENT ON TABLE ps_added_facts IS "
        "'ADDED — what a HUMAN tells us that no feed carries. Tim''s determinations, Rhea''s "
        "partner roster and rates, Jake''s WeChat list, the decoded referrer codes, and the "
        "attribution evidence for a cross-sell or reactivation WE drove. "
        "*** THIS OUTRANKS EVERY AUTOMATED SIGNAL. *** The derivation layer reads ADDED first and "
        "stops there; machine evidence only fills gaps a human has not spoken to. The old system "
        "had no home for human knowledge, so Tim saying ''Grownsy is Chinese'' was graded "
        "''ASSERTED_ONLY — cannot be defended'' — while Grownsy''s Chinese product library sat "
        "ingested in our own knowledge base and 132,311 HubSpot companies WITH a country field sat "
        "unread in this same database. ''Not in the database'' never means ''not provable''.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_added_facts.pinned IS "
        "'A pinned fact CANNOT be overturned by automated evidence. New evidence may raise a flag "
        "in the conflicts queue; it may NEVER flip the value. Only a human act moves it — a new "
        "row that supersedes this one. Tim: ''the final decision is applied and sticks unless it "
        "is manually changed again.'' Without pinning, a decision is merely the most recent guess.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_added_facts.asserted_by IS "
        "'WHO said it. Required. A decision is never anonymous — if we cannot say who made a call, "
        "we cannot defend it, revisit it, or learn from it.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_added_facts.rationale IS "
        "'WHY, in prose a human can audit. Required. ''Tim confirms it'' is a valid rationale — he "
        "is the authority. ''It looks Chinese'' is not, and never was.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_added_facts.superseded_by IS "
        "'Points at the LATER fact that replaced this one. Facts are never deleted or edited — "
        "they are superseded, so the history of a decision survives, including the wrong turns.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_added_facts.product_id IS "
        "'''connect'' or ''boost'' when the fact is about a DEAL rather than a whole brand — a "
        "lead source, an activation, a negotiated fee. NULL when it is a brand-level fact like "
        "nationality. The unit of ownership is the DEAL (brand x product), so most attribution "
        "facts belong to one product, not both.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_added_facts TO {r}")

    # ── the current view of what humans have told us ─────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_added_current")
    op.execute(
        """
        CREATE VIEW lens_ps_added_current AS
        SELECT a.*,
               b.brand_name
        FROM ps_added_facts a
        LEFT JOIN ps_brands b
               ON a.subject_type = 'brand'
              AND b.wayward_brand_id::text = a.subject_id
        WHERE a.superseded_by IS NULL
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_added_current IS "
        "'The facts humans have told us that are still live (not superseded). Read this BEFORE any "
        "derived decision — it is the top of the precedence ladder.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_added_current TO {r}")

    # ── PARK the money work. Not deleted — parked, loudly. ───────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_claim_pack")   # the "can't prove it" framing. Gone.

    park = (
        "*** PARKED 2026-07-14 — MONEY WORK IS FROZEN BY TIM. DO NOT QUOTE OR REASON FROM THIS. "
        "*** The ownership rules changed (doc 15 §5: the deal is brand x PRODUCT; the anchor is "
        "2025-10-01, not 2025-12-01; Boost and reactivation on the contract-10%% book are CONTESTED "
        "and decided by activation EVIDENCE, defaulting to the incumbent). Everything computed here "
        "predates those rules and is therefore WRONG. It will be rebuilt when Tim reactivates the "
        "money work. "
    )
    for v, tail in (
        ("lens_ps_claim_reconciliation",
         "This view also carried the analysis that led to grading brands ''cannot be proven "
         "Chinese'' — the error that caused the reset."),
        ("lens_ps_unclaimed", "Superseded by the rules in doc 15 §5."),
        ("lens_ps_partner_statement",
         "The partner economics are sound, but they rest on claimability, which is being rebuilt."),
        ("lens_ps_partner_summary", "As above."),
    ):
        op.execute(f"COMMENT ON VIEW {v} IS '{park}{tail}'")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_added_current")
    op.execute("DROP TABLE IF EXISTS ps_added_facts")
