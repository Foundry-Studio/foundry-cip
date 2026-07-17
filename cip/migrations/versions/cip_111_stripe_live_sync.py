# foundry: kind=migration domain=client-intelligence-platform
"""cip_111: Stripe live-sync bookkeeping + EVIDENCE-ONLY refund/credit-note tables.

WHY THIS EXISTS (AUTOMATIONS-PLAN §3)
-------------------------------------
Stripe goes from a hand-run one-shot snapshot to a truly live feed (the
``ps_stripe_sync`` module, ``connector_id='ps-stripe-v1'``). That change needs
three small bookkeeping/evidence tables. NONE of them touch the money
derivation — the spine is still ``ps_stripe_invoices`` / ``ps_stripe_invoice_lines``
(cip_49). These are the scaffolding around the live feed.

  1. ps_stripe_events_processed — the Events-API de-dupe log. An OPTIMIZATION +
     audit trail, NOT a correctness requirement. Correctness comes from
     hydrate-by-ID: every event re-fetches the current object and upserts it, so
     replaying an event is idempotent. A lost row here causes at most one
     redundant re-fetch, never wrong data. Pruned to 45 days (> Stripe's 30-day
     event retention) so it can never grow without bound.

  2. ps_stripe_refunds       — EVIDENCE-ONLY (see the big caveat below).
  3. ps_stripe_credit_notes  — EVIDENCE-ONLY (same caveat).

THE EVIDENCE-ONLY RULE (review C1 — verified on prod)
-----------------------------------------------------
Refund economics are ALREADY PARTIALLY INSIDE "collected". Wayward books its
reconciliation adjustments as Stripe-native NEGATIVE ``is_ps_base`` invoice
lines: at review time 777 negative paid ``is_ps_base`` lines totalling
−$10,543.11 (across 102 ledger rows with negative collected months), and the
money engine ALREADY nets them (the ``net_negative_on_positive_revenue``
invariant explicitly tolerates refund months). So naively netting these new
refund/credit-note tables into "collected" would DOUBLE-SUBTRACT.

Therefore these two tables land EVIDENCE-ONLY: we ingest them, we do NOT net
them into the derivation. Their job is to RECONCILE against the negative-line
total (see ``scripts/reconcile_refund_overlap.py``): the real question is not
"are there refunds?" but "which refund economics are NOT already represented as
negative ``is_ps_base`` lines?". Only a PROVEN-UNCOVERED remainder may ever
enter the derivation later — as its own explicit term, with the invariant suite
re-baselined. Until then: ingest, reconcile, never net. (AUTOMATIONS-PLAN §3.)

Revision ID: cip_111_stripe_live_sync
Revises: cip_110_retire_frozen_earnings
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_111_stripe_live_sync"
down_revision: str | Sequence[str] | None = "cip_110_retire_frozen_earnings"
branch_labels = None
depends_on = None

# Same RLS predicate + read-role set as every sibling ps_stripe_* / cip_* table
# (cip_03, cip_49). NULLIF guards the "no tenant set" case so an unscoped
# connection sees zero rows rather than erroring.
_PRED = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_TABLES = ("ps_stripe_events_processed", "ps_stripe_refunds", "ps_stripe_credit_notes")


def upgrade() -> None:
    # ── 1. Events-API de-dupe log (optimization + audit trail) ──────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_events_processed (
            event_id      TEXT PRIMARY KEY,          -- Stripe evt_... (globally unique)
            tenant_id     UUID NOT NULL,
            event_created TIMESTAMPTZ NOT NULL,      -- Stripe event.created — the cursor axis
            event_type    TEXT,                      -- invoice.paid, charge.refunded, ...
            object_id     TEXT,                      -- the hydrated object's id (in_/cus_/...)
            applied_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_events_prune ON ps_stripe_events_processed "
        "(tenant_id, event_created)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_events_processed IS $c$"
        "The /v1/events de-dupe log for the ps-stripe-v1 live sync. This is an "
        "OPTIMIZATION + AUDIT TRAIL, NOT a correctness requirement. Correctness comes from "
        "hydrate-by-ID: every processed event re-fetches the CURRENT object by id and upserts "
        "it, so replaying an already-applied event lands the same state again (idempotent). A "
        "lost or missing row here therefore causes at most ONE redundant re-fetch, never wrong "
        "data. Pruned to 45 days by the sync (> Stripe's 30-day event retention) so it stays "
        "bounded. event_created is the cursor axis the incremental poll advances on.$c$"
    )
    _secure("ps_stripe_events_processed")

    # ── 2. Refunds — EVIDENCE-ONLY ──────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_refunds (
            stripe_refund_id TEXT NOT NULL,          -- re_...
            tenant_id        UUID NOT NULL,
            charge_id        TEXT,                    -- ch_... the refund belongs to
            invoice_id       TEXT,                    -- in_... resolved via the charge (nullable)
            amount           NUMERIC(14,2),           -- refunded amount, POSITIVE dollars
            currency         TEXT,
            status           TEXT,                    -- succeeded | pending | failed | canceled
            reason           TEXT,                    -- duplicate | fraudulent | requested_by_customer
            refund_created   TIMESTAMPTZ,             -- Stripe refund.created
            ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_refund_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_refunds_invoice ON ps_stripe_refunds "
        "(tenant_id, invoice_id)"
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_refunds_charge ON ps_stripe_refunds "
        "(tenant_id, charge_id)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_refunds IS $c$"
        "EVIDENCE-ONLY. Stripe-native refunds (refunds live on the CHARGE, not the invoice; "
        "invoice_id is resolved via charge.invoice where present). These rows are INGESTED but "
        "NEVER netted into 'collected'. Reason (review C1, verified on prod): refund economics "
        "are ALREADY partially inside collected as Wayward's negative paid is_ps_base "
        "reconciliation lines (777 lines / −$10,543.11 at review time), which the money engine "
        "already nets. Netting these tables in as well would DOUBLE-SUBTRACT. Their job is to "
        "RECONCILE against those negative lines (scripts/reconcile_refund_overlap.py); only a "
        "PROVEN-UNCOVERED remainder may ever enter the derivation later, as its own explicit "
        "term with the invariant suite re-baselined. amount is stored POSITIVE (as Stripe "
        "reports it); the reconciliation handles the sign. (AUTOMATIONS-PLAN §3.)$c$"
    )
    _secure("ps_stripe_refunds")

    # ── 3. Credit notes — EVIDENCE-ONLY ─────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ps_stripe_credit_notes (
            stripe_credit_note_id TEXT NOT NULL,      -- cn_...
            tenant_id             UUID NOT NULL,
            invoice_id            TEXT,               -- in_... the credit note is against
            total                 NUMERIC(14,2),      -- credit-note total, POSITIVE dollars
            currency              TEXT,
            status                TEXT,               -- issued | void
            reason                TEXT,               -- duplicate | fraudulent | order_change | ...
            credit_note_created   TIMESTAMPTZ,        -- Stripe credit_note.created
            ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stripe_credit_note_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ps_stripe_credit_notes_invoice ON ps_stripe_credit_notes "
        "(tenant_id, invoice_id)"
    )
    op.execute(
        "COMMENT ON TABLE ps_stripe_credit_notes IS $c$"
        "EVIDENCE-ONLY — same caveat as ps_stripe_refunds. A credit note can drive an invoice to "
        "status='paid' with ZERO cash (a 100 percent credit note), so it is a real part of the "
        "refund/adjustment picture; but Wayward's adjustments are ALREADY booked as negative "
        "is_ps_base invoice lines that the engine nets, so these rows are INGESTED and RECONCILED, "
        "NEVER netted into collected without a proven-uncovered remainder. total is stored "
        "POSITIVE. (AUTOMATIONS-PLAN §3.)$c$"
    )
    _secure("ps_stripe_credit_notes")


def _secure(table: str) -> None:
    """FORCE RLS + cip_tenant_scope policy + read-role grants — the house pattern
    (cip_49 / cip_03). FORCE so even the table owner is scoped; the policy carries
    a WITH CHECK so a mis-scoped write is rejected, not silently mis-tenanted."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY cip_tenant_scope ON {table} "
        f"USING ({_PRED}) WITH CHECK ({_PRED})"
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON {table} TO {r}")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
