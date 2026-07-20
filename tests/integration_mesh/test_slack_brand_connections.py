# foundry: kind=test domain=client-intelligence-platform
"""Unit tests for the Slack brand-connections parser (the schedulable-sync core).

parse_message turns an #amazon-brand-connections post into observation facts. These
are pure functions (no Slack/DB), so they're tested directly. The country field is
the one that flips a brand-new brand to china, so it's the most important to keep
extracting correctly.
"""
from __future__ import annotations

from cip.integration_mesh.sync.slack_brand_connections import (
    _strip_footer,
    _unwrap,
    parse_message,
)

# A real-shape message (Legebo, 2026-07-20) with Slack's link/mailto wrapping.
LEGEBO = """:zap: *New Amazon Brand Connection* :zap:
*Brand Name*: Legebo
*Website*: <http://www.amazon.com/sp|www.amazon.com/sp>
*Contact Name*: Legebo Z
*Email*: <mailto:rethakozan7828@hotmail.com|rethakozan7828@hotmail.com>
*Connection Event Timestamp*: July 20, 2026 at 12:26 AM
*Number of Products Synced*: 21
*Referral Source*: google/search-engine
*Brand ID*: 9d799fb5-dccf-44f5-9492-16039d720069
*Country*: CN
*Logged Deal Source*: China Referral - Tim
*Logged Deal Usage Fee*: 5%
*Logged Deal SaaS Fee*: $0
_Automated with this <http://n8n.example|n8n workflow>_"""


def test_parse_full_message_extracts_country_and_key_fields() -> None:
    r = parse_message(LEGEBO)
    assert r["brand_name"] == "Legebo"
    assert r["country"] == "CN"            # the nationality fact
    assert r["wayward_brand_id"] == "9d799fb5-dccf-44f5-9492-16039d720069"
    assert r["email"] == "rethakozan7828@hotmail.com"   # mailto unwrapped
    assert r["website"] == "www.amazon.com/sp"          # link unwrapped
    assert r["deal_source"] == "China Referral - Tim"
    assert r["usage_fee"] == "5%"
    assert r["products_synced"] == "21"


def test_non_brand_connection_returns_empty() -> None:
    assert parse_message("just a normal chat message") == {}
    assert parse_message("*Brand Name*: X (but not the header)") == {}


def test_empty_field_does_not_swallow_the_next() -> None:
    # a US-referral deal logs no usage fee; the empty field must not eat Country.
    msg = ("*New Amazon Brand Connection*\n*Brand ID*: b1\n"
           "*Logged Deal Usage Fee*: \n*Country*: US")
    r = parse_message(msg)
    assert r["country"] == "US"
    assert "usage_fee" not in r  # empty -> omitted, not "Country"


def test_hubspot_ids_pulled_from_record_urls() -> None:
    msg = ("*New Amazon Brand Connection*\n*Brand ID*: b2\n"
           "<https://app.hubspot.com/contacts/1/record/0-2/334436772553|Company>\n"
           "<https://app.hubspot.com/contacts/1/record/0-3/336619823806|Deal>")
    r = parse_message(msg)
    assert r["hubspot_company_id"] == "334436772553"
    assert r["hubspot_deal_id"] == "336619823806"


def test_unwrap_handles_mailto_and_links() -> None:
    assert _unwrap("<mailto:a@b.com|a@b.com>") == "a@b.com"
    assert _unwrap("<https://x.com|x.com>") == "x.com"
    assert _unwrap("<https://x.com>") == "https://x.com"
    assert _unwrap("plain") == "plain"


def test_strip_footer_removes_n8n_credit() -> None:
    assert _strip_footer("China Referral - Tim _Automated with this wf_") == "China Referral - Tim"
    assert _strip_footer("no footer here") == "no footer here"
