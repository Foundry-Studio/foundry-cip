# foundry: kind=migration domain=client-intelligence-platform
"""cip_46: the real partner roster, a CONFIDENCE dimension, claim lifecycle, commencement.

FOUR THINGS (Tim, 2026-07-13)

1. THE REAL PARTNER ROSTER — the partners who came AFTER PS took over by contract.
   These are contact names AND company names, and the company names are the missing half
   of the identity puzzle:

     Sarah   -- S姐联盟营销        <- S姐 IS SARAH. I had swept S姐 into 'unassigned' via a
                                     bare-'s' type rule. That was WRONG; she is a partner.
     Kerry   -- Snow ball          <- 雪球 LITERALLY MEANS "SNOWBALL". The CJK merge
                                     (雪球 / 雪球站外分享 / xueqiu) was correct AND it is
                                     Kerry's company. Had we ASCII-stripped the CJK, we
                                     would have lost a partner entirely.
     Cassie  -- C姐说品牌
     Mercer  -- Linkbutton
     Fan/Wilson -- Frual
     Jackie/Bella -- Openlight
     Shallow -- Thraive

   NOTE the tension, recorded not resolved: OpenLight and Shallow appear on BOTH the
   contract's EXCLUDED list (§1.4(c),(e)) and this current partner roster. Per Tim: the
   exclusion attaches to the BRANDS already on the excluded/flat-fee lists, not to the
   partner forever — so NEW brands they refer post-contract are eligible. Their OLD
   brands stay excluded.

2. CONFIDENCE IS A FIRST-CLASS DIMENSION. "You won't ALWAYS know" (Tim). A binary
   confirmed/conflict is a lie by omission. Every match now carries:
       confirmed — sources agree, or a human said so
       probable  — we THINK it matches; needs confirmation. NOT a decision yet.
       conflict  — sources disagree; a human must settle it
       unknown   — no evidence
   'probable' is the state that was missing, and it is the one that keeps an honest
   system from either over-claiming or silently dropping a match.

3. CLAIM LIFECYCLE — Tim asked for "reported and awaiting confirmation and
   reconciliation". Added to ps_claims.status, plus 'back_pay' as a claim_type.

4. COMMISSION COMMENCEMENT = 2025-12-01. Revenue before that date is NOT commissionable
   under the current agreement; it is a NEGOTIATION item (an amendment / back-pay ask),
   not a silent zero. Recorded so nobody later assumes pre-Dec revenue was simply absent.

Revision ID: cip_46_partners_confidence
Revises: cip_45_opportunity_lens_fix
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_46_partners_confidence"
down_revision: str | Sequence[str] | None = "cip_45_opportunity_lens_fix"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
COMMISSION_COMMENCEMENT = "2025-12-01"

MATCH_STATES = ("confirmed", "probable", "conflict", "unknown")

# partner_id, display, company, contacts[(name, wechat_or_none)]
ROSTER = [
    ("sarah",   "Sarah",        "S姐联盟营销",   ["Sarah"]),
    ("kerry",   "Kerry",        "Snow ball",     ["Kerry"]),
    ("cassie",  "Cassie",       "C姐说品牌",     ["Cassie"]),
    ("mercer",  "Mercer",       "Linkbutton",    ["Mercer"]),
    ("frual",   "Fan / Wilson", "Frual",         ["Fan", "Wilson"]),
    ("openlight", "Jackie / Bella", "Openlight", ["Jackie", "Bella"]),
    ("shallow", "Shallow",      "Thraive",       ["Shallow"]),
]

# Aliases the roster reveals. The CJK ones are the whole point: without them these
# partners are invisible or, worse, silently split in two.
ALIASES = [
    # sarah — S姐 is Sarah, NOT a referral "type"
    ("sarah", "S姐", "display_name"),
    ("sarah", "S姐联盟营销", "display_name"),
    ("sarah", "Sarah", "display_name"),
    ("sarah", "referral(Sarah)", "referral_tag"),
    ("sarah", "referral(S)", "referral_tag"),
    # kerry — 雪球 == "Snowball" == Kerry's company
    ("kerry", "Snow ball", "display_name"),
    ("kerry", "Snowball", "display_name"),
    ("kerry", "雪球", "display_name"),
    ("kerry", "雪球站外分享", "display_name"),
    ("kerry", "xueqiu", "display_name"),
    ("kerry", "referral(Xueqiu)", "referral_tag"),
    ("kerry", "Kerry", "display_name"),
    # cassie
    ("cassie", "C姐说品牌", "display_name"),
    # mercer
    ("mercer", "Linkbutton", "display_name"),
    ("mercer", "Mercer", "display_name"),
    # frual
    ("frual", "Frual", "display_name"),
    ("frual", "Fan", "display_name"),
    ("frual", "Wilson", "display_name"),
    # openlight
    ("openlight", "Openlight", "display_name"),
    ("openlight", "Jackie", "display_name"),
    ("openlight", "Bella", "display_name"),
    ("openlight", "referral(Bella)", "referral_tag"),
    # shallow
    ("shallow", "Thraive", "display_name"),
]


def _q(s: str) -> str:
    return s.replace("'", "''")


def upgrade() -> None:
    # ── 1. Confidence dimension ─────────────────────────────────────────────
    states = ", ".join(f"'{s}'" for s in MATCH_STATES)
    op.execute(
        f"""
        ALTER TABLE ps_partner_credit
            ADD COLUMN IF NOT EXISTS match_status TEXT
                CHECK (match_status IS NULL OR match_status IN ({states})),
            ADD COLUMN IF NOT EXISTS match_note TEXT
        """
    )
    op.execute(
        "COMMENT ON COLUMN ps_partner_credit.match_status IS "
        "'How SURE are we this partner is right? Tim, 2026-07-13: ''you won''t ALWAYS "
        "know — we need to account for PROBABLE and UNKNOWN''. "
        "''confirmed'' = sources agree, or a human said so. "
        "''probable'' = we THINK it matches and it needs confirmation — NOT a decision "
        "yet, and it must never be billed as if it were. This is the state a binary "
        "confirmed/conflict model silently loses. "
        "''conflict'' = sources disagree; a human must settle it (e.g. a partner claims a "
        "brand Wayward attributes elsewhere). "
        "''unknown'' = no evidence. "
        "match_note carries the WHY, in words.'"
    )
    # nationality gets the same vocabulary — 'probable' was missing there too.
    op.execute(
        "ALTER TABLE cip_clients DROP CONSTRAINT IF EXISTS "
        "cip_clients_nationality_review_status_check"
    )
    op.execute(
        """
        ALTER TABLE cip_clients ADD CONSTRAINT cip_clients_nationality_review_status_check
            CHECK (nationality_review_status IS NULL OR nationality_review_status IN
                   ('pending','probable','confirmed','escalated'))
        """
    )

    # ── 2. Claim lifecycle + back-pay ───────────────────────────────────────
    op.execute("ALTER TABLE ps_claims DROP CONSTRAINT IF EXISTS ps_claims_status_check")
    op.execute(
        """
        ALTER TABLE ps_claims ADD CONSTRAINT ps_claims_status_check
            CHECK (status IN (
                'draft',
                'reported',                -- we have told them
                'awaiting_confirmation',   -- they have it; we await their answer
                'reconciling',             -- both sides comparing numbers
                'sent', 'acknowledged',
                'paid', 'partial', 'rejected', 'abandoned'
            ))
        """
    )
    op.execute(
        "ALTER TABLE ps_claims DROP CONSTRAINT IF EXISTS ps_claims_claim_type_check"
    )
    op.execute(
        """
        ALTER TABLE ps_claims ADD CONSTRAINT ps_claims_claim_type_check
            CHECK (claim_type IS NULL OR claim_type IN (
                'uncredited_chinese', 'mis_tag', 'start_date', 'rate_error',
                'back_pay',        -- revenue BEFORE commission commencement (2025-12-01)
                'short_pay'        -- they paid less than their own report's detail
            ))
        """
    )
    op.execute(
        f"COMMENT ON COLUMN ps_claims.claim_type IS "
        f"'''back_pay'' = revenue earned BEFORE commission commencement "
        f"({COMMISSION_COMMENCEMENT}). NOT commissionable under the current agreement — "
        f"it is a NEGOTIATION / amendment item, not a silent zero. Recorded so nobody "
        f"later assumes the pre-Dec revenue simply did not exist. "
        f"''short_pay'' = Wayward paid LESS than their own report''s detail sums to "
        f"(observed: March -$0.26, April -$0.20).'"
    )
    op.execute(
        f"COMMENT ON COLUMN ps_claims.status IS "
        f"'Lifecycle (Tim, 2026-07-13): draft -> reported -> awaiting_confirmation -> "
        f"reconciling -> paid/partial/rejected. A brand we BELIEVE we are owed on is not "
        f"a claim until it is reported; and it is not settled until they confirm. "
        f"Commission commencement is {COMMISSION_COMMENCEMENT}.'"
    )

    # ── 3. The real partner roster ──────────────────────────────────────────
    for pid, display, company, contacts in ROSTER:
        op.execute(
            f"""
            INSERT INTO ps_partner_registry
                (tenant_id, partner_id, name, company_name, country, status, notes)
            VALUES ('{PS_TENANT}', '{pid}', '{_q(display)}', '{_q(company)}', 'CN',
                    'active',
                    'Current partner roster (post-contract). Tim 2026-07-13.')
            ON CONFLICT (tenant_id, partner_id) DO UPDATE
                SET name = EXCLUDED.name,
                    company_name = EXCLUDED.company_name,
                    country = EXCLUDED.country
            """
        )
        for person in contacts:
            op.execute(
                f"""
                INSERT INTO ps_partner_contacts
                    (tenant_id, partner_id, name, is_primary, notes)
                VALUES ('{PS_TENANT}', '{pid}', '{_q(person)}',
                        {"true" if person == contacts[0] else "false"},
                        'From Tim''s partner roster 2026-07-13. WeChat pending.')
                ON CONFLICT DO NOTHING
                """
            )

    # ── 4. Aliases the roster reveals (incl. the CJK ones) ──────────────────
    for pid, alias, kind in ALIASES:
        op.execute(
            f"""
            INSERT INTO ps_partner_aliases
                (tenant_id, partner_id, alias_value, alias_kind, source, notes)
            VALUES ('{PS_TENANT}', '{pid}', '{_q(alias)}', '{kind}',
                    'tim_roster_2026_07_13',
                    'From Tim''s partner roster: contact names AND company names.')
            ON CONFLICT (tenant_id, alias_kind, alias_value) DO UPDATE
                SET partner_id = EXCLUDED.partner_id,
                    source = EXCLUDED.source,
                    notes = EXCLUDED.notes
            """
        )

    # OpenLight + Shallow sit on BOTH the excluded list and the current roster.
    op.execute(
        f"""
        UPDATE ps_partner_registry SET notes = notes ||
          ' TENSION (recorded, not resolved): this partner also appears on the contract''s
            EXCLUDED list (openlight §1.4(c) / shallow §1.4(e)). Per Tim {COMMISSION_COMMENCEMENT}+:
            the exclusion attaches to the BRANDS already on the excluded/flat-fee lists, NOT to
            the partner in perpetuity — NEW brands they refer post-contract ARE eligible. Their
            OLD brands stay excluded. Do not collapse the two.'
        WHERE tenant_id = '{PS_TENANT}' AND partner_id IN ('openlight','shallow')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM ps_partner_aliases WHERE source='tim_roster_2026_07_13'")
    op.execute(
        "DELETE FROM ps_partner_contacts WHERE notes LIKE 'From Tim%roster 2026-07-13%'"
    )
    op.execute("ALTER TABLE ps_claims DROP CONSTRAINT IF EXISTS ps_claims_claim_type_check")
    op.execute(
        """
        ALTER TABLE ps_claims ADD CONSTRAINT ps_claims_claim_type_check
            CHECK (claim_type IS NULL OR claim_type IN
                   ('uncredited_chinese','mis_tag','start_date','rate_error'))
        """
    )
    op.execute("ALTER TABLE ps_claims DROP CONSTRAINT IF EXISTS ps_claims_status_check")
    op.execute(
        """
        ALTER TABLE ps_claims ADD CONSTRAINT ps_claims_status_check
            CHECK (status IN ('draft','sent','acknowledged','paid','partial',
                              'rejected','abandoned'))
        """
    )
    op.execute(
        "ALTER TABLE cip_clients DROP CONSTRAINT IF EXISTS "
        "cip_clients_nationality_review_status_check"
    )
    op.execute(
        """
        ALTER TABLE cip_clients ADD CONSTRAINT cip_clients_nationality_review_status_check
            CHECK (nationality_review_status IS NULL OR nationality_review_status IN
                   ('pending','confirmed','escalated'))
        """
    )
    op.execute(
        """
        ALTER TABLE ps_partner_credit
            DROP COLUMN IF EXISTS match_note,
            DROP COLUMN IF EXISTS match_status
        """
    )
