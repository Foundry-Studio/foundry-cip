# foundry: kind=test domain=client-intelligence-platform
"""scripts/generate_cip_cheatsheet.py — pure rendering helper.

`render_client_line` is the second of the two roster-writing spots found
in the QC pass on commit e03ca9f (the first is
scripts/generate_tenant_manifest.py::render_clients_section) — the one
that actually had leaked content live on master
(docs/CIP-CHEATSHEET.md: 10 real client names/slugs/ids for Project Silk
plus "... and 1,394 more"). Takes ONLY a count, same reasoning as the
sibling generator's fix.
"""
from __future__ import annotations

from scripts.generate_cip_cheatsheet import render_client_line


def test_render_client_line_zero() -> None:
    assert render_client_line(0) == "- **Clients:** (none yet)"


def test_render_client_line_emits_count_only() -> None:
    result = render_client_line(1404)

    assert "1404" in result
    assert "cip_clients" in result


def test_render_client_line_never_leaks_identities() -> None:
    # Regression guard for the exact incident: these are the real
    # names/slugs that were live in docs/CIP-CHEATSHEET.md on master.
    leaked_terms = [
        "iDaPro", "Indelala", "Funistree",
        "wayward-china-100030771899",
        "59054012-e9e2-520f-98ef-f3adee8899ad",
    ]
    result = render_client_line(1404)

    for term in leaked_terms:
        assert term not in result


def test_render_client_line_singular_count_still_no_identities() -> None:
    result = render_client_line(1)

    assert "1" in result
    assert "wayward" not in result.lower()
