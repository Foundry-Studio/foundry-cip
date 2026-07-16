# foundry: kind=migration domain=client-intelligence-platform
"""cip_110: retire the frozen ps_monthly_earnings snapshot (Tim, 2026-07-16).

The old earnings WRITER (compute_monthly_earnings.py) was deleted in cip_97, but the frozen table it
produced — ps_monthly_earnings (16,020 rows) — was still LIVE, and the money engine reached into it
transitively: lens_ps_china_verdict (the nationality GATE the ledger joins) carried vestigial money
columns sourced from the frozen snapshot. No LIVE lens read those columns (only a spent dated
one-off and a broken harvester summary tail, both handled here), but anyone querying them got frozen
numbers dressed as current. This migration severs every remaining tie and drops the table.

WHAT MOVES (all CREATE OR REPLACE — column signatures unchanged, no dependent cascade):
  - lens_ps_brand_reality  : ever_billed now EXISTS a live is_ps_base Stripe line (was: frozen row)
  - lens_ps_china_verdict  : usage_collected + ever_billed live from the spine; the 4 engine-derived
                             money columns (ps_owed_claimable/ps_paid/shortfall/hypothetical) are
                             NULLed — they cannot be live-sourced here without a circular dependency
                             (the ledger depends on this lens). Money lives in lens_ps_claim.
  - lens_ps_china_companies: usage_collected live from the spine (per company)

WHAT RETIRES (superseded by the cip_104-109 live engine; zero live consumers beyond the frozen set):
  - lens_ps_claim_reconciliation (superseded by cip_108 lens_ps_wayward_reconciliation)
  - lens_ps_client_statement     (redundant with the live lens_ps_commission_ledger detail)
  - lens_ps_partner_statement + lens_ps_partner_summary (superseded by cip_109
                                 lens_ps_partner_payout_summary)
  - lens_ps_unclaimed            (data-quality role now covered by the invariant suite)

Then DROP TABLE ps_monthly_earnings. The 16,020-row snapshot is archived (audit baseline) at
WORKBENCH/china-audit/archive/ps_monthly_earnings_frozen_snapshot.csv.gz; the downgrade recreates the
(empty) structure — data is inherently not restorable, matching the cip_97 precedent.

The live money engine is UNCHANGED: the ledger reads only v.verdict from lens_ps_china_verdict, which
is derived from ps_nationality_signals (live), not the frozen table. Recovery ($12,035) and the china
headcount are penny/row-identical before and after (verified on prod).

Revision ID: cip_110_retire_frozen_earnings
Revises: cip_109_reporting_lenses
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_110_retire_frozen_earnings"
down_revision: str | Sequence[str] | None = "cip_109_reporting_lenses"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_BRAND_REALITY_LIVE = r""" WITH ev AS (
         SELECT b.wayward_brand_id,
            b.brand_name,
            (EXISTS ( SELECT 1
                   FROM ps_stripe_invoice_lines m
                  WHERE m.wayward_brand_id = b.wayward_brand_id AND m.is_ps_base AND m.product_id IS NOT NULL AND m.billing_month IS NOT NULL)) AS ever_billed,
            (EXISTS ( SELECT 1
                   FROM ps_brand_observations o
                  WHERE o.wayward_brand_id = b.wayward_brand_id AND o.source_system ~~ 'slack:%%%%'::text)) AS wayward_onboarded_them,
            (EXISTS ( SELECT 1
                   FROM ps_product_subscriptions s
                  WHERE s.wayward_brand_id = b.wayward_brand_id)) AS has_subscription,
            (EXISTS ( SELECT 1
                   FROM ps_brand_contacts ct
                  WHERE ct.wayward_brand_id = b.wayward_brand_id)) AS has_contact,
            (EXISTS ( SELECT 1
                   FROM ps_excluded_brands x
                  WHERE x.wayward_brand_id = b.wayward_brand_id)) AS on_a_frozen_list,
            b.seen_in_eric_sheets AS on_eric_sheet,
            (EXISTS ( SELECT 1
                   FROM ps_stripe_customers s
                  WHERE s.wayward_brand_id = b.wayward_brand_id AND s.email ~* '@(wayward|artica)\.'::text)) AS staff_mailbox,
            (lower(btrim(COALESCE(b.brand_name, ''::text))) = ANY (ARRAY['1'::text, 'none'::text, 'generic'::text, 'brand'::text, 'brand 2'::text, 'brand co'::text, 'brand test'::text, 'test'::text, 'c'::text, 'country'::text, 'n/a'::text, 'na'::text, '-'::text, '.'::text, 'null'::text, 'x'::text, 'acme'::text, 'adore'::text, 'adores'::text, 'brand_test_2'::text, '1234'::text, '777'::text])) OR b.brand_name ~* '^(test|brand_test|demo|sample)'::text OR b.brand_name IS NULL OR btrim(b.brand_name) = ''::text AS placeholder_name
           FROM ps_brands b
        )
 SELECT wayward_brand_id,
    brand_name,
    ever_billed,
    wayward_onboarded_them,
    has_subscription,
    has_contact,
    on_a_frozen_list,
    on_eric_sheet,
    staff_mailbox,
    placeholder_name,
        CASE
            WHEN ever_billed OR wayward_onboarded_them OR has_subscription OR has_contact OR on_a_frozen_list OR on_eric_sheet THEN 'REAL'::text
            WHEN staff_mailbox OR placeholder_name THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality
   FROM ev"""

_CHINA_VERDICT_LIVE = r""" WITH agg AS (
         SELECT s.wayward_brand_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by
           FROM ps_nationality_signals s
          GROUP BY s.wayward_brand_id
        ), money AS (
         SELECT wayward_brand_id,
            sum(amount) FILTER (WHERE invoice_status = 'paid') AS collected
           FROM ps_stripe_invoice_lines
          WHERE is_ps_base AND product_id IS NOT NULL
            AND wayward_brand_id IS NOT NULL AND billing_month IS NOT NULL
          GROUP BY wayward_brand_id
        )
 SELECT b.wayward_brand_id,
    b.brand_name,
    b.signup_date,
        CASE
            WHEN a.human_not_china THEN 'not_china'::text
            WHEN a.human_china THEN 'china'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN a.human_not_china OR a.human_china THEN 'human'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN
            CASE a.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    a.china_evidence,
    a.not_china_evidence,
    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    a.manual_rationale,
    a.manual_by,
    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,
    COALESCE(st.is_excluded, false) AS is_excluded,
    st.buckets AS excluded_buckets,
    m.wayward_brand_id IS NOT NULL AS ever_billed,
    round(COALESCE(m.collected, 0), 2) AS usage_collected,
    NULL::numeric AS ps_owed_claimable,
    NULL::numeric AS ps_paid,
    NULL::numeric AS shortfall,
    NULL::numeric AS hypothetical_if_all_claimable
   FROM ps_brands b
     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id"""

_CHINA_COMPANIES_LIVE = r""" WITH member AS (
         SELECT b.wayward_brand_id,
            COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
            b.brand_name,
            b.canonical_brand_id IS NOT NULL AND b.canonical_brand_id <> b.wayward_brand_id AS is_alias_row
           FROM ps_brands b
        ), sig AS (
         SELECT m.company_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS decided_by
           FROM member m
             LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), shape AS (
         SELECT m.company_id,
            count(*) AS sibling_rows,
            min(m.brand_name) FILTER (WHERE NOT m.is_alias_row) AS head_name,
            min(m.brand_name) AS any_name,
            bool_or(r.reality = 'REAL'::text) AS is_real,
            bool_or(r.reality = 'JUNK'::text) AS any_row_junk,
            bool_or(r.ever_billed) AS ever_billed,
            bool_or(r.wayward_onboarded_them) AS onboarded,
            bool_or(r.on_a_frozen_list) AS on_a_frozen_list,
            bool_or(r.on_eric_sheet) AS on_eric_sheet
           FROM member m
             JOIN lens_ps_brand_reality r ON r.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), money AS (
         SELECT m.company_id,
            round(sum(l.amount) FILTER (WHERE l.invoice_status = 'paid'), 2) AS usage_collected
           FROM member m
             JOIN ps_stripe_invoice_lines l ON l.wayward_brand_id = m.wayward_brand_id
          WHERE l.is_ps_base AND l.product_id IS NOT NULL AND l.billing_month IS NOT NULL
          GROUP BY m.company_id
        )
 SELECT sh.company_id,
    COALESCE(sh.head_name, sh.any_name) AS company_name,
        CASE
            WHEN sg.human_not_china THEN 'not_china'::text
            WHEN sg.human_china THEN 'china'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN sg.human_not_china OR sg.human_china THEN 'human'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN
            CASE sg.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    sg.china_evidence,
    sg.not_china_evidence,
    COALESCE(sg.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    sg.decided_by,
    sh.sibling_rows,
    sh.sibling_rows > 1 AS is_split_identity,
        CASE
            WHEN sh.is_real THEN 'REAL'::text
            WHEN sh.any_row_junk THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality,
    sh.ever_billed,
    sh.onboarded,
    sh.on_a_frozen_list,
    sh.on_eric_sheet,
    mo.usage_collected
   FROM shape sh
     JOIN sig sg ON sg.company_id = sh.company_id
     LEFT JOIN money mo ON mo.company_id = sh.company_id"""

_BRAND_REALITY_FROZEN = r""" WITH ev AS (
         SELECT b.wayward_brand_id,
            b.brand_name,
            (EXISTS ( SELECT 1
                   FROM ps_monthly_earnings m
                  WHERE m.wayward_brand_id = b.wayward_brand_id)) AS ever_billed,
            (EXISTS ( SELECT 1
                   FROM ps_brand_observations o
                  WHERE o.wayward_brand_id = b.wayward_brand_id AND o.source_system ~~ 'slack:%%%%'::text)) AS wayward_onboarded_them,
            (EXISTS ( SELECT 1
                   FROM ps_product_subscriptions s
                  WHERE s.wayward_brand_id = b.wayward_brand_id)) AS has_subscription,
            (EXISTS ( SELECT 1
                   FROM ps_brand_contacts ct
                  WHERE ct.wayward_brand_id = b.wayward_brand_id)) AS has_contact,
            (EXISTS ( SELECT 1
                   FROM ps_excluded_brands x
                  WHERE x.wayward_brand_id = b.wayward_brand_id)) AS on_a_frozen_list,
            b.seen_in_eric_sheets AS on_eric_sheet,
            (EXISTS ( SELECT 1
                   FROM ps_stripe_customers s
                  WHERE s.wayward_brand_id = b.wayward_brand_id AND s.email ~* '@(wayward|artica)\.'::text)) AS staff_mailbox,
            (lower(btrim(COALESCE(b.brand_name, ''::text))) = ANY (ARRAY['1'::text, 'none'::text, 'generic'::text, 'brand'::text, 'brand 2'::text, 'brand co'::text, 'brand test'::text, 'test'::text, 'c'::text, 'country'::text, 'n/a'::text, 'na'::text, '-'::text, '.'::text, 'null'::text, 'x'::text, 'acme'::text, 'adore'::text, 'adores'::text, 'brand_test_2'::text, '1234'::text, '777'::text])) OR b.brand_name ~* '^(test|brand_test|demo|sample)'::text OR b.brand_name IS NULL OR btrim(b.brand_name) = ''::text AS placeholder_name
           FROM ps_brands b
        )
 SELECT wayward_brand_id,
    brand_name,
    ever_billed,
    wayward_onboarded_them,
    has_subscription,
    has_contact,
    on_a_frozen_list,
    on_eric_sheet,
    staff_mailbox,
    placeholder_name,
        CASE
            WHEN ever_billed OR wayward_onboarded_them OR has_subscription OR has_contact OR on_a_frozen_list OR on_eric_sheet THEN 'REAL'::text
            WHEN staff_mailbox OR placeholder_name THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality
   FROM ev"""

_CHINA_VERDICT_FROZEN = r""" WITH agg AS (
         SELECT s.wayward_brand_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.evidence) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_rationale,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS manual_by
           FROM ps_nationality_signals s
          GROUP BY s.wayward_brand_id
        ), money AS (
         SELECT e.wayward_brand_id,
            sum(e.usage_collected) AS collected,
            sum(e.ps_gross_owed) AS gross_if_claimable,
            sum(e.ps_gross_owed) FILTER (WHERE e.is_claimable) AS ps_owed,
            sum(e.ps_actually_paid) FILTER (WHERE e.is_claimable) AS ps_paid
           FROM ps_monthly_earnings e
          GROUP BY e.wayward_brand_id
        )
 SELECT b.wayward_brand_id,
    b.brand_name,
    b.signup_date,
        CASE
            WHEN a.human_not_china THEN 'not_china'::text
            WHEN a.human_china THEN 'china'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN a.human_not_china OR a.human_china THEN 'human'::text
            WHEN COALESCE(a.confirming, 0::bigint) > 0 THEN
            CASE a.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(a.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    a.china_evidence,
    a.not_china_evidence,
    COALESCE(a.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    a.manual_rationale,
    a.manual_by,
    COALESCE(a.confirming, 0::bigint) > 0 AND COALESCE(a.legal_not_china, 0::bigint) > 0 AS has_conflict,
    COALESCE(st.is_excluded, false) AS is_excluded,
    st.buckets AS excluded_buckets,
    m.wayward_brand_id IS NOT NULL AS ever_billed,
    round(m.collected, 2) AS usage_collected,
    round(COALESCE(m.ps_owed, 0::numeric), 2) AS ps_owed_claimable,
    round(COALESCE(m.ps_paid, 0::numeric), 2) AS ps_paid,
    round(COALESCE(m.ps_owed, 0::numeric) - COALESCE(m.ps_paid, 0::numeric), 2) AS shortfall,
    round(m.gross_if_claimable, 2) AS hypothetical_if_all_claimable
   FROM ps_brands b
     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN agg a ON a.wayward_brand_id = b.wayward_brand_id
     LEFT JOIN money m ON m.wayward_brand_id = b.wayward_brand_id"""

_CHINA_COMPANIES_FROZEN = r""" WITH member AS (
         SELECT b.wayward_brand_id,
            COALESCE(b.canonical_brand_id, b.wayward_brand_id) AS company_id,
            b.brand_name,
            b.canonical_brand_id IS NOT NULL AND b.canonical_brand_id <> b.wayward_brand_id AS is_alias_row
           FROM ps_brands b
        ), sig AS (
         SELECT m.company_id,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'not_china'::text) AS human_not_china,
            bool_or(s.signal = 'manual_review'::text AND s.points_to = 'china'::text) AS human_china,
            count(*) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS confirming,
            count(*) FILTER (WHERE s.points_to = 'not_china'::text AND (s.signal = ANY (ARRAY['amazon_seller_entity'::text, 'uspto_trademark_owner'::text]))) AS legal_not_china,
            count(*) FILTER (WHERE s.signal = 'wayward_country_other'::text) AS wayward_says_us,
            max(
                CASE s.strength
                    WHEN 'definitional'::text THEN 6
                    WHEN 'confirmed'::text THEN 5
                    WHEN 'strong'::text THEN 4
                    WHEN 'moderate'::text THEN 3
                    WHEN 'weak'::text THEN 2
                    ELSE 1
                END) FILTER (WHERE s.points_to = 'china'::text AND (s.signal = ANY (ARRAY['on_exclusion_list'::text, 'eric_sheet'::text, 'wayward_country_cn'::text, 'chinese_email_domain'::text, 'cjk_in_name'::text, 'phone_+86'::text, 'qq_handle'::text, 'cn_mobile_handle'::text, 'cn_company_name_pinyin'::text, 'shared_owner_mailbox'::text, 'amazon_seller_entity'::text, 'uspto_trademark_owner'::text, 'tim_batch_approval'::text, 'chinese_partner'::text]))) AS best_china_rank,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'china'::text) AS china_evidence,
            string_agg(DISTINCT s.signal, ', '::text) FILTER (WHERE s.points_to = 'not_china'::text) AS not_china_evidence,
            max(s.asserted_by) FILTER (WHERE s.signal = 'manual_review'::text) AS decided_by
           FROM member m
             LEFT JOIN ps_nationality_signals s ON s.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), shape AS (
         SELECT m.company_id,
            count(*) AS sibling_rows,
            min(m.brand_name) FILTER (WHERE NOT m.is_alias_row) AS head_name,
            min(m.brand_name) AS any_name,
            bool_or(r.reality = 'REAL'::text) AS is_real,
            bool_or(r.reality = 'JUNK'::text) AS any_row_junk,
            bool_or(r.ever_billed) AS ever_billed,
            bool_or(r.wayward_onboarded_them) AS onboarded,
            bool_or(r.on_a_frozen_list) AS on_a_frozen_list,
            bool_or(r.on_eric_sheet) AS on_eric_sheet
           FROM member m
             JOIN lens_ps_brand_reality r ON r.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        ), money AS (
         SELECT m.company_id,
            round(sum(e.usage_collected), 2) AS usage_collected
           FROM member m
             JOIN ps_monthly_earnings e ON e.wayward_brand_id = m.wayward_brand_id
          GROUP BY m.company_id
        )
 SELECT sh.company_id,
    COALESCE(sh.head_name, sh.any_name) AS company_name,
        CASE
            WHEN sg.human_not_china THEN 'not_china'::text
            WHEN sg.human_china THEN 'china'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN 'china'::text
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'not_china'::text
            ELSE 'unknown'::text
        END AS verdict,
        CASE
            WHEN sg.human_not_china OR sg.human_china THEN 'human'::text
            WHEN COALESCE(sg.confirming, 0::bigint) > 0 THEN
            CASE sg.best_china_rank
                WHEN 6 THEN 'definitional'::text
                WHEN 5 THEN 'confirmed'::text
                WHEN 4 THEN 'strong'::text
                ELSE 'confirmed'::text
            END
            WHEN COALESCE(sg.legal_not_china, 0::bigint) > 0 THEN 'legal_record'::text
            ELSE NULL::text
        END AS verdict_strength,
    sg.china_evidence,
    sg.not_china_evidence,
    COALESCE(sg.wayward_says_us, 0::bigint) > 0 AS corroborates_not_china,
    sg.decided_by,
    sh.sibling_rows,
    sh.sibling_rows > 1 AS is_split_identity,
        CASE
            WHEN sh.is_real THEN 'REAL'::text
            WHEN sh.any_row_junk THEN 'JUNK'::text
            ELSE 'GHOST'::text
        END AS reality,
    sh.ever_billed,
    sh.onboarded,
    sh.on_a_frozen_list,
    sh.on_eric_sheet,
    mo.usage_collected
   FROM shape sh
     JOIN sig sg ON sg.company_id = sh.company_id
     LEFT JOIN money mo ON mo.company_id = sh.company_id"""

_CLAIM_RECONCILIATION = r""" WITH canon AS (
         SELECT ps_brands.wayward_brand_id,
            COALESCE(ps_brands.canonical_brand_id, ps_brands.wayward_brand_id) AS canon_id
           FROM ps_brands
        ), owed AS (
         SELECT c.canon_id,
            sum(e.ps_gross_owed) FILTER (WHERE e.is_claimable) AS ps_owed,
            sum(e.usage_collected) FILTER (WHERE e.is_claimable) AS collected,
            string_agg(DISTINCT e.claim_basis, ', '::text) FILTER (WHERE e.is_claimable) AS claim_basis
           FROM ps_monthly_earnings e
             JOIN canon c ON c.wayward_brand_id = e.wayward_brand_id
          GROUP BY c.canon_id
        ), paid AS (
         SELECT c.canon_id,
            sum(p_1.rev_share_stated) AS ps_paid
           FROM ps_payment_events p_1
             JOIN canon c ON c.wayward_brand_id = p_1.wayward_brand_id
          GROUP BY c.canon_id
        )
 SELECT b.wayward_brand_id,
    b.brand_name,
    COALESCE(o.ps_owed, 0::numeric) AS ps_owed,
    COALESCE(p.ps_paid, 0::numeric) AS ps_paid,
    round(COALESCE(o.ps_owed, 0::numeric) - COALESCE(p.ps_paid, 0::numeric), 2) AS balance,
        CASE
            WHEN COALESCE(o.ps_owed, 0::numeric) > 0::numeric AND COALESCE(p.ps_paid, 0::numeric) = 0::numeric THEN 'owed_never_paid'::text
            WHEN COALESCE(o.ps_owed, 0::numeric) > (COALESCE(p.ps_paid, 0::numeric) + 0.01) THEN 'underpaid'::text
            WHEN COALESCE(p.ps_paid, 0::numeric) > (COALESCE(o.ps_owed, 0::numeric) + 0.01) AND COALESCE(o.ps_owed, 0::numeric) > 0::numeric THEN 'OVERPAID'::text
            WHEN COALESCE(o.ps_owed, 0::numeric) = 0::numeric AND COALESCE(p.ps_paid, 0::numeric) > 0::numeric THEN 'PAID_ON_A_BRAND_WE_DO_NOT_CLAIM'::text
            ELSE 'square'::text
        END AS status,
    round(o.collected, 2) AS usage_collected,
    o.claim_basis,
    st.is_excluded,
    st.buckets AS excluded_buckets
   FROM ps_brands b
     LEFT JOIN owed o ON o.canon_id = b.wayward_brand_id
     LEFT JOIN paid p ON p.canon_id = b.wayward_brand_id
     LEFT JOIN lens_ps_exclusion_status st ON st.wayward_brand_id = b.wayward_brand_id
  WHERE b.canonical_brand_id IS NULL AND (COALESCE(o.ps_owed, 0::numeric) <> 0::numeric OR COALESCE(p.ps_paid, 0::numeric) <> 0::numeric)"""

_CLIENT_STATEMENT = r""" SELECT e.wayward_brand_id,
    e.brand_name,
    e.period_month,
    e.product_id,
    round(e.usage_billed, 2) AS fees_billed,
    round(e.usage_collected, 2) AS fees_paid,
    round(e.usage_outstanding, 2) AS fees_outstanding,
    round(e.usage_voided, 2) AS fees_voided,
    s.productive_date AS first_sale_month,
    s.reactivated_at,
    s.dormant_since
   FROM ps_monthly_earnings e
     LEFT JOIN ps_product_subscriptions s ON s.wayward_brand_id = e.wayward_brand_id AND s.product_id = e.product_id AND s.tenant_id = e.tenant_id"""

_PARTNER_STATEMENT = r""" SELECT e.partner_id,
    r.name AS partner_name,
    r.company_name,
    e.period_month,
    e.wayward_brand_id,
    e.brand_name,
    e.product_id,
    round(e.usage_collected, 2) AS usage_fees_collected,
    round(e.usage_outstanding, 2) AS billed_not_yet_collected,
    e.partner_rate_pct AS your_rate_pct,
    round(e.partner_owed, 2) AS you_earned,
    pc.credit_start AS your_window_opened,
    pc.credit_end AS your_window_closes,
    e.period_month >= pc.credit_end AS window_expired,
    e.months_since_productive
   FROM ps_monthly_earnings e
     JOIN ps_partner_registry r ON r.partner_id = e.partner_id AND r.tenant_id = e.tenant_id
     LEFT JOIN ps_partner_credit pc ON pc.wayward_brand_id = e.wayward_brand_id AND pc.product_id = e.product_id AND pc.tenant_id = e.tenant_id
  WHERE e.partner_id IS NOT NULL AND e.partner_id <> 'unassigned'::text AND e.is_claimable"""

_PARTNER_SUMMARY = r""" SELECT partner_id,
    partner_name,
    company_name,
    count(DISTINCT wayward_brand_id) AS brands,
    count(DISTINCT wayward_brand_id) FILTER (WHERE NOT window_expired) AS brands_still_earning,
    min(period_month) AS first_month,
    max(period_month) AS latest_month,
    round(sum(usage_fees_collected), 2) AS usage_collected,
    round(sum(billed_not_yet_collected), 2) AS in_the_pipeline,
    round(sum(you_earned), 2) AS earned_to_date,
    min(your_window_closes) FILTER (WHERE NOT window_expired) AS next_window_closes
   FROM lens_ps_partner_statement s
  GROUP BY partner_id, partner_name, company_name"""

_UNCLAIMED = r""" SELECT claim_basis,
    product_id,
    count(DISTINCT wayward_brand_id) AS brands,
    count(*) AS brand_months,
    round(sum(usage_collected), 2) AS usage_collected,
    round(sum(ps_gross_owed), 2) AS ps_owed_gross,
    round(sum(ps_actually_paid), 2) AS ps_paid,
    round(sum(ps_gross_owed) - sum(ps_actually_paid), 2) AS shortfall,
    count(*) FILTER (WHERE ps_rate_pct IS NULL) AS rows_unknown_rate,
    count(*) FILTER (WHERE partner_rate_pct IS NULL) AS rows_unknown_partner
   FROM ps_monthly_earnings e
  WHERE is_claimable
  GROUP BY claim_basis, product_id"""

# full evolved DDL of the frozen table, captured from prod at cip_109 (26 cols, PK/UNIQUE/2 FK/4 CHECK,
# 2 indexes) — recreates the empty structure faithfully on downgrade.
_FROZEN_DDL = [
    r"""CREATE TABLE ps_monthly_earnings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    client_id uuid,
    wayward_brand_id uuid,
    brand_name text,
    product_id text NOT NULL,
    period_month date NOT NULL,
    usage_billed numeric(14,2) DEFAULT 0 NOT NULL,
    usage_collected numeric(14,2) DEFAULT 0 NOT NULL,
    usage_outstanding numeric(14,2) GENERATED ALWAYS AS ((usage_billed - usage_collected)) STORED,
    ps_rate_pct numeric(5,2),
    months_since_productive integer,
    partner_id text,
    partner_rate_pct numeric(5,2),
    ps_actually_paid numeric(14,2) DEFAULT 0 NOT NULL,
    eligibility text,
    excluded_bucket text,
    is_chinese boolean,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    ps_gross_owed numeric(14,2) GENERATED ALWAYS AS (round(((usage_collected * ps_rate_pct) / 100.0), 2)) STORED,
    is_claimable boolean,
    claim_basis text,
    usage_voided numeric(14,2),
    partner_owed numeric(14,2) GENERATED ALWAYS AS (round(((usage_collected * partner_rate_pct) / 100.0), 2)) STORED,
    ps_net_owed numeric(14,2) GENERATED ALWAYS AS ((round(((usage_collected * ps_rate_pct) / 100.0), 2) - round(((usage_collected * partner_rate_pct) / 100.0), 2))) STORED,
    variance numeric(14,2) GENERATED ALWAYS AS (((round(((usage_collected * ps_rate_pct) / 100.0), 2) - round(((usage_collected * partner_rate_pct) / 100.0), 2)) - ps_actually_paid)) STORED
)""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_claim_basis CHECK (((claim_basis IS NULL) OR (claim_basis = ANY (ARRAY['boost_all_brands'::text, 'rule_a_post_takeover'::text, 'rule_b_december'::text, 'reactivation_flat_fee'::text, 'not_claimable_excluded'::text, 'not_claimable_not_chinese'::text, 'not_claimable_pre_takeover'::text, 'unknown_nationality'::text]))))""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_month_is_first CHECK ((period_month = (date_trunc('month'::text, (period_month)::timestamp with time zone))::date))""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_partner_rate CHECK (((partner_rate_pct IS NULL) OR ((partner_rate_pct >= (0)::numeric) AND (partner_rate_pct <= (10)::numeric))))""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ck_earnings_rate CHECK (((ps_rate_pct IS NULL) OR (ps_rate_pct = ANY (ARRAY[(3)::numeric, (6)::numeric, (10)::numeric]))))""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT fk_ps_monthly_earnings_brand FOREIGN KEY (wayward_brand_id) REFERENCES ps_brands(wayward_brand_id) ON DELETE RESTRICT""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ps_monthly_earnings_product_fk FOREIGN KEY (tenant_id, product_id) REFERENCES ps_products(tenant_id, product_id) ON DELETE RESTRICT""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ps_monthly_earnings_pkey PRIMARY KEY (id)""",
    r"""ALTER TABLE ps_monthly_earnings ADD CONSTRAINT ps_monthly_earnings_tenant_id_wayward_brand_id_product_id_p_key UNIQUE (tenant_id, wayward_brand_id, product_id, period_month)""",
    r"""CREATE INDEX idx_ps_earn_month ON public.ps_monthly_earnings USING btree (tenant_id, period_month, product_id)""",
    r"""CREATE INDEX idx_ps_earn_partner ON public.ps_monthly_earnings USING btree (tenant_id, partner_id, period_month)""",
]


def upgrade() -> None:
    # 1. repoint the three live lenses off the frozen snapshot (signatures unchanged -> no cascade)
    op.execute("CREATE OR REPLACE VIEW lens_ps_brand_reality AS " + _BRAND_REALITY_LIVE)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_verdict AS " + _CHINA_VERDICT_LIVE)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_companies AS " + _CHINA_COMPANIES_LIVE)
    # 2. retire the superseded frozen-era reporting lenses (dependents first)
    for name in ("lens_ps_partner_summary", "lens_ps_partner_statement", "lens_ps_client_statement",
                 "lens_ps_claim_reconciliation", "lens_ps_unclaimed"):
        op.execute(f"DROP VIEW IF EXISTS {name}")
    # 3. the frozen snapshot itself — nothing references it anymore
    op.execute("DROP TABLE IF EXISTS ps_monthly_earnings")


def downgrade() -> None:
    # recreate the (empty) frozen structure, then restore every view to its frozen-referencing form
    for stmt in _FROZEN_DDL:
        op.execute(stmt)
    # restore the table's security posture (cip_51): FORCE RLS + tenant policy + read grants, so a
    # downgrade yields the tenant-isolated, role-readable table it dropped — not an open one.
    op.execute("ALTER TABLE ps_monthly_earnings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ps_monthly_earnings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cip_tenant_scope ON ps_monthly_earnings "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )
    for role in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_monthly_earnings TO {role}")
    op.execute("CREATE OR REPLACE VIEW lens_ps_brand_reality AS " + _BRAND_REALITY_FROZEN)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_verdict AS " + _CHINA_VERDICT_FROZEN)
    op.execute("CREATE OR REPLACE VIEW lens_ps_china_companies AS " + _CHINA_COMPANIES_FROZEN)
    recreated = {
        "lens_ps_claim_reconciliation": _CLAIM_RECONCILIATION,
        "lens_ps_client_statement": _CLIENT_STATEMENT,
        "lens_ps_partner_statement": _PARTNER_STATEMENT,
        "lens_ps_partner_summary": _PARTNER_SUMMARY,
        "lens_ps_unclaimed": _UNCLAIMED,
    }
    for name, sql in recreated.items():
        op.execute(f"CREATE VIEW {name} AS " + sql)
        for role in _READ_ROLES:
            op.execute(f"GRANT SELECT ON {name} TO {role}")
