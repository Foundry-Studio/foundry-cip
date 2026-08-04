# foundry: kind=migration domain=client-intelligence-platform
"""cip_156_china_tier: DI-5e. Add a china certainty-tier dimension to the nationality engine.

Money guardrail (read this first): this migration does NOT change any brand's `verdict`. The verdict CASE in
lens_ps_china_verdict is untouched, character for character. The new `china_tier` column is purely additive.
Proof that the tier split cannot move the verdict: the DEFINITIVE signal set (wayward_country_cn,
chinese_partner, on_exclusion_list, eric_sheet, tim_batch_approval) union the CLAIMED signal set
(chinese_email_domain, phone_+86, card_country_cn, card_country_hk, cjk_in_name, cn_mobile_handle, qq_handle,
wechat_handle, shared_owner_mailbox, amazon_seller_entity, uspto_trademark_owner, cn_company_name_pinyin) is
EXACTLY equal, element for element, to the `confirming` signal array the live verdict CASE already tests via
`COALESCE(a.confirming, 0) > 0` (asserted by this migration's own generator script before writing this file, and
re-checked in the rolled-back dry run below). The RESEARCH signals (pinyin_name_in_email, pinyin_contact_name)
are disjoint from `confirming` and were never part of the verdict computation. So "china_tier IN
('definitive','claimed')" is a partition of exactly the same brand set that "verdict='china'" already selects;
this migration only labels the certainty of a verdict that was already being computed, it does not compute a
new one. Grounded at authoring time: lens_ps_china_verdict = 5445 rows, verdict='china' count unchanged
before/after, lens_ps_claim sum(ps_claim_owed) WHERE verdict='china' = exactly $16,868.26 across 1167 rows both
before and after (verified via a transactional dry run that applied this exact upgrade() SQL and was always
rolled back; never committed, no alembic_version_cip write).

What this migration does (DI-5e), in order:

1. CREATE OR REPLACE VIEW lens_ps_china_verdict. Same 19 existing columns, same names/types/order, byte-for-byte
   identical SQL text for every existing expression (verdict, verdict_strength, china_evidence, usage_collected,
   the NULL::numeric placeholders, all CTEs and joins) - only two additive splices touch the captured body:
     a) three new bool_or(...) aggregates in the `agg` CTE, inserted immediately after the existing `confirming`
        aggregate: has_definitive, has_claimed, has_research (one per tier, testing s.points_to = 'china' AND
        s.signal = ANY (<tier's own signal array>)).
     b) one new column appended at the very end of the outer SELECT list (column 20, after
        hypothetical_if_all_claimable, immediately before FROM ps_brands b):

            CASE
                WHEN a.human_not_china THEN 'not_china'
                WHEN a.human_china THEN 'definitive'
                WHEN COALESCE(a.has_definitive, false) THEN 'definitive'
                WHEN COALESCE(a.has_claimed, false) THEN 'claimed'
                WHEN COALESCE(a.has_research, false) THEN 'research'
                WHEN COALESCE(a.legal_not_china, 0) > 0 THEN 'not_china'
                ELSE 'unknown'
            END AS china_tier

     A human manual_review china call (a.human_china) is tiered 'definitive' - a human ruling is treated as the
     strongest possible signal, same tier as the DEFINITIVE automated signals. Both splice points are applied
     via a guarded string replace that asserts its anchor occurs EXACTLY ONCE in the captured body (the same
     convention cip_153's _swapped() uses); the generator additionally re-checks that every non-blank line of
     the captured original still appears verbatim in the new body, so nothing existing was dropped or reworded.

2. CREATE VIEW lens_ps_china_research_queue - a thin additive view over the new tier: the not-yet-claimed
   research queue (brands whose only china-pointing signals are the two RESEARCH-tier ones). GRANT SELECT to
   the same reader roles cip_155 granted (cip_query_reader, ps_reporting_reader, cip_metabase_project_silk,
   cip_twenty_project_silk, metabase_reader_foundry). lens_ps_china_verdict needs no re-GRANT: CREATE OR REPLACE
   preserves its existing ACL entries because the existing column list only grows, it never shrinks or reorders.

   Grounded finding (checked, not a defect): this view returns 0 rows against today's data, not the ~55-61
   originally estimated. Investigated at authoring time: 61 distinct brands carry a RESEARCH-tier signal
   (pinyin_name_in_email x45, pinyin_contact_name x16); 6 of those also carry a stronger DEFINITIVE/CLAIMED
   automated signal (expected, china_tier correctly reads 'definitive'/'claimed' for those); of the remaining
   55, EVERY one already has a manual_review row from Tim - some confirming china, some overriding to
   not_china (e.g. a Korean/Malaysian romanized name misread as Chinese pinyin). Since human_not_china /
   human_china are checked FIRST in the china_tier CASE (by design - a human ruling outranks any automated
   signal), all 55 resolve to 'definitive' or 'not_china' before the has_research branch is ever reached, so
   none land in this queue today. Verified with two positive-control brands via direct dry-run query
   (has_research evaluates true in both; one resolves 'definitive' via human_china, the other 'not_china' via
   human_not_china) - the tier flag itself is correct, and the empty result reflects that pinyin-only signals
   currently have 100% human-review coverage. Shipping it anyway: it will surface automatically the next time a
   new brand's only china signal is a research-tier pinyin match with no human review yet, which is exactly its
   purpose.

3. DROP the 4 legacy china_brands_* lenses (lens_ps_china_brands_all, _onboarded, _producing,
   _by_original_attribution). pg_get_viewdef + pg_depend were re-checked at authoring time: these four have zero
   dependents OUTSIDE this group. A naive pg_depend join (one row per column reference, not de-duplicated) reads
   32 raw rows against lens_ps_china_brands_all; de-duplicated by dependent object it is exactly 2, and both of
   those 2 (lens_ps_china_brands_onboarded, lens_ps_china_brands_producing) are themselves in this drop set - so
   there is no dependent surviving the migration. That intra-group edge does set a required DROP order: the two
   dependents must be dropped before their base view. downgrade() recreates all 4 verbatim from a captured
   pg_get_viewdef snapshot embedded below (pure ASCII SQL - confirmed via .isascii() before embedding, so no
   encoding round-trip risk), in the reverse (base-first) order.

NOT in scope (deferred, per this task's own instructions - both are app-coupled and need the Wayward-
acknowledgement join semantics confirmed with Tim first):
    - lens_ps_china_contention rebuild (chase-Wayward + conflict + research queues). Untouched: it has 3
      dependent views (lens_ps_fee_at_risk, lens_ps_gate_signals, lens_ps_nationality_trail) and review.ts reads
      it directly.
    - The chase-Wayward queue view itself.
    - lens_ps_claim and lens_ps_commission_ledger: untouched, per instructions; lens_ps_claim's dependence on
      lens_ps_china_verdict.verdict is exactly how this migration's own dry run proves the money held.

Verified by a transactional dry run against the live database at authoring time (this exact upgrade() SQL -
the CREATE OR REPLACE, the new view, the drops - executed inside a transaction that was always rolled back,
never committed; no alembic_version_cip write, no persisted change). This migration itself was NOT applied to
any database; the guarded prod apply is done separately by the reviewing party.

Revision ID: cip_156_china_tier   (18 chars <= alembic_version_cip VARCHAR(32))
Revises: cip_155_integrity_checks
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_156_china_tier"
down_revision: str | Sequence[str] | None = "cip_155_integrity_checks"
branch_labels = None
depends_on = None

_VIEW = "lens_ps_china_verdict"
_RESEARCH_VIEW = "lens_ps_china_research_queue"
# Reader roles that every sibling lens grants SELECT to (same list cip_155 used for its new view). A NEW
# view inherits NO grants, so this must be explicit or cip_query_reader / ps_reporting_reader get
# "permission denied" on the new research queue. lens_ps_china_verdict needs no re-GRANT: CREATE OR REPLACE
# preserves its existing ACL entries (append-only column list).
_READER_ROLES = "cip_query_reader, ps_reporting_reader, cip_metabase_project_silk, cip_twenty_project_silk, metabase_reader_foundry"

# Drop order for the 4 retired legacy lenses: lens_ps_china_brands_onboarded and _producing SELECT FROM
# lens_ps_china_brands_all, so they must be dropped before it (Postgres refuses to drop a view something
# else still depends on). lens_ps_china_brands_by_original_attribution has no such relationship and could
# go anywhere in the list; it is placed with the other independent view for readability.
_LEGACY_DROP_ORDER: list[str] = [
    "lens_ps_china_brands_onboarded",
    "lens_ps_china_brands_producing",
    "lens_ps_china_brands_by_original_attribution",
    "lens_ps_china_brands_all",
]
# Reverse (base-first) order for downgrade()'s recreation.
_LEGACY_CREATE_ORDER: list[str] = [
    "lens_ps_china_brands_all",
    "lens_ps_china_brands_onboarded",
    "lens_ps_china_brands_producing",
    "lens_ps_china_brands_by_original_attribution",
]

# Captured verbatim via pg_get_viewdef('lens_ps_china_verdict'::regclass, true) at authoring time. This is
# the byte-for-byte original body downgrade() restores; upgrade() applies only the two additive splices
# documented above (built once, mechanically, by this migration's generator; never hand-retyped).
_ORIG_VERDICT_DEF = " WITH agg AS (\n         SELECT s.wayward_brand_id,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,\n            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS confirming,\n            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,\n            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,\n            max(\n                CASE s.strength\n                    WHEN 'definitional'::text THEN 6\n                    WHEN 'confirmed'::text THEN 5\n                    WHEN 'strong'::text THEN 4\n                    WHEN 'moderate'::text THEN 3\n                    WHEN 'weak'::text THEN 2\n                    ELSE 1\n                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS best_china_rank,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,\n            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,\n            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by\n           FROM ps_nationality_signals s\n          GROUP BY s.wayward_brand_id\n        ), money AS (\n         SELECT ps_stripe_invoice_lines.wayward_brand_id,\n            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS collected\n           FROM ps_stripe_invoice_lines\n          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL\n          GROUP BY ps_stripe_invoice_lines.wayward_brand_id\n        )\n SELECT b.wayward_brand_id,\n    b.brand_name,\n    b.signup_date,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'china'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS verdict,\n        CASE\n            WHEN a.human_not_china OR a.human_china THEN 'human'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN\n            CASE a.best_china_rank\n                WHEN 6 THEN 'definitional'::text\n                WHEN 5 THEN 'confirmed'::text\n                WHEN 4 THEN 'strong'::text\n                ELSE 'confirmed'::text\n            END\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text\n            ELSE NULL::text\n        END AS verdict_strength,\n    a.china_evidence,\n    a.not_china_evidence,\n    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,\n    a.manual_rationale,\n    a.manual_by,\n    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,\n    COALESCE(st.is_excluded, false) AS is_excluded,\n    st.buckets AS excluded_buckets,\n    m.wayward_brand_id IS NOT NULL AS ever_billed,\n    round(COALESCE(m.collected, 0::numeric) - COALESCE(rf.brand_refund, 0::numeric), 2) AS usage_collected,\n    NULL::numeric AS ps_owed_claimable,\n    NULL::numeric AS ps_paid,\n    NULL::numeric AS shortfall,\n    NULL::numeric AS hypothetical_if_all_claimable\n   FROM ps_brands b\n     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN ( SELECT lens_ps_refund_allocation.wayward_brand_id,\n            sum(lens_ps_refund_allocation.usage_refund_netted) AS brand_refund\n           FROM lens_ps_refund_allocation\n          GROUP BY lens_ps_refund_allocation.wayward_brand_id) rf ON rf.wayward_brand_id = b.wayward_brand_id;"

# _ORIG_VERDICT_DEF with (a) has_definitive / has_claimed / has_research appended to the `agg` CTE right
# after `confirming`, and (b) the china_tier CASE appended as the new last column of the outer SELECT.
# Every other character of _ORIG_VERDICT_DEF is untouched (see docstring for the exact splice mechanism).
_NEW_VERDICT_DEF = " WITH agg AS (\n         SELECT s.wayward_brand_id,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,\n            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,\n            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS confirming,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['wayward_country_cn'::text, 'chinese_partner'::text, 'on_exclusion_list'::text, 'eric_sheet'::text, 'tim_batch_approval'::text]))) AS has_definitive,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['chinese_email_domain'::text, 'phone_+86'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'cjk_in_name'::text, 'cn_mobile_handle'::text, 'qq_handle'::text, 'wechat_handle'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'cn_company_name_pinyin'::text]))) AS has_claimed,\n            bool_or(s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['pinyin_name_in_email'::text, 'pinyin_contact_name'::text]))) AS has_research,\n            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,\n            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,\n            max(\n                CASE s.strength\n                    WHEN 'definitional'::text THEN 6\n                    WHEN 'confirmed'::text THEN 5\n                    WHEN 'strong'::text THEN 4\n                    WHEN 'moderate'::text THEN 3\n                    WHEN 'weak'::text THEN 2\n                    ELSE 1\n                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text, 'card_country_cn'::text, 'card_country_hk'::text, 'wechat_handle'::text]))) AS best_china_rank,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,\n            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,\n            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,\n            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by\n           FROM ps_nationality_signals s\n          GROUP BY s.wayward_brand_id\n        ), money AS (\n         SELECT ps_stripe_invoice_lines.wayward_brand_id,\n            sum(ps_stripe_invoice_lines.amount) FILTER (WHERE ps_stripe_invoice_lines.invoice_status = 'paid'::text) AS collected\n           FROM ps_stripe_invoice_lines\n          WHERE ps_stripe_invoice_lines.is_ps_base AND ps_stripe_invoice_lines.product_id IS NOT NULL AND ps_stripe_invoice_lines.wayward_brand_id IS NOT NULL AND ps_stripe_invoice_lines.billing_month IS NOT NULL\n          GROUP BY ps_stripe_invoice_lines.wayward_brand_id\n        )\n SELECT b.wayward_brand_id,\n    b.brand_name,\n    b.signup_date,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'china'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS verdict,\n        CASE\n            WHEN a.human_not_china OR a.human_china THEN 'human'::text\n            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN\n            CASE a.best_china_rank\n                WHEN 6 THEN 'definitional'::text\n                WHEN 5 THEN 'confirmed'::text\n                WHEN 4 THEN 'strong'::text\n                ELSE 'confirmed'::text\n            END\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text\n            ELSE NULL::text\n        END AS verdict_strength,\n    a.china_evidence,\n    a.not_china_evidence,\n    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,\n    a.manual_rationale,\n    a.manual_by,\n    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,\n    COALESCE(st.is_excluded, false) AS is_excluded,\n    st.buckets AS excluded_buckets,\n    m.wayward_brand_id IS NOT NULL AS ever_billed,\n    round(COALESCE(m.collected, 0::numeric) - COALESCE(rf.brand_refund, 0::numeric), 2) AS usage_collected,\n    NULL::numeric AS ps_owed_claimable,\n    NULL::numeric AS ps_paid,\n    NULL::numeric AS shortfall,\n    NULL::numeric AS hypothetical_if_all_claimable,\n        CASE\n            WHEN a.human_not_china THEN 'not_china'::text\n            WHEN a.human_china THEN 'definitive'::text\n            WHEN COALESCE(a.has_definitive, false) THEN 'definitive'::text\n            WHEN COALESCE(a.has_claimed, false) THEN 'claimed'::text\n            WHEN COALESCE(a.has_research, false) THEN 'research'::text\n            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text\n            ELSE 'unknown'::text\n        END AS china_tier\n   FROM ps_brands b\n     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id\n     LEFT JOIN ( SELECT lens_ps_refund_allocation.wayward_brand_id,\n            sum(lens_ps_refund_allocation.usage_refund_netted) AS brand_refund\n           FROM lens_ps_refund_allocation\n          GROUP BY lens_ps_refund_allocation.wayward_brand_id) rf ON rf.wayward_brand_id = b.wayward_brand_id;"

# Thin additive view: the not-yet-claimed research queue (china_tier='research' only).
_RESEARCH_QUEUE_DEF = "SELECT wayward_brand_id, brand_name, china_evidence, usage_collected FROM lens_ps_china_verdict WHERE china_tier = 'research'"

# Captured verbatim via pg_get_viewdef at authoring time; pure ASCII (checked), so this embed round-trips
# exactly. downgrade() recreates all 4 from this dict.
_LEGACY_DEFS: dict[str, str] = {
    'lens_ps_china_brands_onboarded': " SELECT client_id,\n    tenant_id,\n    hubspot_company_id,\n    client_name,\n    initial_intake_route,\n    companion_data,\n    ps_onboarded_status,\n    ps_engagement_health,\n    ps_segment,\n    cip_company_id,\n    company_name,\n    company_domain,\n    company_country,\n    company_industry,\n    ingested_at,\n    refreshed_at\n   FROM lens_ps_china_brands_all\n  WHERE ps_onboarded_status = 'onboarded'::text;",
    'lens_ps_china_brands_producing': " SELECT client_id,\n    tenant_id,\n    hubspot_company_id,\n    client_name,\n    initial_intake_route,\n    companion_data,\n    ps_onboarded_status,\n    ps_engagement_health,\n    ps_segment,\n    cip_company_id,\n    company_name,\n    company_domain,\n    company_country,\n    company_industry,\n    ingested_at,\n    refreshed_at\n   FROM lens_ps_china_brands_all\n  WHERE ps_engagement_health = 'producing'::text;",
    'lens_ps_china_brands_by_original_attribution': ' SELECT d.id AS cip_deal_id,\n    d.client_id,\n    d.tenant_id,\n    d.source_id AS hubspot_deal_id,\n    d.name AS deal_name,\n    cl.name AS client_name,\n    cl.companion_data ->> \'ps_onboarded_status\'::text AS ps_onboarded_status,\n    cl.companion_data ->> \'ps_engagement_health\'::text AS ps_engagement_health,\n    cl.companion_data ->> \'ps_segment\'::text AS ps_segment,\n    d.amount,\n    d.currency,\n    d.close_date,\n    d.stage AS deal_stage,\n    d.pipeline AS deal_pipeline,\n    d.properties ->> \'source\'::text AS attribution_source,\n        CASE\n            WHEN (d.properties ->> \'source\'::text) ~~ \'China Referral - %\'::text THEN "substring"(d.properties ->> \'source\'::text, \'China Referral - (.+)$\'::text)\n            ELSE \'(other)\'::text\n        END AS attribution_sourcer\n   FROM cip_deals d\n     JOIN cip_clients cl ON cl.client_id = d.client_id AND cl.tenant_id = d.tenant_id\n  WHERE d.tenant_id = \'078a37d6-6ae2-4e22-869e-cc08f6cb2787\'::uuid AND d.tenant_id = NULLIF(current_setting(\'app.current_tenant\'::text, true), \'\'::text)::uuid;',
    'lens_ps_china_brands_all': " SELECT cl.client_id,\n    cl.tenant_id,\n    cl.source_id AS hubspot_company_id,\n    cl.name AS client_name,\n    cl.initial_intake_route,\n    cl.companion_data,\n    cl.companion_data ->> 'ps_onboarded_status'::text AS ps_onboarded_status,\n    cl.companion_data ->> 'ps_engagement_health'::text AS ps_engagement_health,\n    cl.companion_data ->> 'ps_segment'::text AS ps_segment,\n    co.id AS cip_company_id,\n    co.name AS company_name,\n    co.domain AS company_domain,\n    co.country AS company_country,\n    co.industry AS company_industry,\n    cl.ingested_at,\n    cl.refreshed_at\n   FROM cip_clients cl\n     LEFT JOIN cip_companies co ON co.source_id = cl.source_id AND co.tenant_id = cl.tenant_id\n  WHERE cl.tenant_id = '078a37d6-6ae2-4e22-869e-cc08f6cb2787'::uuid AND cl.tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid;",
}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # 1) Add the china_tier column (additive; verdict computation untouched, see docstring proof).
    op.execute(f"CREATE OR REPLACE VIEW {_VIEW} AS {_NEW_VERDICT_DEF}")
    # 2) New thin research-queue view over the new tier, plus its reader grants.
    op.execute(f"CREATE VIEW {_RESEARCH_VIEW} AS {_RESEARCH_QUEUE_DEF}")
    op.execute(f"GRANT SELECT ON {_RESEARCH_VIEW} TO {_READER_ROLES}")
    # 3) Retire the 4 unwired legacy china_brands_* lenses (dependents-first order; see comment above).
    for view in _LEGACY_DROP_ORDER:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    print(
        f"cip_156: added china_tier to {_VIEW} (DI-5e), created {_RESEARCH_VIEW}, "
        f"dropped {len(_LEGACY_DROP_ORDER)} retired legacy china_brands_* lenses. "
        "verdict computation unchanged; china claim total is unaffected."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Drop the research queue FIRST: it selects china_tier, and CREATE OR REPLACE below removes that
    # column, which Postgres refuses while a dependent view still references it.
    op.execute(f"DROP VIEW IF EXISTS {_RESEARCH_VIEW}")
    op.execute(f"CREATE OR REPLACE VIEW {_VIEW} AS {_ORIG_VERDICT_DEF}")
    for view in _LEGACY_CREATE_ORDER:
        op.execute(f"CREATE VIEW {view} AS {_LEGACY_DEFS[view]}")
    print(
        f"cip_156 downgrade: restored {_VIEW} to its pre-china_tier definition, dropped {_RESEARCH_VIEW}, "
        f"recreated {len(_LEGACY_CREATE_ORDER)} legacy china_brands_* lenses."
    )

