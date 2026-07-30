# foundry: kind=migration domain=client-intelligence-platform
"""cip_142 — ps_signal_family seed + lens_ps_nationality_trail (RDL 1.5b, P2 review/Brand360).

CLEAN-BUILD-PLAN Phase 1.5b. EXPAND-ONLY: one new config table + one new view.

ps_signal_family: the signal->family+label map as CONFIG-AS-DATA (not an inline CASE; house
doctrine, precedent ps_gate_policy / ps_figure_catalog / ps_feed_registry in cip_138 — global PS
config, no RLS). Maps the 21 live ps_nationality_signals signals to the screen's 5 evidence families
(registration, legal_entity, shipping_origin, seller_region, contact_language) + a 6th 'ruling' bucket
for authoritative human/list determinations (manual_review / eric_sheet / on_exclusion_list /
tim_batch_approval — these are definitional, not engine evidence; see feedback_list_membership_is_
definitive). A future engineer edits ONE row, not a buried view.

lens_ps_nationality_trail: per brand, supports[] of {signal, label, direction(points_to; unknown->
neutral), family, strength, at(created_at), by(asserted_by), evidence}, families_present = count of
DISTINCT 5-engine-families present (drives "3+ families = complete"; 'ruling' excluded), has_definitional,
and the contention flag/priority/type from lens_ps_china_contention (cip_138). Serves the Nationality
review evidence panel (§4, grouped by family) AND the Brand 360 trail (§3, chronological). All-brands-
with-signals grain; contention_* is null for non-contention brands.

Owner=postgres (reader reads the view without raw ps_nationality_signals grant). Granted to
ps_reporting_reader + the cip_129 read set.

Revision ID: cip_142_nationality_trail (24 chars <= 32)
Revises: cip_141_brand_tickets
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_142_nationality_trail"
down_revision: str | Sequence[str] | None = "cip_141_brand_tickets"
branch_labels = None
depends_on = None

_READER = "ps_reporting_reader"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_TABLE = r"""
CREATE TABLE ps_signal_family (
    signal TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    label  TEXT NOT NULL
);
"""

# DELEGATED mapping (config-as-data — edit a row to re-classify). 5 engine families + 'ruling'.
_SEED = r"""
INSERT INTO ps_signal_family (signal, family, label) VALUES
  ('wayward_country_cn',     'seller_region',    'Wayward seller country: China'),
  ('wayward_country_other',  'seller_region',    'Wayward seller country: other'),
  ('card_country_cn',        'seller_region',    'Payment card country: China'),
  ('card_country_hk',        'seller_region',    'Payment card country: Hong Kong'),
  ('chinese_email_domain',   'contact_language', 'Chinese email domain'),
  ('phone_+86',              'contact_language', '+86 phone number'),
  ('wechat_handle',          'contact_language', 'WeChat handle'),
  ('qq_handle',              'contact_language', 'QQ handle'),
  ('cn_mobile_handle',       'contact_language', 'CN mobile handle'),
  ('shared_owner_mailbox',   'contact_language', 'Shared owner mailbox'),
  ('cn_company_name_pinyin', 'registration',     'Chinese company name (pinyin)'),
  ('cjk_in_name',            'registration',     'CJK characters in brand name'),
  ('pinyin_name_in_email',   'registration',     'Pinyin name in email'),
  ('pinyin_contact_name',    'registration',     'Pinyin contact name'),
  ('uspto_trademark_owner',  'registration',     'US trademark owner'),
  ('amazon_seller_entity',   'legal_entity',     'Amazon seller entity'),
  ('chinese_partner',        'legal_entity',     'Chinese partner / referral'),
  ('manual_review',          'ruling',           'Human ruling'),
  ('eric_sheet',             'ruling',           'On Eric''s China list'),
  ('on_exclusion_list',      'ruling',           'On the frozen exclusion list'),
  ('tim_batch_approval',     'ruling',           'Tim batch approval')
ON CONFLICT (signal) DO NOTHING;
"""

_ENGINE_FAMILIES = "'registration','legal_entity','shipping_origin','seller_region','contact_language'"

_VIEW = rf"""
CREATE VIEW lens_ps_nationality_trail AS
WITH sig AS (
    SELECT s.wayward_brand_id, s.signal,
           COALESCE(sf.label, s.signal) AS label,
           COALESCE(sf.family, 'other') AS family,
           CASE WHEN s.points_to = 'unknown' THEN 'neutral' ELSE s.points_to END AS direction,
           s.strength, s.created_at, s.asserted_by, s.evidence
    FROM ps_nationality_signals s
    LEFT JOIN ps_signal_family sf ON sf.signal = s.signal
),
agg AS (
    SELECT wayward_brand_id,
           json_agg(json_build_object(
               'signal', signal, 'label', label, 'direction', direction, 'family', family,
               'strength', strength, 'at', created_at::text, 'by', asserted_by, 'evidence', evidence
           ) ORDER BY created_at) AS supports,
           count(DISTINCT family) FILTER (WHERE family IN ({_ENGINE_FAMILIES})) AS families_present,
           bool_or(strength = 'definitional') AS has_definitional
    FROM sig
    GROUP BY wayward_brand_id
)
SELECT a.wayward_brand_id,
       cc.brand_name,
       a.supports,
       a.families_present,
       (a.families_present >= 3) AS evidence_complete,
       a.has_definitional,
       cc.verdict         AS contention_verdict,
       cc.review_priority AS contention_priority,
       cc.contention_type,
       cc.china_evidence  AS engine_note
FROM agg a
LEFT JOIN lens_ps_china_contention cc ON cc.wayward_brand_id = a.wayward_brand_id;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_TABLE)
    op.execute(_SEED)
    op.execute(_VIEW)
    op.execute(f'GRANT SELECT ON lens_ps_nationality_trail TO {_READER};')
    for role in _READ_ROLES:
        op.execute(f'GRANT SELECT ON lens_ps_nationality_trail TO {role};')
    print("cip_142: ps_signal_family seeded (21 signals) + lens_ps_nationality_trail created + granted")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS lens_ps_nationality_trail;")
    op.execute("DROP TABLE IF EXISTS ps_signal_family;")
