# foundry: kind=migration domain=client-intelligence-platform
"""cip_157_legal_research: reclassify the Chinese legal-record signals (amazon_seller_entity,
uspto_trademark_owner, cn_company_name_pinyin) from CLAIMED to RESEARCH tier, and stop RESEARCH-only
signals from producing a 'china' verdict on their own.

Tim's ruling (this migration's mandate): a Chinese Amazon-seller-entity record or a USPTO
trademark-owner record is "needs verification", not a claim. china_tier (cip_156) already labels
these signals correctly today; this migration moves them out of has_claimed into has_research, and
narrows the verdict CASE so a brand resolves to 'china' only when it has a DEFINITIVE or CLAIMED
signal, not a RESEARCH-only one. A brand whose only china-pointing evidence is research-tier now
falls to 'unknown' - it is not asserted not_china, it is simply no longer asserted china.
china_evidence keeps naming the exact signal, so the reason surfaces automatically in the
(unchanged) lens_ps_china_research_queue view, which already selects china_tier = 'research'.

Money guardrail (read this first - this is the number the apply decision is gated on): verified via
a transactional dry run against the live database at authoring time (this exact upgrade() SQL
executed inside a transaction that was always rolled back; never committed, no alembic_version_cip
write). Two different grains move by different amounts and that is expected, not a defect - the
claim/dollar grain is what was guarded, and it lands exactly on target:

  - lens_ps_china_verdict.verdict = 'china' row count: 2375 -> 2362 (13 fewer
    rows, spanning 8 distinct companies - NOT 6; see below for why row count != company count).
  - lens_ps_claim sum(ps_claim_owed) WHERE verdict = 'china': $16868.26 -> $16738.20
    (down exactly $130.06), across 1167 -> 1161 rows. This is the guarded number: only
    the 6 claim-bearing companies drop - aloderma, Baker's Secret, Braddell Optics, Culvani,
    Foonbe, Bakscape - and no other company's claim total moves.
  - china_tier split after: claimed 276 / definitive 2086 / research 13 / not_china 878 /
    unknown 2192 = 5445 (total row count unchanged; china_tier's own CASE, added by cip_156,
    is untouched byte-for-byte by this migration - the split shifts only because 13 rows' signals
    move from the has_claimed test to the has_research test, see splice (a) below).

Why 13 rows / 8 companies, not 6: lens_ps_china_verdict is grained on ps_brands.wayward_brand_id,
one row per signup, not one row per real company. ps_brands.canonical_brand_id links duplicate
signup rows for the same company. Of the 13 rows that lose 'china':
  - 11 rows belong to the 6 named companies (aloderma x2, Baker's Secret x3, Braddell Optics x2 -
    one is the case-variant "BRADDELL OPTICS" - Culvani x2, Bakscape x1, Foonbe x1). Every row of
    each of these 6 companies carries china_evidence that is purely amazon_seller_entity and/or
    uspto_trademark_owner, so the whole company exits china together. These are the only 6
    companies with a nonzero claim, which is why the dollar guardrail is exactly $130.06.
  - 2 rows are a single duplicate ps_brands row each for AIRNEX and for Fitouch. In both cases the
    OTHER (canonical) row for that same company keeps a retained has_claimed signal
    (card_country_hk for AIRNEX's canonical row, card_country_cn for Fitouch's canonical row) and
    so stays verdict = 'china'; only the duplicate row, whose own china_evidence is amazon/uspto-
    only, flips to 'unknown'. Neither company's china status changes and neither row ever had a
    lens_ps_claim entry (checked directly: $0 impact either way). This is accepted as the correct,
    clean application of the rule at the row grain the view actually runs at - lens_ps_china_verdict
    does not dedupe by canonical_brand_id for any signal today, china-related or not, and that
    dedup is out of scope for this migration.

What this migration does, in order:

1. CREATE OR REPLACE VIEW lens_ps_china_verdict. Same 20 existing columns, same names/types/order
   (china_tier stays column 20; verified via pg_attribute before/after in the dry run, byte-for-
   byte identical) - only two edits touch the captured body, each applied via a guarded string
   replace that asserts its anchor occurs EXACTLY ONCE in the captured body (the same convention
   cip_153 and cip_156 use):
     a) in the `agg` CTE, the has_claimed and has_research bool_or(...) aggregates (added by
        cip_156, otherwise untouched) swap which signals they test:
          - has_claimed loses amazon_seller_entity, uspto_trademark_owner, cn_company_name_pinyin
            (9 signals remain: chinese_email_domain, phone_+86, card_country_cn, card_country_hk,
            cjk_in_name, cn_mobile_handle, qq_handle, wechat_handle, shared_owner_mailbox).
          - has_research gains those same 3 signals (5 signals total: pinyin_name_in_email,
            pinyin_contact_name, cn_company_name_pinyin, amazon_seller_entity,
            uspto_trademark_owner).
        has_definitive, `confirming`, legal_not_china, best_china_rank, china_evidence and every
        other aggregate in this CTE are untouched - `confirming` still drives verdict_strength and
        has_conflict exactly as before, it is simply no longer read by the verdict CASE.
     b) the verdict CASE's single automated-signal branch changes from
        `WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text` to
        `WHEN COALESCE(a.has_definitive, false) OR COALESCE(a.has_claimed, false) THEN 'china'::text`.
        The human_not_china / human_china branches (checked first, unchanged) and the
        legal_not_china / ELSE 'unknown' branches (checked last, unchanged) are untouched.
        china_tier's own CASE (added by cip_156) is untouched byte-for-byte - it already reads
        has_research correctly; this migration only changes which tiers the *verdict* CASE reads.
   Both splice points were verified by diffing _ORIG.splitlines() against _NEW.splitlines(): exactly
   3 lines differ (the two agg-CTE lines above and the one verdict-CASE line), same total line
   count, every other line byte-identical.

Not in scope (per this task's own instructions): lens_ps_china_research_queue (already selects
china_tier = 'research'; needs no change, it will surface these brands automatically - the "reason"
Tim wants surfaced is china_evidence, already carried through unmodified), lens_ps_claim,
lens_ps_commission_ledger, ps_brands.canonical_brand_id dedup logic (does not exist in this view
for any signal and is not introduced here).

lens_ps_china_verdict needs no re-GRANT: CREATE OR REPLACE preserves its existing ACL entries
because the column list stays exactly the same - it does not grow, shrink, or reorder.

Verified by a transactional dry run against the live database at authoring time (this exact
upgrade() SQL executed inside a transaction that was always rolled back, never committed; no
alembic_version_cip write, no persisted change). This migration itself was NOT applied to any
database; the guarded prod apply is done separately by the reviewing party.

Revision ID: cip_157_legal_research   (22 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_156_china_tier
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = 'cip_157_legal_research'
down_revision: str | Sequence[str] | None = 'cip_156_china_tier'
branch_labels = None
depends_on = None

_VIEW = "lens_ps_china_verdict"

# Captured verbatim via pg_get_viewdef('lens_ps_china_verdict'::regclass, true) at authoring time
# (byte-for-byte identical to cip_156's _NEW_VERDICT_DEF - confirmed by direct comparison before
# writing this file). This is the body downgrade() restores; upgrade() applies only the two
# guarded splices documented above.
_ORIG_VERDICT_DEF = " WITH agg AS (\n         SELECT s.wayward_brand_id,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,\n            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS confirming,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['wayward_country_cn'::text, 'chinese_partner'::text, 'on_exclusion_list'::text, 'eric_sheet'::text, 'tim_batch_approval'::text]))) AS has_definitive,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['chinese_email_domain'::text, 'phone_+86'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'cjk_in_name'::text, 'cn_mobile_handle'::text, 'qq_handle'::text, 'wechat_handle'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'cn_company_name_pinyin'::text]))) AS has_claimed,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['pinyin_name_in_email'::text, 'pinyin_contact_name'::text]))) AS has_research,\n            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,\n            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,\n            max(\n                CASE s.strength\n                    WHEN 'definitional'::text THEN 6\n                    WHEN 'confirmed'::text THEN 5\n                    WHEN 'strong'::text THEN 4\n                    WHEN 'moderate'::text THEN 3\n                    WHEN 'weak'::text THEN 2\n                    ELSE 1\n                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS best_china_rank,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,\n            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,\n            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by\n           FROM ps_nationality_signals s\n          GROUP BY s.wayward_brand_id\n        ), money AS (\n         SELECT ps_stripe_invoice_lines.wayward_brand_id,\n            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS collected\n           FROM ps_stripe_invoice_lines\n          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL\n          GROUP BY ps_stripe_invoice_lines.wayward_brand_id\n        )\n SELECT b.wayward_brand_id,\n    b.brand_name,\n    b.signup_date,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'china'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS verdict,\n        CASE\n            WHEN a.human_not_china OR a.human_china THEN 'human'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN\n            CASE a.best_china_rank\n                WHEN 6 THEN 'definitional'::text\n                WHEN 5 THEN 'confirmed'::text\n                WHEN 4 THEN 'strong'::text\n                ELSE 'confirmed'::text\n            END\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text\n            ELSE NULL::text\n        END AS verdict_strength,\n    a.china_evidence,\n    a.not_china_evidence,\n    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,\n    a.manual_rationale,\n    a.manual_by,\n    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,\n    COALESCE(st.is_excluded, false) AS is_excluded,\n    st.buckets AS excluded_buckets,\n    m.wayward_brand_id IS NOT NULL AS ever_billed,\n    round(COALESCE(m.collected, 0::numeric) - COALESCE(rf.brand_refund, 0::numeric), 2) AS usage_collected,\n    NULL::numeric AS ps_owed_claimable,\n    NULL::numeric AS ps_paid,\n    NULL::numeric AS shortfall,\n    NULL::numeric AS hypothetical_if_all_claimable,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'definitive'::text\n            WHEN COALESCE(a.has_definitive, false) THEN 'definitive'::text\n            WHEN COALESCE(a.has_claimed, false) THEN 'claimed'::text\n            WHEN COALESCE(a.has_research, false) THEN 'research'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS china_tier\n   FROM ps_brands b\n     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN ( SELECT lens_ps_refund_allocation.wayward_brand_id,\n            sum(lens_ps_refund_allocation.usage_refund_netted) AS brand_refund\n           FROM lens_ps_refund_allocation\n          GROUP BY lens_ps_refund_allocation.wayward_brand_id) rf ON rf.wayward_brand_id = b.wayward_brand_id;"

# _ORIG_VERDICT_DEF with (a) has_claimed / has_research given their post-ruling signal sets and
# (b) the verdict CASE's automated-signal branch reading has_definitive/has_claimed instead of
# confirming. Every other character of _ORIG_VERDICT_DEF is untouched (see docstring for the exact
# splice mechanism and the line-level diff that proves it).
_NEW_VERDICT_DEF = " WITH agg AS (\n         SELECT s.wayward_brand_id,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,\n            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS confirming,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['wayward_country_cn'::text, 'chinese_partner'::text, 'on_exclusion_list'::text, 'eric_sheet'::text, 'tim_batch_approval'::text]))) AS has_definitive,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['chinese_email_domain'::text, 'phone_+86'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'cjk_in_name'::text, 'cn_mobile_handle'::text, 'qq_handle'::text, 'wechat_handle'::text, 'shared_owner_mailbox'::text]))) AS has_claimed,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['pinyin_name_in_email'::text, 'pinyin_contact_name'::text, 'cn_company_name_pinyin'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS has_research,\n            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,\n            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,\n            max(\n                CASE s.strength\n                    WHEN 'definitional'::text THEN 6\n                    WHEN 'confirmed'::text THEN 5\n                    WHEN 'strong'::text THEN 4\n                    WHEN 'moderate'::text THEN 3\n                    WHEN 'weak'::text THEN 2\n                    ELSE 1\n                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS best_china_rank,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,\n            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,\n            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by\n           FROM ps_nationality_signals s\n          GROUP BY s.wayward_brand_id\n        ), money AS (\n         SELECT ps_stripe_invoice_lines.wayward_brand_id,\n            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS collected\n           FROM ps_stripe_invoice_lines\n          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL\n          GROUP BY ps_stripe_invoice_lines.wayward_brand_id\n        )\n SELECT b.wayward_brand_id,\n    b.brand_name,\n    b.signup_date,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'china'::text\n            WHEN COALESCE(a.has_definitive, false) OR COALESCE(a.has_claimed, false) THEN 'china'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS verdict,\n        CASE\n            WHEN a.human_not_china OR a.human_china THEN 'human'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN\n            CASE a.best_china_rank\n                WHEN 6 THEN 'definitional'::text\n                WHEN 5 THEN 'confirmed'::text\n                WHEN 4 THEN 'strong'::text\n                ELSE 'confirmed'::text\n            END\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text\n            ELSE NULL::text\n        END AS verdict_strength,\n    a.china_evidence,\n    a.not_china_evidence,\n    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,\n    a.manual_rationale,\n    a.manual_by,\n    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,\n    COALESCE(st.is_excluded, false) AS is_excluded,\n    st.buckets AS excluded_buckets,\n    m.wayward_brand_id IS NOT NULL AS ever_billed,\n    round(COALESCE(m.collected, 0::numeric) - COALESCE(rf.brand_refund, 0::numeric), 2) AS usage_collected,\n    NULL::numeric AS ps_owed_claimable,\n    NULL::numeric AS ps_paid,\n    NULL::numeric AS shortfall,\n    NULL::numeric AS hypothetical_if_all_claimable,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'definitive'::text\n            WHEN COALESCE(a.has_definitive, false) THEN 'definitive'::text\n            WHEN COALESCE(a.has_claimed, false) THEN 'claimed'::text\n            WHEN COALESCE(a.has_research, false) THEN 'research'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS china_tier\n   FROM ps_brands b\n     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN ( SELECT lens_ps_refund_allocation.wayward_brand_id,\n            sum(lens_ps_refund_allocation.usage_refund_netted) AS brand_refund\n           FROM lens_ps_refund_allocation\n          GROUP BY lens_ps_refund_allocation.wayward_brand_id) rf ON rf.wayward_brand_id = b.wayward_brand_id;"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"CREATE OR REPLACE VIEW {_VIEW} AS {_NEW_VERDICT_DEF}")
    print(
        f"cip_157: reclassified amazon_seller_entity/uspto_trademark_owner/cn_company_name_pinyin "
        f"from CLAIMED to RESEARCH tier on {_VIEW}, and narrowed the verdict CASE to "
        "has_definitive/has_claimed only. verdict='china' row count and lens_ps_claim total both "
        "drop per this migration's docstring money guardrail; china_evidence still names the exact "
        "signal for every affected brand via the unchanged lens_ps_china_research_queue."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"CREATE OR REPLACE VIEW {_VIEW} AS {_ORIG_VERDICT_DEF}")
    print(f"cip_157 downgrade: restored {_VIEW} to its pre-legal-research-tier definition (cip_156 state).")
