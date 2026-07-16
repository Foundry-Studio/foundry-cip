# foundry: kind=script domain=client-intelligence-platform touches=storage
"""Harvest every automatic China signal we already hold. Facts only — no decision, no guessing.

Tim: "determine the slack channel indicators, all the spreadsheets, etc and other signals you
have, and find us known Chinese brands that aren't listed as Chinese, and find us money they owe."

This writes SIGNALS, not verdicts. The verdict is derived in lens_ps_china_verdict, where CHINA
WINS: one positive signal locks the brand.

WHAT IT HARVESTS

  on_exclusion_list      DEFINITIONAL. Contract §1.4: "'Excluded Brands' means any and all
                         CHINESE-BASED Brands...". Being on that list is Wayward and Project Silk
                         jointly asserting, in a signed instrument, that the brand is Chinese.
                         It is the strongest evidence in the entire dataset — and 399 brands the
                         model currently calls "nationality unknown" are ON it.

                         (Chinese and EXCLUDED are different questions. An excluded brand still
                         earns us Boost money and reactivation money — cip_64. So establishing it
                         is Chinese is worth real dollars even though Connect is closed.)

  wayward_country_cn     Wayward's onboarding feed says CN. ISO-2 only.

  wayward_country_other  Wayward states a real, non-CN ISO country. NEGATIVE — and only ever
                         decides a brand that has no positive signal at all. A US flag is not
                         evidence a brand is not Chinese; it usually means a US-registered shell.

                         NOTE the parser bug this guards: two brands have country =
                         "Impersonate Account button  View Contact in Intercom button *Hubspot
                         Sync Information*" — HubSpot page furniture scraped into the country
                         field. One of them is TINY LAND, which Tim knows is Chinese, which has
                         collected $11,524.16, and on which we have been paid $0.00. Requiring
                         ISO-2 stops that string from being read as "a foreign country" and
                         silently disqualifying the brand.

  chinese_email_domain   qq / 163 / 126 / sina / foxmail / aliyun / 139 / 188. A Chinese consumer
                         mailbox on a brand contact is not an accident.

  chinese_partner        Referred by one of OUR China partners (Kerry, Cassie, Sarah, Adina, Eric,
                         Shallow, OpenLight, Chen, Caspar, DBZW). They do not source US brands.
                         STRONG, never definitional: this is a REFERRAL relationship, and it is
                         exactly BruMate's situation — American, referred by a Chinese partner.

  eric_sheet             Present in Eric's all-agreements sheet. His book IS the China programme.
                         DEFINITIONAL, by Tim's ruling of 2026-07-14: "ANY that are on an eric list
                         or something are definitely, you dont even need to ask me, CHinese.
                         Exclusion list, heav performaer, or any of them." It was 'strong' until
                         then, which left 71 brands resting on it alone looking like a research
                         queue. They were never a queue. LIST MEMBERSHIP IS THE ANSWER.

  cjk_in_name            Chinese characters in the brand name or the contact name.

WHAT IT REFUSES TO HARVEST
  The BRAND NAME. Bob and Brad is Chinese. AEEZO is Chinese. "SOUTH KOREA ULIKE GROUP" is a
  Shenzhen company. Lifepro sounds Chinese and is a Los Angeles company. The name generates a
  REVIEW, never a DECISION.

Usage:
  DATABASE_URL=... python scripts/harvest_nationality_signals.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

PS_TENANT = "078a37d6-6ae2-4e22-869e-cc08f6cb2787"

CN_PARTNERS = (
    "kerry", "cassie", "sarah", "adina", "eric", "shallow",
    "openlight", "chen", "caspar", "dbzw",
)

INSERT = """
    INSERT INTO ps_nationality_signals
        (tenant_id, wayward_brand_id, signal, strength, points_to, evidence, source_system)
    {select}
    ON CONFLICT (tenant_id, wayward_brand_id, signal, source_system) DO NOTHING
"""

HARVESTS: list[tuple[str, str]] = [
    # ── DEFINITIONAL ────────────────────────────────────────────────────────
    ("on_exclusion_list", """
        SELECT CAST(:t AS uuid), x.wayward_brand_id, 'on_exclusion_list', 'definitional', 'china',
               'On the frozen exclusion list (bucket: ' || COALESCE(x.bucket,'?') || '). '
               || 'Contract §1.4 defines Excluded Brands as "any and all CHINESE-BASED Brands" — '
               || 'so the list is Wayward and Project Silk jointly asserting, in a signed '
               || 'instrument, that this brand is Chinese. Excluded and Chinese are different '
               || 'questions: this brand still earns us Boost and reactivation money.',
               'contract:exhibit_a_frozen_2025_11_18'
        FROM ps_excluded_brands x
        WHERE x.tenant_id = CAST(:t AS uuid) AND x.wayward_brand_id IS NOT NULL
    """),
    # DEFINITIONAL, by Tim's ruling of 2026-07-14: "ANY that are on an eric list or something are
    # definitely, you dont even need to ask me, CHinese. Exclusion list, heav performaer, or any of
    # them." This was 'strong' until then, which left 71 brands resting on it alone looking like a
    # research queue. They are not. LIST MEMBERSHIP IS THE ANSWER.
    #
    # The one carve-out is BruMate — on the list (OceanWing bucket) and American. Tim ruled it
    # personally, and a pinned ps_added_facts row outranks any machine signal, definitional or not.
    # That is the mechanism: the rule is absolute, and Tim can still overrule it by name.
    ("eric_sheet", """
        SELECT CAST(:t AS uuid), b.wayward_brand_id, 'eric_sheet', 'definitional', 'china',
               'Present in Eric''s all-agreements sheet. Eric''s book IS the China programme — '
               || 'every brand in it was sourced through Chinese referral channels. '
               || 'TIM, 2026-07-14: list membership is DEFINITIVE, not a hint. Do not ask.',
               'gsheet:eric-all-agreements'
        FROM ps_brands b
        WHERE b.tenant_id = CAST(:t AS uuid) AND b.seen_in_eric_sheets
    """),
    # ── CONFIRMED ───────────────────────────────────────────────────────────
    ("wayward_country_cn", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'wayward_country_cn', 'confirmed',
               'china',
               'Wayward''s own onboarding feed records country = CN.',
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid) AND o.field = 'country' AND o.value = 'CN'
          AND o.wayward_brand_id IS NOT NULL
    """),
    ("cjk_in_name", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'cjk_in_name', 'confirmed', 'china',
               'Chinese characters in the ' || o.field || ': ' || o.value,
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid)
          AND o.field IN ('brand_name','contact_name')
          AND o.value ~ '[\\u4e00-\\u9fff]'
          AND o.wayward_brand_id IS NOT NULL
    """),
    # ── STRONG ──────────────────────────────────────────────────────────────
    ("chinese_email_domain", """
        SELECT DISTINCT CAST(:t AS uuid), s.wayward_brand_id, 'chinese_email_domain', 'strong',
               'china',
               'Brand contact uses a Chinese consumer mailbox: ' || s.email,
               'stripe:customers'
        FROM ps_stripe_customers s
        WHERE s.tenant_id = CAST(:t AS uuid) AND s.wayward_brand_id IS NOT NULL
          AND s.email ~* '@(qq|163|126|sina|foxmail|aliyun|139|188|yeah)\\.'
    """),
    ("chinese_email_domain_slack", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'chinese_email_domain', 'strong',
               'china',
               'Onboarding contact uses a Chinese consumer mailbox: ' || o.value,
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid) AND o.field = 'email'
          AND o.value ~* '@(qq|163|126|sina|foxmail|aliyun|139|188|yeah)\\.'
          AND o.wayward_brand_id IS NOT NULL
    """),
    ("chinese_partner", f"""
        SELECT DISTINCT CAST(:t AS uuid), p.wayward_brand_id, 'chinese_partner', 'strong', 'china',
               'Referred by ' || p.partner_of_record || ', one of our China partners. They do not '
               || 'source US brands.',
               'cip:ps_partner_credit'
        FROM ps_partner_credit p
        WHERE p.tenant_id = CAST(:t AS uuid) AND p.wayward_brand_id IS NOT NULL
          AND p.partner_of_record IN ({", ".join(f"'{x}'" for x in CN_PARTNERS)})
    """),
    # ── NEGATIVE ────────────────────────────────────────────────────────────
    # ISO-2 ONLY. Two brands carry HubSpot page furniture in this field — one of them is Tiny
    # Land, which is Chinese, has collected $11,524, and has been paid $0. Treating that string
    # as "a foreign country" is what disqualified it.
    ("wayward_country_other", """
        SELECT DISTINCT CAST(:t AS uuid), o.wayward_brand_id, 'wayward_country_other', 'negative',
               'not_china',
               'Wayward''s onboarding feed records country = ' || o.value || ' (a real ISO-2 code, '
               || 'not CN). NOTE: this only decides the brand if NO positive China signal exists — '
               || 'a US flag is routinely just a US-registered shell for a Chinese operator.',
               'slack:amazon-brand-connections'
        FROM ps_brand_observations o
        WHERE o.tenant_id = CAST(:t AS uuid) AND o.field = 'country'
          AND o.value ~ '^[A-Z]{2}$' AND o.value <> 'CN'
          AND o.wayward_brand_id IS NOT NULL
    """),
]


def run(conn, *, apply: bool) -> dict:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"), {"t": PS_TENANT}
    )
    out: dict = {"harvested": {}}
    for name, select in HARVESTS:
        r = conn.execute(text(INSERT.format(select=select)), {"t": PS_TENANT})
        out["harvested"][name] = r.rowcount

    # nationality lens = nationality only (cip_110): the money columns were vestigial and this
    # summary referenced ps_owed_if_china / ps_paid_today, which never existed on the view (a
    # pre-existing UndefinedColumn). Money lives in lens_ps_claim; here we report book + collected.
    out["verdicts"] = [
        dict(zip(("verdict", "strength", "brands", "collected"), r, strict=False))
        for r in conn.execute(text("""
            SELECT verdict, COALESCE(verdict_strength, '-'),
                   count(*), round(sum(usage_collected), 2)
            FROM lens_ps_china_verdict
            GROUP BY 1, 2
            ORDER BY 3 DESC NULLS LAST
        """)).fetchall()
    ]
    if not apply:
        conn.execute(text("ROLLBACK"))
    out["applied"] = apply
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args(argv)
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            out = run(conn, apply=args.apply)
    finally:
        engine.dispose()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
