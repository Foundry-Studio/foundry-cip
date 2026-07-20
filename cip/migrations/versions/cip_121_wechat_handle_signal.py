# foundry: kind=migration domain=client-intelligence-platform
"""cip_121: generic wechat_handle as a china nationality signal.

WHY (Jake's HubSpot feed now captures WeChat IDs; Tim: "wire wechat_id as a china
signal so it auto-flags", 2026-07-20)
--------------------------------------------------------------------------------
cip_100 split contact WeChat into ``wechat_id`` (handle) + ``wechat_phone``. The
numeric shapes were already covered by confirming signals — a WeChat handle that is
a CN mobile → ``cn_mobile_handle``; a QQ-number handle → ``qq_handle``; a +86 number
→ ``phone_+86``. But 215 of 237 live ``wechat_id`` values are GENERIC handles
(``lzwws25``, ``w2455623084``) that no signal captured. WeChat is China's dominant
business-messaging platform; a brand contact who communicates via a WeChat handle is
Chinese-ecosystem. This promotes ``wechat_handle`` to a first-class CONFIRMING signal
so the verdict counts it — joining its already-confirming numeric siblings
(``cn_mobile_handle`` / ``qq_handle``), for consistency.

The VALUES are generated hourly by the signal-harvest from ps_brand_contacts (see
cip.integration_mesh.sync.signal_harvest — the same run that already produces
eric_sheet / cjk_in_name / chinese_partner). So a NEW brand arriving from Jake's feed
with only a WeChat ID auto-flags china within the hour.

ASYMMETRY (Tim's rule): wechat_handle only ever ADDS china evidence — confirming
set only, never a not_china path. A human ``manual_review`` not_china still WINS
(checked first in the lens), so a brand Tim ruled not_china stays not_china even
with a WeChat handle. Never assume not-china.

BLAST RADIUS: dry-run 2026-07-20 — of 873 brands carrying WeChat/+86 contact
evidence, 869 are ALREADY china; **0 brands flip**, recovery unchanged. Purely
corroborating today; forward-enabling for wechat-only brands.

Revision ID: cip_121_wechat_handle_signal
Revises: cip_120_reporting_reader_role
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_121_wechat_handle_signal"
down_revision: str | Sequence[str] | None = "cip_120_reporting_reader_role"
branch_labels = None
depends_on = None

# Full allowed signal set (cip_116's 20 + wechat_handle). Ordered as the live constraint.
_SIGNALS_NEW = [
    "on_exclusion_list", "wayward_country_cn", "cjk_in_name", "chinese_email_domain",
    "chinese_partner", "eric_sheet", "manual_review", "wayward_country_other", "phone_+86",
    "shared_owner_mailbox", "cn_mobile_handle", "qq_handle", "cn_company_name_pinyin",
    "pinyin_name_in_email", "pinyin_contact_name", "amazon_seller_entity",
    "uspto_trademark_owner", "tim_batch_approval", "card_country_cn", "card_country_hk",
    "wechat_handle",
]
_SIGNALS_OLD = _SIGNALS_NEW[:-1]

# Confirming china signals used by lens_ps_china_verdict (cip_116's 16 + wechat_handle).
_CONFIRM_NEW = [
    "on_exclusion_list", "eric_sheet", "wayward_country_cn", "chinese_email_domain",
    "cjk_in_name", "phone_+86", "qq_handle", "cn_mobile_handle", "cn_company_name_pinyin",
    "shared_owner_mailbox", "amazon_seller_entity", "uspto_trademark_owner",
    "tim_batch_approval", "chinese_partner", "card_country_cn", "card_country_hk",
    "wechat_handle",
]
_CONFIRM_OLD = _CONFIRM_NEW[:-1]


def _arr(items: list[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{s}'::text" for s in items) + "]"


def _constraint(items: list[str]) -> str:
    return (
        "ALTER TABLE ps_nationality_signals DROP CONSTRAINT ps_nationality_signals_signal_check; "
        "ALTER TABLE ps_nationality_signals ADD CONSTRAINT ps_nationality_signals_signal_check "
        f"CHECK (signal = ANY ({_arr(items)}))"
    )


def _lens(confirm: list[str]) -> str:
    arr = _arr(confirm)
    return f"""
CREATE OR REPLACE VIEW lens_ps_china_verdict AS
WITH agg AS (
  SELECT s.wayward_brand_id,
     bool_or(s.signal = 'manual_review' AND s.points_to = 'not_china') AS human_not_china,
     bool_or(s.signal = 'manual_review' AND s.points_to = 'china') AS human_china,
     count(*) FILTER (WHERE s.points_to='china' AND s.signal = ANY ({arr})) AS confirming,
     count(*) FILTER (WHERE s.points_to='not_china' AND s.signal = ANY (ARRAY['amazon_seller_entity'::text,'uspto_trademark_owner'::text])) AS legal_not_china,
     count(*) FILTER (WHERE s.signal='wayward_country_other') AS wayward_says_us,
     max(CASE s.strength WHEN 'definitional' THEN 6 WHEN 'confirmed' THEN 5 WHEN 'strong' THEN 4
                         WHEN 'moderate' THEN 3 WHEN 'weak' THEN 2 ELSE 1 END)
       FILTER (WHERE s.points_to='china' AND s.signal = ANY ({arr})) AS best_china_rank,
     string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='china') AS china_evidence,
     string_agg(DISTINCT s.signal, ', ') FILTER (WHERE s.points_to='not_china') AS not_china_evidence,
     max(s.evidence) FILTER (WHERE s.signal='manual_review') AS manual_rationale,
     max(s.asserted_by) FILTER (WHERE s.signal='manual_review') AS manual_by
  FROM ps_nationality_signals s GROUP BY s.wayward_brand_id
), money AS (
  SELECT wayward_brand_id, sum(amount) FILTER (WHERE invoice_status='paid') AS collected
  FROM ps_stripe_invoice_lines
  WHERE is_ps_base AND product_id IS NOT NULL AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
  GROUP BY wayward_brand_id
)
SELECT b.wayward_brand_id, b.brand_name, b.signup_date,
  CASE WHEN a.human_not_china THEN 'not_china' WHEN a.human_china THEN 'china'
       WHEN COALESCE(a.confirming,0)>0 THEN 'china'
       WHEN COALESCE(a.legal_not_china,0)>0 THEN 'not_china' ELSE 'unknown' END AS verdict,
  CASE WHEN a.human_not_china OR a.human_china THEN 'human'
       WHEN COALESCE(a.confirming,0)>0 THEN
         CASE a.best_china_rank WHEN 6 THEN 'definitional' WHEN 5 THEN 'confirmed' WHEN 4 THEN 'strong' ELSE 'confirmed' END
       WHEN COALESCE(a.legal_not_china,0)>0 THEN 'legal_record' ELSE NULL END AS verdict_strength,
  a.china_evidence, a.not_china_evidence,
  COALESCE(a.wayward_says_us,0)>0 AS corroborates_not_china,
  a.manual_rationale, a.manual_by,
  COALESCE(a.confirming,0)>0 AND COALESCE(a.legal_not_china,0)>0 AS has_conflict,
  COALESCE(st.is_excluded,false) AS is_excluded, st.buckets AS excluded_buckets,
  m.wayward_brand_id IS NOT NULL AS ever_billed,
  round(COALESCE(m.collected,0) - COALESCE(rf.brand_refund,0), 2) AS usage_collected,
  NULL::numeric AS ps_owed_claimable, NULL::numeric AS ps_paid, NULL::numeric AS shortfall,
  NULL::numeric AS hypothetical_if_all_claimable
FROM ps_brands b
  LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id=b.wayward_brand_id
  LEFT JOIN agg a ON a.wayward_brand_id=b.wayward_brand_id
  LEFT JOIN money m ON m.wayward_brand_id=b.wayward_brand_id
  LEFT JOIN (SELECT wayward_brand_id, sum(usage_refund_netted) AS brand_refund
             FROM lens_ps_refund_allocation GROUP BY wayward_brand_id) rf ON rf.wayward_brand_id=b.wayward_brand_id
"""


def upgrade() -> None:
    op.execute(_constraint(_SIGNALS_NEW))
    op.execute(_lens(_CONFIRM_NEW))


def downgrade() -> None:
    # wechat_handle signals violate the old CHECK — remove them first.
    op.execute("DELETE FROM ps_nationality_signals WHERE signal = 'wechat_handle'")
    op.execute(_constraint(_SIGNALS_OLD))
    op.execute(_lens(_CONFIRM_OLD))
