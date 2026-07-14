# foundry: kind=migration domain=client-intelligence-platform
"""cip_66: ps_nationality_signals. The China call, with its evidence, in the DB.

Tim: "do this in an organized way where the CIP shows everything, not just you manually."

He is right, and it is the whole architecture of this system applied to the last open question.
A determination that lives in a chat message is worth nothing: it cannot be audited, cannot be
re-run when new data lands, cannot be handed to an LLM, and cannot be defended to Wayward. So
every signal that bears on a brand's nationality becomes a ROW, and the decision is derived from
the rows.

THE SIGNALS, and why each one is worth what it is worth
------------------------------------------------------
  DEFINITIONAL  on_exclusion_list      Contract §1.4 defines Excluded Brands as "any and all
                                       Chinese-based Brands...". Being on that list is Wayward
                                       and Project Silk jointly asserting the brand is Chinese,
                                       in a signed instrument. Nothing is stronger. 399 of the
                                       unknown brands are on it.

  CONFIRMED     wayward_country_cn     Wayward's onboarding feed says CN.
                cjk_in_name            Chinese characters in the brand or contact name.

  STRONG        chinese_email_domain   qq / 163 / 126 / sina / foxmail / aliyun. A Chinese
                                       consumer mailbox on a brand contact is not an accident.
                chinese_partner        Referred by one of OUR China partners (Kerry, Cassie,
                                       Sarah, Adina, Eric...). They do not source US brands.
                eric_sheet             Present in Eric's all-agreements sheet — his book IS the
                                       China programme.

  MANUAL        manual_review          A human or LLM asserting nationality WITH a rationale and
                                       an author. This is how Tim's knowledge ("Tiny Land is
                                       Chinese, I know it") enters the system as evidence rather
                                       than as an untraceable edit.

  NEGATIVE      wayward_country_other  Wayward states a real ISO country that is not CN.

WHAT IS DELIBERATELY *NOT* A SIGNAL
-----------------------------------
The BRAND NAME. Bob and Brad is Chinese. AEEZO is Chinese. "SOUTH KOREA ULIKE GROUP" is a
Shenzhen company. Chinese Amazon sellers use Western-sounding private-label names as a matter of
course — that is the entire point of the branding. A name may generate a REVIEW, never a
DECISION, and this schema will not store it as one.

CHINA WINS
----------
Tim's rule (§3 of doc 15): any single source saying China locks it. A "US" flag never overrides
a China signal — it usually just means a US-registered shell. So the decision is: if ANY positive
signal exists, the brand is Chinese. A negative signal only decides the brand when NO positive
signal exists at all.

Revision ID: cip_66_nationality_signals
Revises: cip_65_unknown_nationality
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_66_nationality_signals"
down_revision: str | Sequence[str] | None = "cip_65_unknown_nationality"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_SIGNALS = (
    "on_exclusion_list",      # definitional — the contract calls these Chinese-based Brands
    "wayward_country_cn",     # confirmed
    "cjk_in_name",            # confirmed
    "chinese_email_domain",   # strong
    "chinese_partner",        # strong
    "eric_sheet",             # strong
    "manual_review",          # a human/LLM assertion, WITH a rationale
    "wayward_country_other",  # negative — a real, non-CN ISO country
)
_STRENGTHS = ("definitional", "confirmed", "strong", "moderate", "weak", "negative")


def upgrade() -> None:
    sig = ", ".join(f"'{s}'" for s in _SIGNALS)
    strg = ", ".join(f"'{s}'" for s in _STRENGTHS)

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS ps_nationality_signals (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            wayward_brand_id UUID NOT NULL REFERENCES ps_brands (wayward_brand_id),
            signal          TEXT NOT NULL CHECK (signal IN ({sig})),
            strength        TEXT NOT NULL CHECK (strength IN ({strg})),
            points_to       TEXT NOT NULL CHECK (points_to IN ('china', 'not_china')),
            evidence        TEXT NOT NULL,
            source_system   TEXT NOT NULL,
            asserted_by     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, wayward_brand_id, signal, source_system)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ps_nationality_signals IS "
        "'Every piece of evidence bearing on whether a brand is Chinese — one row per signal, "
        "kept separate from the decision. ~$137k of our claim turns on this question, and a "
        "determination that lives in a chat message cannot be audited, re-run, handed to an LLM, "
        "or defended to Wayward. CHINA WINS: any single positive signal locks the brand as "
        "Chinese; a negative signal only decides a brand when no positive signal exists. A US "
        "country flag is not evidence a brand is not Chinese — it usually means a US-registered "
        "shell.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.signal IS "
        "'on_exclusion_list is DEFINITIONAL — contract §1.4 defines Excluded Brands as ''any and "
        "all Chinese-based Brands'', so the list is a signed instrument asserting Chineseness. "
        "manual_review is a human or LLM assertion and MUST carry a rationale in `evidence` and "
        "a name in `asserted_by`. NOTE what is absent: the BRAND NAME is not a signal. Bob and "
        "Brad is Chinese; AEEZO is Chinese; ''SOUTH KOREA ULIKE GROUP'' is a Shenzhen company. A "
        "name may generate a REVIEW, never a DECISION.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.evidence IS "
        "'WHY this signal fired, in prose, specific enough to defend. ''qq.com email on the brand "
        "contact'', not ''email looked Chinese''. For manual_review this is the reasoning — it is "
        "the difference between a judgement and a guess.'"
    )
    op.execute(
        "COMMENT ON COLUMN ps_nationality_signals.asserted_by IS "
        "'Who made the call. Required for manual_review. Decisions are never anonymous.'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_nat_signals_brand "
        "ON ps_nationality_signals (tenant_id, wayward_brand_id)"
    )
    op.execute("ALTER TABLE ps_nationality_signals ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY ps_nationality_signals_tenant ON ps_nationality_signals
            USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
        """
    )

    # ── the verdict, derived from the signals ───────────────────────────────
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict")
    op.execute(
        """
        CREATE VIEW lens_ps_china_verdict AS
        WITH agg AS (
            SELECT wayward_brand_id,
                   count(*) FILTER (WHERE points_to = 'china')     AS china_signals,
                   count(*) FILTER (WHERE points_to = 'not_china') AS not_china_signals,
                   max(CASE strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5
                                     WHEN 'strong' THEN 4 WHEN 'moderate' THEN 3
                                     WHEN 'weak' THEN 2 ELSE 1 END)
                       FILTER (WHERE points_to = 'china')          AS best_china_rank,
                   string_agg(DISTINCT signal, ', ')
                       FILTER (WHERE points_to = 'china')          AS china_evidence,
                   string_agg(DISTINCT signal, ', ')
                       FILTER (WHERE points_to = 'not_china')      AS not_china_evidence
            FROM ps_nationality_signals
            GROUP BY wayward_brand_id
        ),
        money AS (
            SELECT wayward_brand_id,
                   sum(usage_collected)  AS collected,
                   sum(ps_gross_owed)    AS ps_owed,
                   sum(ps_actually_paid) AS ps_paid
            FROM ps_monthly_earnings
            GROUP BY wayward_brand_id
        )
        SELECT
            b.wayward_brand_id,
            b.brand_name,
            b.signup_date,
            -- CHINA WINS: one positive signal is enough. A negative only decides when nothing
            -- positive exists at all.
            CASE
                WHEN COALESCE(a.china_signals, 0) > 0 THEN 'china'
                WHEN COALESCE(a.not_china_signals, 0) > 0 THEN 'not_china'
                ELSE 'unknown'
            END                                              AS verdict,
            CASE a.best_china_rank
                WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed' WHEN 4 THEN 'strong'
                WHEN 3 THEN 'moderate' WHEN 2 THEN 'weak' ELSE NULL
            END                                              AS verdict_strength,
            a.china_evidence,
            a.not_china_evidence,
            round(m.collected, 2)                            AS usage_collected,
            round(m.ps_owed, 2)                              AS ps_owed_if_china,
            round(m.ps_paid, 2)                              AS ps_paid_today,
            round(COALESCE(m.ps_owed, 0) - COALESCE(m.ps_paid, 0), 2) AS shortfall
        FROM ps_brands b
        LEFT JOIN agg   a ON a.wayward_brand_id = b.wayward_brand_id
        LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id
        WHERE m.collected > 0
        """
    )
    op.execute(
        "COMMENT ON VIEW lens_ps_china_verdict IS "
        "'THE CHINA CALL, per brand, derived from ps_nationality_signals — never hand-edited. "
        "CHINA WINS: one positive signal locks it. Sort by ps_owed_if_china to work the money "
        "top-down; sort by verdict=''unknown'' to see what still needs a human. Every verdict "
        "carries the signals that produced it, so it can be defended line by line to Wayward.'"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_china_verdict TO {r}")
        op.execute(f"GRANT SELECT ON ps_nationality_signals TO {r}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_china_verdict")
    op.execute("DROP TABLE IF EXISTS ps_nationality_signals")
