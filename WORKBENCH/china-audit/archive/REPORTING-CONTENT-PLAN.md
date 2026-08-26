# Reporting & Dashboard Content Plan — Project Silk × Wayward

**What each audience needs to see, in plain terms, at three depths.** This is the **content list** —
the *what to show*, locked before we build. It deliberately does **not** cover access-gating, visual
design, or report automation; those are the next three phases (see [Next phases](#next-phases)).

Authored 2026-07-20 (Tim: "a list of the things everyone will want to see... filtered by WHO... then
we lock that list"). Visual version: an Artifact was published for review. Every item below is backed
by data **already live in CIP** (the `mono` reference names the lens/table) — buildable today.

Sits with: [DATA-EXPANSION-PLAN.md](DATA-EXPANSION-PLAN.md) (the data foundation, shipped cip_114–119),
[REPORTING-FRONTEND-PLAN.md](REPORTING-FRONTEND-PLAN.md) + [REPORTING-FRONTEND-IMPLEMENTATION.md](REPORTING-FRONTEND-IMPLEMENTATION.md)
(the custom-frontend decision + build plan).

## The three depths
- **Glance** — the 5-second status (KPI tiles).
- **Working** — the lists & queues used daily/weekly to do the job.
- **Deep** — per-brand / per-transaction drill-down & evidence, for investigation and reconciliation.

Audience type: **INTERNAL** (our teams — full detail) vs **EXTERNAL** (Wayward & partners — curated).
Many items reappear across audiences at different depths/framings — see [Shared cores](#shared-cores).

---

## Leadership *(internal)*
*You & the exec view: "how is the whole thing doing, and what needs me?"*

**Glance**
- **The one number** — still owed to us by Wayward + this month's movement. `lens_ps_claim`
- **Money snapshot** — GMV driven (lifetime + this month), billed, collected, paid to us. `lens_ps_brand_revenue · lens_ps_monthly_summary`
- **Book size** — china brands (active / producing), unknowns pending, brands in contention. `lens_ps_china_verdict · lens_ps_china_contention`
- **Partnership health** — are we in sync with Wayward? recon status + open dispute $. `lens_ps_wayward_reconciliation`

**Working**
- **Growth trend** — china brands & GMV over time; new vs churned.
- **Money trend** — owed / collected / paid by month.
- **Needs your attention** — high-$ contention, aged AR, disputes, statement-drift flags, one list. `lens_ps_china_contention · lens_ps_ar_aging · lens_ps_statement_drift`

**Deep**
- **Drill into any brand or month** — jump to the CS Brand 360 or a Finance month/product breakdown.

## Finance *(internal)*
*The money, end to end — from revenue generated to cash in the door and partner payouts out.*

**Glance**
- **The stages, at a glance** — Revenue generated → Wayward billed → Collected → Owed to us → Paid to us → Owed to partners. `lens_ps_monthly_summary · lens_ps_claim · lens_ps_partner_payout_summary`
- **Receivables** — total still owed + aging buckets. `lens_ps_ar_aging`
- **Cash this period** — net collected, Stripe fees, payouts to Wayward's bank. `ps_stripe_balance_transactions · ps_stripe_payouts`

**Working**
- **Commission ledger** — per brand × product × month: collected, rate (10/6/3), fee owed, partner cut, claim status. `lens_ps_commission_ledger`
- **Collections queue** — who owes, how much, how long overdue, ranked. `lens_ps_ar_aging · lens_ps_china_chase_list`
- **Partner payouts** — what we owe each referral partner, paid vs still-owed. `lens_ps_partner_payout_summary`
- **Statement drift** — brands whose live number moved since the last statement to Wayward. `lens_ps_statement_drift`
- **Wayward reconciliation** — our claim vs Wayward's stated numbers → deltas to resolve. `lens_ps_wayward_reconciliation · lens_ps_wayward_stated`

**Deep**
- **Per-brand claim detail** — the invoice: usage lines, refunds netted, payments applied. `lens_ps_commission_ledger · lens_ps_refund_allocation`
- **Cash reconciliation** — payouts ↔ the balance-transaction ledger (fees, net, per charge). `ps_stripe_balance_transactions · ps_stripe_payouts · ps_stripe_charges`
- **Refunds & disputes** — refund netting + chargebacks by brand. `lens_ps_refund_allocation · ps_stripe_disputes`
- **Rate-clock detail** — when each brand steps 10% → 6% → 3%. `lens_ps_rate_schedule · lens_ps_rate_clock`

## CS Team *(internal)*
*The brand-facing China CS/ops team: who the brands are, who to talk to, which we're unsure about, what support is open.*

**Glance**
- **My brands** — total, by status (china / not-china / unknown) and health. `lens_ps_china_verdict · lens_ps_brand_reality`
- **Review queue count** — brands needing a nationality decision (contention + unknown). `lens_ps_china_contention`
- **Support needing attention** — open / awaiting-response tickets. `cip_tickets (Zendesk)`

**Working**
- **Brand directory** — every brand: status, product eligibility, revenue tier, last activity, owner. `lens_ps_brand_reality · lens_ps_product_eligibility`
- **Nationality review queue** — signals say china but a human ruled otherwise (or still unknown), with evidence, to make/confirm the call. **Never auto-flips — CS decides.** `lens_ps_china_contention · lens_ps_china_verdict`
- **Contact book** — per brand: names, emails, phones, and **WeChat** (as it flows from HubSpot) for outreach. `lens_ps_brand_contact_book`
- **Onboarding pipeline** — brands mid-onboarding and what's pending. `lens_ps_brand_hubspot · lens_ps_deal_timeline`
- **Support by brand** — Zendesk tickets grouped by brand. `cip_tickets`

**Deep**
- **Brand 360** — one brand, everything: verdict + evidence, revenue trend, product setup, contacts, support history, engagement, exclusion status, deal timeline. `lens_ps_china_evidence_grid · lens_ps_brand_revenue · lens_ps_deal_timeline`

## Ops Team *(internal)*
*The pipeline & data-health team: is the data live, fresh, complete — and where are the gaps/exceptions/hygiene fixes.*

**Glance**
- **Data freshness / sync health** — all ingestions running & fresh (Stripe money + extras, HubSpot, Zendesk, lens-mirror, signal-harvest). `lens_ps_source_freshness · cip_sync_runs`
- **Coverage** — % of book with a verdict, fee-rate, GMV, contacts. `lens_ps_information_gaps`
- **Exceptions** — sync failures, invariant violations, anomalies. `cip_sync_runs · lens_ps_open_questions`

**Working**
- **Sync & automation status** — each connector: last success, next run, failures. `cip_sync_runs`
- **Information gaps** — brands missing a fee-rate (GMV can't compute), verdict, or contacts — the work queue. `lens_ps_information_gaps · lens_ps_brand_revenue (rate_missing)`
- **Identity health** — duplicate/split brands, shared owner mailboxes. `lens_ps_identity_health · lens_ps_identity_provenance`
- **Review-queue throughput** — is the nationality queue being worked down? (shared with CS.)

**Deep**
- **Per-run detail** — rows created/updated, errors, cursor state. `cip_sync_runs`
- **Per-brand data quality** — exactly what's missing/inconsistent for a brand. `lens_ps_information_gaps · lens_ps_open_questions`

## Wayward *(external — curated)*
*Our partner / client: a curated portal that proves value and makes the commission transparent — nothing internal.*

**Glance**
- **Partnership scorecard** — total GMV / revenue PS is driving on your china book, active brands, trend. `lens_ps_brand_revenue`

**Working**
- **Commission statement** — what you owe PS, per brand: fee owed, paid, balance. The itemised, transparent invoice. `lens_ps_claim (curated)`
- **Brand performance** — your china brands' revenue by product (Connect / Boost), trend. `lens_ps_brand_revenue · lens_ps_commission_ledger`

**Deep**
- **Reconciliation view** — per brand: our claim vs your attribution/records, so discrepancies resolve together. `lens_ps_wayward_reconciliation`

> **Not shown to Wayward:** our partner payouts & margins, cost/fee analysis, raw nationality-signal
> evidence, anything about other clients.

## Referral Partners *(external — V2, roadmap)*
*The partners we pass a cut to: a self-serve view scoped to **their own** brands only. Deferred to V2 (internal staff first).*

**Glance** — **Your book:** brands you referred, their revenue, what we still owe you. `lens_ps_partner_payout_summary`
**Working** — **Your brands & payouts:** per brand revenue, your commission cut, paid vs unpaid. `lens_ps_partner_payout_summary · lens_ps_commission_ledger`

> **Scope:** strictly their own referred brands; never the full book, our margin, or Wayward's numbers.

---

## Shared cores
A few surfaces do most of the work; build each once, re-frame (and gate) per audience. **Build these first.**

| Surface | Audiences |
|---|---|
| **Commission statement** (full for Finance; curated for Wayward) | Finance · Wayward |
| **Brand performance** (GMV/revenue by brand × product × month) | CS · Finance · Wayward · Leadership |
| **Nationality review queue** (CS decides · Ops ensures worked · Leadership watches high-$) | CS · Ops · Leadership |
| **Data freshness** (Ops operates · everyone needs it green to trust the numbers) | Ops · (all) |

## Candidate scheduled / pushed reports
Not designed yet — a starter list for the automation phase (sent on a cadence to a person/place).

| Report | To | Cadence |
|---|---|---|
| Monthly commission statement (bill + reconciliation) | Wayward + Finance | monthly (after Jake's report, ~10th) |
| Weekly collections / AR (who to chase) | Finance | weekly |
| Weekly nationality review queue | CS | weekly |
| Daily sync-health digest (exceptions only) | Ops | daily |
| Monthly executive summary | Leadership | monthly |

---

## Next phases
This doc is **phase 1 (content)**. In order, still to do:
1. **Access & gating** — Google OAuth logins + an admin surface for per-user visibility (who sees what).
2. **Dashboard design** — the visual build of the screens above (Claude design), shared cores first.
3. **Report automation & delivery** — scheduled generation + send to people/places (email/Slack), per the candidate list.

**Architecture (decided):** a custom reporting web app on Railway at `reports.project-silk.com` (Metabase
retired for Project Silk) — server-only data-access reading the CIP lenses read-only. Users view dashboards
and **download** reports (CSV/PDF); automation (scheduled create + send) is layered on later. Details in
REPORTING-FRONTEND-PLAN.md + REPORTING-FRONTEND-IMPLEMENTATION.md.
