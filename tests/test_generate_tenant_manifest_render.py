# foundry: kind=test domain=client-intelligence-platform
"""scripts/generate_tenant_manifest.py — pure rendering helpers.

`render_clients_section` and `format_client_breakdown` are the two spots
that used to write client identities (names, slugs, client_ids) straight
into a public repo. They're extracted as pure functions so this can be
tested without a database — see docstrings on the functions themselves for
why the shape changed.
"""
from __future__ import annotations

from scripts.generate_tenant_manifest import (
    format_client_breakdown,
    render_clients_section,
)

# ── render_clients_section ───────────────────────────────────────────────

def test_render_clients_section_emits_count_only() -> None:
    client_rows = [
        ("11111111-1111-1111-1111-111111111111", "Acme Corp", "acme-corp", "retail"),
        ("22222222-2222-2222-2222-222222222222", "Widget Co", "widget-co", "manufacturing"),
        ("33333333-3333-3333-3333-333333333333", "Foo Ltd", "foo-ltd", None),
    ]

    lines = render_clients_section(client_rows)
    rendered = "\n".join(lines)

    assert "## Clients (3)" in rendered


def test_render_clients_section_never_leaks_identities() -> None:
    client_rows = [
        ("11111111-1111-1111-1111-111111111111", "Acme Corp", "acme-corp", "retail"),
        ("22222222-2222-2222-2222-222222222222", "Widget Co", "widget-co", "manufacturing"),
    ]

    rendered = "\n".join(render_clients_section(client_rows))

    for cid, name, slug, _industry in client_rows:
        assert cid not in rendered
        assert name not in rendered
        assert slug not in rendered


def test_render_clients_section_zero_rows() -> None:
    lines = render_clients_section([])
    rendered = "\n".join(lines)

    assert "## Clients (0)" in rendered
    # No leftover "no clients seeded" special-case content — the section is
    # identity-free regardless of count.
    assert "cip_clients" in rendered


# ── format_client_breakdown ──────────────────────────────────────────────

def test_format_client_breakdown_at_or_under_ten_keeps_itemized_format() -> None:
    bd_rows = [
        ("11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa", 42),
        ("22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb", 7),
    ]

    result = format_client_breakdown(bd_rows)

    assert result == "11111111=42, 22222222=7"


def test_format_client_breakdown_over_ten_collapses_to_count() -> None:
    bd_rows = [(f"{i:08d}-0000-0000-0000-000000000000", i) for i in range(11)]

    result = format_client_breakdown(bd_rows)

    assert result == "across 11 clients"
    # Must not contain any client_id prefix once collapsed.
    for cid, _n in bd_rows:
        assert cid[:8] not in result


def test_format_client_breakdown_exactly_ten_keeps_itemized_format() -> None:
    bd_rows = [(f"{i:08d}-0000-0000-0000-000000000000", i) for i in range(10)]

    result = format_client_breakdown(bd_rows)

    assert "across" not in result
    assert result.count("=") == 10


def test_format_client_breakdown_empty() -> None:
    assert format_client_breakdown([]) == ""


def test_format_client_breakdown_null_client_id() -> None:
    result = format_client_breakdown([(None, 5)])

    assert result == "NULL=5"
