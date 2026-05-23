# foundry: kind=test domain=client-intelligence-platform
"""Pure tests for the CRM → CIP companion field-map + enum validation.

These exercise ``build_managed_companion`` as a dict-in / dict-out
function with no Postgres dependency. Integration coverage (role +
GUC + merge + lens) lives in test_crm_companion_writeback_integration.py.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from cip.integration_mesh.sync.crm_companion_writeback import (
    RunSummary,
    build_managed_companion,
)


def _crm_base(cip_client_id: str = "11111111-1111-1111-1111-111111111111") -> dict:
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "external_ids": {"cip_client_id": cip_client_id},
        "metadata": {},
        "onboarding_status": None,
        "status": "active",
        "dba_name": None,
        "billing_currency": "USD",
        "payment_terms": None,
        "customer_since": None,
        "data_source": "cip-mirror",
    }


# ── Field-map happy path ──────────────────────────────────────────────────

def test_field_map_full_payload_with_partner() -> None:
    """All managed keys (minus deferred ps_lead_owner_email) come through
    when the CRM row + partner carry every input."""
    summary = RunSummary()
    crm = _crm_base()
    crm.update(
        onboarding_status="onboarded",
        dba_name="BrandA EN Alias",
        billing_currency="cny",
        payment_terms="Net 30",
        customer_since=date(2025, 6, 1),
        metadata={
            "engagement_health": "producing",
            "alias_zh": "品牌A",
            "team_notes": "PS team note",
            "last_reviewed": "2026-04-01",
            "ps_segment": "china_referral",
        },
    )
    partner = {"commission_rate": Decimal("12.50"), "updated_at": None}

    managed = build_managed_companion(crm, partner, summary=summary)

    # Note: payment_terms='Net 30' carries days info but not a cadence
    # keyword — so ps_invoice_cadence is omitted (correctly skipped).
    assert managed == {
        "ps_segment": "china_referral",
        "ps_onboarded_status": "onboarded",
        "ps_engagement_health": "producing",
        "ps_local_alias_zh": "品牌A",
        "ps_local_alias_en": "BrandA EN Alias",
        "ps_team_notes": "PS team note",
        "ps_commission_pct": 12.5,
        "ps_billing_currency": "CNY",
        "ps_payment_terms_days": 30,
        "ps_first_onboarded_date": "2025-06-01",
        "ps_last_reviewed_date": "2026-04-01",
    }
    assert summary.enum_coerced_skipped == 0


def test_invoice_cadence_when_payment_terms_is_keyword() -> None:
    """When payment_terms = 'monthly' (a cadence keyword), cadence is
    set and days is omitted — they're mutually exclusive CRM inputs."""
    summary = RunSummary()
    crm = _crm_base()
    crm["payment_terms"] = "monthly"
    managed = build_managed_companion(crm, None, summary=summary)
    assert managed["ps_invoice_cadence"] == "monthly"
    assert "ps_payment_terms_days" not in managed


def test_status_fallback_when_onboarding_status_null() -> None:
    """When ``onboarding_status`` is null we map the legacy ``status``
    column via the CRM→CIP translation table."""
    summary = RunSummary()
    crm = _crm_base()
    crm.update(onboarding_status=None, status="churned")
    managed = build_managed_companion(crm, None, summary=summary)
    assert managed["ps_onboarded_status"] == "offboarded"


# ── Enum miss = warn + SKIP (NOT overwrite to unknown) ────────────────────

def test_enum_miss_on_health_skips_key_preserving_curated_value() -> None:
    """An unknown engagement_health must NOT be coerced; the key is
    omitted so SQL ``||`` keeps any prior curated companion value."""
    summary = RunSummary()
    crm = _crm_base()
    crm["metadata"] = {"engagement_health": "thriving-but-tired"}
    managed = build_managed_companion(crm, None, summary=summary)
    assert "ps_engagement_health" not in managed
    assert summary.enum_coerced_skipped == 1


def test_enum_miss_on_onboarded_status_skips_key() -> None:
    summary = RunSummary()
    crm = _crm_base()
    crm["onboarding_status"] = "something-weird-not-mapped"
    crm["status"] = None
    managed = build_managed_companion(crm, None, summary=summary)
    assert "ps_onboarded_status" not in managed
    assert summary.enum_coerced_skipped == 1


def test_enum_miss_on_invoice_cadence_drops_key_only() -> None:
    """Unknown cadence in payment_terms drops invoice_cadence but the
    'net 60' parse for ps_payment_terms_days still works."""
    summary = RunSummary()
    crm = _crm_base()
    crm["payment_terms"] = "net 60"
    managed = build_managed_companion(crm, None, summary=summary)
    assert "ps_invoice_cadence" not in managed
    assert managed["ps_payment_terms_days"] == 60


# ── Optional keys: missing inputs omit the key entirely ───────────────────

def test_missing_inputs_omit_optional_keys() -> None:
    """A bare CRM row (only the linkage + status) should only emit the
    keys it actually has data for — no None values, no empty strings."""
    summary = RunSummary()
    crm = _crm_base()
    crm["billing_currency"] = None  # remove the default
    managed = build_managed_companion(crm, None, summary=summary)
    # ps_segment defaults to china_referral; ps_onboarded_status maps
    # 'active' → 'onboarded'. Everything else absent.
    assert set(managed.keys()) == {"ps_segment", "ps_onboarded_status"}


# ── ps_commission_pct (Decimal → float) ────────────────────────────────────

def test_commission_decimal_coerced_to_float() -> None:
    summary = RunSummary()
    crm = _crm_base()
    partner = {"commission_rate": Decimal("7.25"), "updated_at": None}
    managed = build_managed_companion(crm, partner, summary=summary)
    assert isinstance(managed["ps_commission_pct"], float)
    assert managed["ps_commission_pct"] == 7.25


def test_no_partner_means_no_commission_key() -> None:
    """When the caller can't pick a partner deterministically (None passed),
    ps_commission_pct is OMITTED — prior curated value preserved."""
    summary = RunSummary()
    managed = build_managed_companion(_crm_base(), None, summary=summary)
    assert "ps_commission_pct" not in managed


# ── ps_segment override via metadata ───────────────────────────────────────

def test_ps_segment_override_via_metadata_when_in_enum() -> None:
    """metadata.ps_segment takes precedence when it's a valid value."""
    summary = RunSummary()
    crm = _crm_base()
    crm["metadata"] = {"ps_segment": "china_referral"}
    managed = build_managed_companion(crm, None, summary=summary)
    assert managed["ps_segment"] == "china_referral"


def test_ps_segment_override_invalid_falls_back_to_skip() -> None:
    """An invalid metadata.ps_segment is skipped (not overwritten to
    the default). Caller can curate via the metadata.ps_segment slot."""
    summary = RunSummary()
    crm = _crm_base()
    crm["metadata"] = {"ps_segment": "tier2"}
    managed = build_managed_companion(crm, None, summary=summary)
    assert "ps_segment" not in managed
    assert summary.enum_coerced_skipped == 1


# ── Defensive: malformed inputs don't raise ───────────────────────────────

def test_malformed_external_ids_treated_as_empty() -> None:
    summary = RunSummary()
    crm = _crm_base()
    crm["external_ids"] = "not-a-dict"  # type: ignore[assignment]
    # build_managed_companion ignores cip_client_id derivation issues —
    # it just passes None into log messages. No exception.
    managed = build_managed_companion(crm, None, summary=summary)
    # Still emits the segment+status keys (they don't depend on cid).
    assert "ps_segment" in managed
    assert "ps_onboarded_status" in managed


def test_malformed_metadata_treated_as_empty() -> None:
    summary = RunSummary()
    crm = _crm_base()
    crm["metadata"] = ["unexpected"]  # type: ignore[assignment]
    managed = build_managed_companion(crm, None, summary=summary)
    assert "ps_local_alias_zh" not in managed
    assert "ps_team_notes" not in managed


# ── payment_terms parsing variants ─────────────────────────────────────────

def test_payment_terms_pure_int_string_parsed_to_days() -> None:
    summary = RunSummary()
    crm = _crm_base()
    crm["payment_terms"] = "30"
    managed = build_managed_companion(crm, None, summary=summary)
    assert managed["ps_payment_terms_days"] == 30


def test_payment_terms_with_days_suffix_parsed() -> None:
    summary = RunSummary()
    crm = _crm_base()
    crm["payment_terms"] = "45 days"
    managed = build_managed_companion(crm, None, summary=summary)
    assert managed["ps_payment_terms_days"] == 45
