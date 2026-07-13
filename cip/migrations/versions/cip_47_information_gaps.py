# foundry: kind=migration domain=client-intelligence-platform
"""cip_47: ps_information_gaps — the "we need info" queue that agents can actually work.

Tim, 2026-07-13: "for things like Joydeco, keep that as 'need info' as a field or tag, so
we can run those reports and filter for those, and we can get the info we need from Rhea
or someone else. We can just have you or another LLM run questionnaire sheets and get
answers, OR have an agent send messages on Slack to team... but we need the data there,
fields there, to do this."

THE IDEA
--------
An "unknown" is not a dead end — it is a TASK. Today our unknowns are scattered across
columns (nationality_class='unknown', partner match_status='unknown',
activity_source='none:no_activity_signal', a partner claim nobody has adjudicated). Each
is a question someone can answer, but nothing tracks WHO to ask, WHETHER we asked, or WHAT
they said. So the same question gets re-discovered forever and never closed.

This table makes each gap a first-class, workable row:
  - question       : the actual question, in words, ready to put in front of a human
  - ask_who / ask_channel : who can answer, and how to reach them (Slack / email / sheet)
  - status         : open -> asked -> answered -> resolved   (or blocked/abandoned)
  - answer         : what they said, verbatim
  - blocks         : which DECISION is stuck behind this gap

Designed for three consumers, all of which Tim named:
  1. REPORTS — filter "show me every brand needing info", grouped by who to ask.
  2. QUESTIONNAIRES — an LLM renders open gaps for one person into a single sheet, then
     writes the answers straight back into `answer`.
  3. SLACK AGENTS — an agent DMs the right person the right question and records the reply.

CRITICAL DESIGN RULE (the same one as everywhere else in this schema):
An ANSWER IS EVIDENCE, NOT A DECISION. When a gap is answered, the answer is written back
into ps_brand_observations with source_system='human:<who>' — it takes its place beside
Wayward's record and the partner's claim, and the decision layer resolves them. A human
saying so does not silently overwrite what a source said; it becomes another (strong)
source. That is what keeps the audit trail honest even when the answer comes from a person.

Revision ID: cip_47_information_gaps
Revises: cip_46_partners_confidence
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_47_information_gaps"
down_revision: str | Sequence[str] | None = "cip_46_partners_confidence"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

GAP_TYPES = (
    "referrer_unknown",        # nobody knows who brought this brand (e.g. Joydeco)
    "referrer_conflict",       # a partner claims a brand Wayward credits elsewhere
    "nationality_unknown",     # cannot tell if the brand is Chinese
    "nationality_conflict",    # Wayward says US, but China signals disagree
    "no_activity_signal",      # we cannot tell if it is dormant -> cannot tell if reactivatable
    "deal_terms_unknown",      # flat fee vs rev share vs rate not known
    "not_paid_verify",         # Chinese post-takeover brand we have never been paid on
    "contact_missing",         # no WeChat / no email
    "other",
)
STATUSES = ("open", "asked", "answered", "resolved", "blocked", "abandoned")
CHANNELS = ("slack", "email", "questionnaire", "wechat", "manual")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE ps_information_gaps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,

            -- what the gap is ABOUT (a brand, usually)
            client_id UUID,
            wayward_brand_id UUID,
            subject_label TEXT,            -- human-readable, e.g. the brand name

            gap_type TEXT NOT NULL
                CHECK (gap_type IN ({", ".join(f"'{g}'" for g in GAP_TYPES)})),

            -- the actual question, ready to put in front of a human
            question TEXT NOT NULL,
            context TEXT,                  -- what we already know / why we are asking

            -- WHO can answer, and HOW to reach them
            ask_who TEXT,                  -- 'rhea' | 'jake' | partner_id | 'team'
            ask_channel TEXT
                CHECK (ask_channel IS NULL OR ask_channel IN
                       ({", ".join(f"'{c}'" for c in CHANNELS)})),

            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ({", ".join(f"'{s}'" for s in STATUSES)})),
            priority INTEGER NOT NULL DEFAULT 3,   -- 1 = highest

            asked_at TIMESTAMPTZ,
            asked_by TEXT,                 -- which agent/human asked
            asked_ref TEXT,                -- Slack permalink / email id / sheet url

            answered_at TIMESTAMPTZ,
            answered_by TEXT,
            answer TEXT,                   -- verbatim, as they said it

            -- Which DECISION is stuck behind this gap. Makes the cost of not asking visible.
            blocks TEXT,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- One open gap of a given type per brand. Re-running the detectors must not
            -- pile up duplicate questions for the same thing.
            UNIQUE (tenant_id, wayward_brand_id, gap_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_gaps_work ON ps_information_gaps "
        "(tenant_id, status, ask_who, priority)"
    )
    op.execute(
        "COMMENT ON TABLE ps_information_gaps IS "
        "'The ''we need info'' queue (Tim, 2026-07-13). An unknown is not a dead end, it "
        "is a TASK: a question, a person who can answer it, and a record of what they "
        "said. Built to be worked three ways — filtered reports, LLM-generated "
        "questionnaire sheets, and agents that DM the right person on Slack. "
        "CRITICAL: an ANSWER IS EVIDENCE, NOT A DECISION. On resolution the answer is "
        "written back to ps_brand_observations with source_system=''human:<who>'', where "
        "it sits BESIDE Wayward''s record and the partner''s claim and the decision layer "
        "resolves them. A human answer never silently overwrites a source.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_information_gaps.blocks IS "
        "'Which decision is stuck behind this gap (e.g. ''nationality_class'', "
        "''partner_of_record'', ''is this reactivatable''). Makes the COST of not asking "
        "visible — an unanswered question is revenue we cannot claim or pursue.'"
    )
    op.execute("ALTER TABLE ps_information_gaps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_information_gaps FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON ps_information_gaps "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_information_gaps TO {r}")

    # The worklist an agent (or a human) actually opens.
    op.execute(
        """
        CREATE VIEW lens_ps_open_questions AS
        SELECT g.ask_who,
               g.ask_channel,
               g.gap_type,
               g.priority,
               count(*)                              AS open_questions,
               min(g.created_at)                     AS oldest,
               array_agg(g.subject_label ORDER BY g.priority, g.subject_label)
                   FILTER (WHERE g.subject_label IS NOT NULL)  AS brands
        FROM ps_information_gaps g
        WHERE g.status IN ('open','asked')
        GROUP BY 1,2,3,4
        ORDER BY g.priority, count(*) DESC
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_open_questions IS "
        "'Everything we still need to know, GROUPED BY WHO CAN ANSWER IT — so one person "
        "gets one questionnaire / one Slack message covering all their brands, instead of "
        "being pinged once per brand.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_open_questions TO {r}")

    _desc = (
        "Open information gaps grouped by who can answer them — drives questionnaires "
        "and Slack outreach."
    ).replace("'", "''")
    op.execute(
        f"""
        INSERT INTO cip_views (
            id, tenant_id, client_id, source_connector, source_id,
            ingested_at, refreshed_at, ingestion_batch_id, authority,
            view_name, description, filter_config,
            owner_type, owner_id, is_default, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), '{PS_TENANT}', NULL, 'lens-mirror', 'ps_open_questions',
            NOW(), NOW(), gen_random_uuid(), 'validated',
            'lens_ps_open_questions', '{_desc}',
            '{{"slug": "ps_open_questions", "sql_view": "lens_ps_open_questions", "filter_kind": "ps_open_questions", "phase": "2.9"}}'::jsonb,
            'system', 'cip', false, NOW(), NOW()
        )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM cip_views WHERE view_name='lens_ps_open_questions'")
    op.execute("DROP VIEW IF EXISTS lens_ps_open_questions")
    op.execute("DROP TABLE IF EXISTS ps_information_gaps CASCADE")
