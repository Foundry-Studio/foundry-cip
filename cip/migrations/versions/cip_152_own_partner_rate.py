# foundry: kind=migration domain=client-intelligence-platform
"""cip_152: own the partner rate in ps_partner_rate (RDL task #5) - finish cip_131's design.

Completes cip_131 without touching the correct money engine. Three additive parts:

  1. Backfill (in this migration). Own EVERY active (party x product) pair at rate_pct=5, basis='default',
     effective_from=2020-01-01, set_by='backfill:cip_152'. Tim ruling 2026-08-03: every partner is 5% from
     when they started, so all 27 active pairs are 5% (including the 3 that currently fall back to all-zero).
     ON CONFLICT DO NOTHING skips the 7 uniform-positive rows cip_131 already owns at 5% and stays idempotent.
     This is NOT money-neutral: the ~20 pairs that fell back to a bimodal 0/5 pc.partner_rate now read 5% for
     ALL their brands, which raises the previously-0 brands to 5% (a deliberate increase in partner owed - the
     correction Tim ordered). The cutover-date mechanism (ps_set_partner_rate) is reserved for FUTURE changes;
     supersedes the earlier go-forward-mixed-pairs plan under decision f3f1e1d6.

  2. ps_set_partner_rate(...) (new SQL function, in this migration). The safe manual set: atomically closes
     the current open interval (effective_to = cutover) and inserts the new open row (effective_from = cutover,
     basis='agreed'), validated, non-retroactive by default (p_allow_retro=false blocks a past cutover). Tim
     runs one line via Claude Code. We do NOT reuse FAS set_rate (it writes ps_partner_registry.default_rate,
     a dead column, wrong key, fraction units, not per-product, not effective-dated).

  3. lens_ps_partner_rate (new view, in this migration). Partner x product grain: current rate_pct + basis +
     effective dates + is_agreed + a jsonb interval history, using the SAME as-of guard as the money engine
     (effective_from <= CURRENT_DATE AND (effective_to IS NULL OR effective_to > CURRENT_DATE), DESC). It feeds
     the agreed-vs-default badge (task #5 -> #53) and a future Partner 360 rate-history block. It does NOT bloat
     lens_ps_product_eligibility (different grain, different consumers).

MUST NOT touch the money engine: this migration does NOT CREATE OR REPLACE lens_ps_commission_ledger or
lens_ps_product_eligibility. mgmt_fee_owed / ps_claim_owed (the recovery number) cannot move because the
partner rate does not feed them.

UNITS: rate_pct is a PERCENT (5.0 = 5%); the engine divides by 100. The table CHECK bounds 0..100; the
function bounds 0..100; the live basis CHECK allows only 'agreed', 'default', or NULL.

downgrade() drops the function and the view and deletes ONLY the set_by='backfill:cip_152' rows. Mixed-pair
rows carry set_by='claude_code' (deliberate data) and are intentionally left in place.

Revision ID: cip_152_own_partner_rate   (24 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_151_days_to_pay
APPLY-TIME (not in file, human-gated): export
FOUNDRY_CIP_EXPECTED_FOREIGN_REVISIONS="<current FAS foreign head>"; apply in one transaction. All 27 pairs
are owned at 5% by the backfill; no separate mixed-pair runbook is needed (Tim ruling 2026-08-03). Capture
partner_fee_owed + china ps_claim_owed before/after: partner owed RISES (the correction), the claim number
must be byte-identical.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_152_own_partner_rate"
down_revision: str | Sequence[str] | None = "cip_151_days_to_pay"
branch_labels = None
depends_on = None

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"
_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")
_WRITER = "ps_reporting_writer"
_RATE_EPOCH = "2020-01-01"  # cip_131 epoch: before any Stripe data, so the zero seed covers every rated period.
_BACKFILL_TAG = "backfill:cip_152"

# ---------------------------------------------------------------------------------------------------------
# Part 1: own EVERY active (party x product) pair at 5% from inception (Tim ruling 2026-08-03: every partner
#   is 5% from when they started; the cutover-date mechanism is only for FUTURE changes). Seeds 5% / default /
#   2020-01-01 for all active pairs; ON CONFLICT skips the 7 uniform-positive rows cip_131 already owns at 5%.
#   NOT money-neutral: the ~20 pairs that fell back to a bimodal 0/5 pc.partner_rate now read 5% for all their
#   brands, raising the previously-0 brands to 5% (a real increase in partner_fee_owed - the intended
#   correction). Does NOT move mgmt_fee_owed / ps_claim_owed: the partner rate never feeds the china claim.
# ---------------------------------------------------------------------------------------------------------
_BACKFILL_ALL_5PCT = f"""
    INSERT INTO ps_partner_rate (tenant_id, party_id, product_id, rate_pct, basis, effective_from, set_by)
    SELECT DISTINCT pc.tenant_id, pc.party_id, pc.product_id, 5, 'default', DATE '{_RATE_EPOCH}', '{_BACKFILL_TAG}'
    FROM ps_partner_credit pc
    WHERE pc.party_id IS NOT NULL AND pc.product_id <> ''
    ON CONFLICT (tenant_id, party_id, product_id, effective_from) DO NOTHING
"""

# ---------------------------------------------------------------------------------------------------------
# Part 3: lens_ps_partner_rate (partner x product; one row per pair with a current interval). Same as-of
#   guard + DESC as lens_ps_commission_ledger, so "current" is consistent everywhere.
# ---------------------------------------------------------------------------------------------------------
_LENS = r"""
CREATE OR REPLACE VIEW lens_ps_partner_rate AS
WITH cur AS (
    SELECT DISTINCT ON (r.party_id, r.product_id)
           r.party_id, r.product_id, r.rate_pct, r.basis,
           r.effective_from, r.effective_to, r.set_by, r.set_at, r.note
    FROM ps_partner_rate r
    WHERE r.effective_from <= CURRENT_DATE
      AND (r.effective_to IS NULL OR r.effective_to > CURRENT_DATE)
    ORDER BY r.party_id, r.product_id, r.effective_from DESC   -- same as-of guard + DESC as the engine
),
hist AS (
    SELECT r.party_id, r.product_id,
           jsonb_agg(jsonb_build_object(
               'rate_pct', r.rate_pct, 'basis', r.basis,
               'effective_from', r.effective_from, 'effective_to', r.effective_to,
               'set_by', r.set_by, 'set_at', r.set_at
           ) ORDER BY r.effective_from DESC) AS history
    FROM ps_partner_rate r
    GROUP BY r.party_id, r.product_id
)
SELECT
    cur.party_id,
    pty.display_name       AS partner_name,
    cur.product_id,
    cur.rate_pct           AS current_rate_pct,
    cur.basis              AS current_basis,
    (cur.basis = 'agreed') AS is_agreed,
    cur.effective_from     AS current_effective_from,
    cur.effective_to       AS current_effective_to,
    cur.set_by, cur.set_at, cur.note,
    hist.history
FROM cur
LEFT JOIN ps_party pty ON pty.party_id = cur.party_id
LEFT JOIN hist ON hist.party_id = cur.party_id AND hist.product_id = cur.product_id;
"""

# ---------------------------------------------------------------------------------------------------------
# Part 2: ps_set_partner_rate(...) - the safe manual set. Atomic close + insert, validated, non-retroactive
#   by default. SECURITY INVOKER (default): works for the FAS superuser path (dbq_runner, BYPASSRLS) and for
#   ps_reporting_writer (the internal set_config satisfies the RLS WITH CHECK). RETURNS the new row.
# ---------------------------------------------------------------------------------------------------------
_FN = r"""
CREATE OR REPLACE FUNCTION ps_set_partner_rate(
    p_party_id    uuid,
    p_product_id  text,
    p_rate_pct    numeric,
    p_cutover     date,
    p_basis       text    DEFAULT 'agreed',
    p_note        text    DEFAULT NULL,
    p_set_by      text    DEFAULT 'claude_code',
    p_allow_retro boolean DEFAULT false,
    p_tenant_id   uuid    DEFAULT '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid
) RETURNS ps_partner_rate
LANGUAGE plpgsql AS $fn$
DECLARE
    v_open ps_partner_rate;
    v_new  ps_partner_rate;
BEGIN
    PERFORM set_config('app.current_tenant', p_tenant_id::text, true);   -- tenant scope for RLS FORCE

    IF p_rate_pct IS NULL OR p_rate_pct < 0 OR p_rate_pct > 100 THEN
        RAISE EXCEPTION 'rate_pct must be a percent 0..100, got %', p_rate_pct;
    END IF;
    IF p_basis IS NOT NULL AND p_basis NOT IN ('agreed','default') THEN
        RAISE EXCEPTION 'basis must be agreed, default, or null';
    END IF;
    IF p_cutover IS NULL THEN
        RAISE EXCEPTION 'cutover date is required';
    END IF;
    IF NOT p_allow_retro AND p_cutover < CURRENT_DATE THEN
        RAISE EXCEPTION 'cutover % is in the past; non-retroactive by default (pass p_allow_retro=>true to override)', p_cutover;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ps_party WHERE party_id = p_party_id AND tenant_id = p_tenant_id) THEN
        RAISE EXCEPTION 'unknown party_id % for this tenant', p_party_id;
    END IF;

    SELECT * INTO v_open FROM ps_partner_rate
     WHERE tenant_id=p_tenant_id AND party_id=p_party_id AND product_id=p_product_id AND effective_to IS NULL
     ORDER BY effective_from DESC LIMIT 1;

    IF v_open.id IS NOT NULL AND v_open.effective_from >= p_cutover THEN
        RAISE EXCEPTION 'cutover % must be after the current interval start % for (%, %)',
              p_cutover, v_open.effective_from, p_party_id, p_product_id;
    END IF;

    -- 1) close the current open interval at the cutover (old rate holds for months < cutover)
    UPDATE ps_partner_rate
       SET effective_to = p_cutover, set_at = now()
     WHERE tenant_id=p_tenant_id AND party_id=p_party_id AND product_id=p_product_id
       AND effective_to IS NULL AND effective_from < p_cutover;

    -- 2) insert the new open interval; UNIQUE(..., effective_from) blocks a duplicate cutover date
    INSERT INTO ps_partner_rate
        (tenant_id, party_id, product_id, rate_pct, basis, effective_from, effective_to, set_by, set_at, note)
    VALUES
        (p_tenant_id, p_party_id, p_product_id, p_rate_pct, p_basis, p_cutover, NULL, p_set_by, now(),
         COALESCE(p_note, 'manual set via Claude Code'))
    RETURNING * INTO v_new;

    RETURN v_new;
END;
$fn$;
"""

_FN_SIG = "ps_set_partner_rate(uuid,text,numeric,date,text,text,text,boolean,uuid)"

_COMMENT_VIEW = (
    "COMMENT ON VIEW lens_ps_partner_rate IS $c$cip_152: current owned partner payout rate per party x "
    "product, plus a full interval history (jsonb, desc). Uses the SAME as-of guard as "
    "lens_ps_commission_ledger (effective_from <= CURRENT_DATE AND (effective_to IS NULL OR effective_to > "
    "CURRENT_DATE), DESC), so current is consistent with the money engine. Read-only reporting lens: feeds "
    "the agreed-vs-default badge (task #53) and Partner 360 rate history. It does NOT feed the money engine.$c$"
)

_COMMENT_FN = (
    "COMMENT ON FUNCTION " + _FN_SIG + " IS $c$cip_152: the safe manual partner-rate set. Atomically closes "
    "the current open interval at p_cutover and inserts a new open row (basis defaults to agreed). "
    "Non-retroactive by default: p_allow_retro=false blocks a cutover before CURRENT_DATE. Validates "
    "rate_pct 0..100, basis in (agreed, default, null), and party existence for the tenant. SECURITY INVOKER; "
    "sets app.current_tenant internally for RLS FORCE. Run one line via Claude Code at a Tim-approved cutover.$c$"
)


def upgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")
    op.execute("SET LOCAL lock_timeout = '5s'")

    # 1. Backfill: own EVERY active (party x product) pair at 5% from inception (Tim ruling 2026-08-03).
    op.execute(_BACKFILL_ALL_5PCT)

    # 3. New rate lens (additive), then grant SELECT to the 4 standard read roles (cip_151 pattern).
    op.execute(_LENS)
    op.execute(f"GRANT SELECT ON lens_ps_partner_rate TO {_READER};")
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON lens_ps_partner_rate TO {role};")

    # 2. Safe manual set function (additive), then grant EXECUTE to the reporting writer role.
    op.execute(_FN)
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FN_SIG} TO {_WRITER};")

    # Provenance comments for the catalog.
    op.execute(_COMMENT_VIEW)
    op.execute(_COMMENT_FN)

    print(
        "cip_152: owned every active partner rate at 5% from inception (Tim ruling 2026-08-03), created "
        "lens_ps_partner_rate (granted to 4 read roles) + ps_set_partner_rate (granted EXECUTE to the writer). "
        "Raises previously-0 brands to 5% (partner owed); mgmt_fee_owed / ps_claim_owed unchanged."
    )


def downgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant', '{PS_TENANT}', true)")
    # Drop the additive objects, then remove ONLY the migration's own money-neutral seed rows.
    # Mixed-pair rows carry set_by='claude_code' (deliberate data) and are intentionally left in place.
    op.execute(f"DROP FUNCTION IF EXISTS {_FN_SIG}")
    op.execute("DROP VIEW IF EXISTS lens_ps_partner_rate")
    op.execute(f"DELETE FROM ps_partner_rate WHERE set_by = '{_BACKFILL_TAG}'")
    print("cip_152 downgrade: dropped ps_set_partner_rate + lens_ps_partner_rate; deleted backfill:cip_152 rows")
