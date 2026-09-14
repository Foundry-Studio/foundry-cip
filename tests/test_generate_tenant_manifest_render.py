# foundry: kind=test domain=client-intelligence-platform
"""scripts/generate_tenant_manifest.py — pure rendering helpers.

`render_clients_section` and `format_client_breakdown` are the two spots
that used to write client identities (names, slugs, client_ids) straight
into a public repo. Both now take ONLY a count (a plain int) — never the
row objects — so leaking an identity isn't just "the function chooses not
to read a field", it's "the function was never handed the field". See the
docstrings on the functions themselves for the full incident context
(docs/CIP-CHEATSHEET.md and docs/tenants/dec814db.../MANIFEST.md both had
to be hand-redacted because of this — see the commit body).
"""
from __future__ import annotations

from scripts.generate_tenant_manifest import (
    format_client_breakdown,
    render_clients_section,
)

# ── render_clients_section ───────────────────────────────────────────────

def test_render_clients_section_emits_count_only() -> None:
    lines = render_clients_section(3)
    rendered = "\n".join(lines)

    assert "## Clients (3)" in rendered


def test_render_clients_section_zero_rows() -> None:
    lines = render_clients_section(0)
    rendered = "\n".join(lines)

    assert "## Clients (0)" in rendered
    # No leftover "no clients seeded" special-case content — the section is
    # identity-free regardless of count.
    assert "cip_clients" in rendered


# ── format_client_breakdown ──────────────────────────────────────────────

def test_format_client_breakdown_collapses_unconditionally_at_low_counts() -> None:
    """Even a single client collapses to a count -- no threshold below
    which itemized client_id prefixes reappear."""
    result = format_client_breakdown(1)

    assert result == "across 1 client"


def test_format_client_breakdown_collapses_at_high_counts() -> None:
    result = format_client_breakdown(1404)

    assert result == "across 1404 clients"


def test_format_client_breakdown_pluralizes_correctly() -> None:
    assert format_client_breakdown(1) == "across 1 client"
    assert format_client_breakdown(2) == "across 2 clients"


def test_format_client_breakdown_zero() -> None:
    assert format_client_breakdown(0) == ""
