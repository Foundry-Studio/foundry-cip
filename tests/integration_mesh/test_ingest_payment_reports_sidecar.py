# foundry: kind=test domain=client-intelligence-platform
"""Sidecar hardening for scripts/ingest_payment_reports.py (AUTOMATIONS-PLAN §7).

Pure-unit (no DB): exercises the sidecar parse layer (``load_expected_totals``) and the
reject-on-missing-month decision in ``ingest_file`` with tmp files + a fake connection. The old
hardcoded EXPECTED_TOTALS dict became a CSV Tim edits; these lock the new contract:
  - a month ABSENT from the sidecar is a LOUD REJECT (unless --force),
  - a present month whose total MISMATCHES is the existing loud SKIP,
  - a present, matching month LOADS, and --force overrides the reject,
  - the pre-existing missing-required-column reject still fires first.
"""
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_payment_reports.py"
_spec = importlib.util.spec_from_file_location("ingest_payment_reports", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
ipr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ipr)


class _FakeConn:
    """Records executes so a test can assert whether the load path ran — no real DB."""

    def __init__(self) -> None:
        self.executes: list = []

    def execute(self, *args: object, **kwargs: object) -> None:
        self.executes.append((args, kwargs))
        return None


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# ── load_expected_totals (the sidecar parser) ────────────────────────────────


def test_load_expected_totals_parses(tmp_path: Path) -> None:
    p = _write(tmp_path / "EXPECTED-TOTALS.csv",
               "month,expected_total,source_note\n"
               "2025-12,1806.86,Jake email\n"
               "2026-06,1149.20,Jake email\n")
    assert ipr.load_expected_totals(p) == {
        "2025-12": Decimal("1806.86"), "2026-06": Decimal("1149.20"),
    }


def test_load_expected_totals_missing_file_is_empty(tmp_path: Path) -> None:
    assert ipr.load_expected_totals(tmp_path / "nope.csv") == {}


def test_load_expected_totals_tolerates_header_case_and_full_date(tmp_path: Path) -> None:
    p = _write(tmp_path / "EXPECTED-TOTALS.csv",
               "Month,Expected Total,Source Note\n"
               "2026-05-01,2859.81,from the May email\n")
    # header case/spacing normalized; month value truncated to YYYY-MM
    assert ipr.load_expected_totals(p) == {"2026-05": Decimal("2859.81")}


def test_load_expected_totals_bad_headers_is_hard_error(tmp_path: Path) -> None:
    p = _write(tmp_path / "EXPECTED-TOTALS.csv", "foo,bar\n2026-05,2859.81\n")
    with pytest.raises(SystemExit):
        ipr.load_expected_totals(p)


# ── ingest_file month gate (no DB — reject/skip paths return before any execute) ──

_GOOD_REPORT = "brandId,paymentDate,usageFeesPaid,revShareOwed\nb-1,2026-09-01,500.00,50.00\n"


def _report(tmp_path: Path, month: str, body: str = _GOOD_REPORT) -> Path:
    return _write(tmp_path / f"{month}-report.csv", body)


def test_absent_month_is_rejected_without_force(tmp_path: Path) -> None:
    conn = _FakeConn()
    res = ipr.ingest_file(conn, _report(tmp_path, "2026-09"), {}, {}, force=False)
    assert "REJECTED" in res and "2026-09" in res["REJECTED"]
    assert conn.executes == [], "a rejected month must never touch the DB"


def test_absent_month_loads_with_force(tmp_path: Path) -> None:
    conn = _FakeConn()
    res = ipr.ingest_file(conn, _report(tmp_path, "2026-09"), {}, {}, force=True)
    assert res.get("loaded") == 1
    assert conn.executes, "--force must load an absent month anyway"


def test_present_matching_month_loads(tmp_path: Path) -> None:
    conn = _FakeConn()
    totals = {"2026-09": Decimal("50.00")}
    res = ipr.ingest_file(conn, _report(tmp_path, "2026-09"), {}, totals, force=False)
    assert res.get("loaded") == 1
    assert res["matches_email"] is True


def test_present_mismatching_month_skips_without_force(tmp_path: Path) -> None:
    conn = _FakeConn()
    totals = {"2026-09": Decimal("999.99")}
    res = ipr.ingest_file(conn, _report(tmp_path, "2026-09"), {}, totals, force=False)
    assert "SKIPPED" in res
    assert conn.executes == [], "a mismatched month must not load without --force"


def test_missing_required_column_rejects_before_month_gate(tmp_path: Path) -> None:
    # drop revShareOwed -> required column missing -> rejected even though the month is known
    body = "brandId,paymentDate,usageFeesPaid\nb-1,2026-09-01,500.00\n"
    conn = _FakeConn()
    totals = {"2026-09": Decimal("50.00")}
    res = ipr.ingest_file(conn, _report(tmp_path, "2026-09", body), {}, totals, force=False)
    assert "REJECTED" in res and "required" in res["REJECTED"]
    assert conn.executes == []
