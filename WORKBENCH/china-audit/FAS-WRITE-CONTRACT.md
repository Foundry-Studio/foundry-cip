# FAS Money-Write Contract — detailed spec (REPORTING-REBUILD-PLAN §10.1)

> **Sprint-1 deliverable (authored 2026-07-22).** The *spec*; the endpoint is **built in Sprint 3** and is
> gated by JOS/FAS tool-creation governance. This fleshes out the six requirements in the plan's §10.1 into a
> buildable contract. Read §10.1 + §5 rule 11 + §7.8/§7.10/§7.11 first.

## 0. Why this exists
The reporting app (`reports-project-silk`) is **read-only on CIP** — it connects as `ps_reporting_reader`
(cip_120), which has SELECT on `lens_ps_*` only. That is a deliberate safety fence: a bug in the website can
never corrupt the money data, because the website has no write privilege. But three actions need to change
money-critical CIP data, so the read-only app must **ask a trustworthy backend to make the change on its
behalf**. That backend is a **governed endpoint in the Foundry-Agent-System (FAS)** — the only thing that
writes. This doc is the rules of that hand-off.

## 1. The three write actions (all money-critical → all through this contract)
| Action | Screen | Writes | CIP target |
|---|---|---|---|
| **statement.pin** | §7.10 Statements | pin an as-of claim + freeze its provenance snapshot | `ps_claim_statements` (+ the frozen derivation) |
| **partner.upsert** | §7.11 Partners light-write | add a partner / set-rate / map-alias | `ps_partner_registry` / `ps_partner_credit` / `ps_partner_aliases` |
| **nationality.rule** | §7.8 Nationality Review | CS rules china / not_china (a hard verdict) | `ps_added_facts` (+ sibling-row propagation) |

Nationality is here (not a bare `app_*` server action) because a verdict **flips claim eligibility** — it is
money-critical (plan §5 rule 9, §10.2 #2).

## 2. Endpoint shape
One namespaced, versioned endpoint per action under a single guarded router — e.g.
`POST /api/v1/ps-reporting/write/{action}` where `{action}` ∈ `statement.pin | partner.upsert |
nationality.rule`. One router, one auth path, one audit path; the per-action body differs. (A single
`/write` with an `action` discriminator is equally fine — the point is ONE governed surface, not N ad-hoc
routes.)

## 3. AuthN + AuthZ — the doorway is guarded twice
1. **App → FAS: a scoped service credential.** The reporting app authenticates to FAS with a **service token**
   (its own secret, in the Fernet credential store — see [[reference_foundry_slack_app_d210]] pattern), NOT
   the CIP reader role, NOT a user token. The token is scoped to `ps-reporting/write` only.
2. **Actor propagation + RE-verification.** The request carries the **initiating user** (the Google-signed-in
   email) + their **app-RBAC roles**. FAS does **not** trust these — it **re-verifies** the actor is
   authorized for the action against the app's RBAC model (the `app_*` DB / the same `assertCan` truth-table):
   `statement.pin`/`partner.upsert` require Finance-or-owner; `nationality.rule` requires CS-or-admin. A
   request whose claimed roles don't check out is rejected `403`, logged.
3. **FAS writes with its OWN CIP credential** — a dedicated CIP write role (NOT `ps_reporting_reader`, NOT the
   app). This is the only credential in the system that can write these `ps_*` tables from the reporting path.

## 4. Per-action request/response
All requests share an envelope: `{ idempotency_key, actor: {email, roles[]}, action, payload }`.
Responses share `{ status: 'committed'|'rejected'|'noop', write_id, audit_id, detail }`.

- **statement.pin** · payload `{ as_of, scope: 'wayward'|'partner', partner_id? }`. FAS re-computes the claim
  server-side from the lenses at `as_of`, writes a `ps_claim_statements` row + a **frozen provenance snapshot**
  (per-brand verdict/evidence/rate/lines that produced the total — §7.10), sets the drift baseline. Returns the
  pinned total + `write_id`.
- **partner.upsert** · payload `{ op: 'add'|'set_rate'|'map_alias', partner{...} }`. FAS validates the partner
  economics (rate in range; no duplicate) and writes the registry/credit/alias row.
- **nationality.rule** · payload `{ wayward_brand_id, verdict: 'china'|'not_china', rationale? }`. FAS writes
  `ps_added_facts` with **reporting-engine provenance** (`asserted_by`=actor.email, `source_ref`='reporting-app',
  `asserted_at`=now) and **propagates across the company's sibling brand rows** (one company = many
  `ps_brands` rows — a ruling pinned to one leaks; [[feedback_split_identity_leaks_decisions]]). The verdict
  then flows through `lens_ps_china_verdict` (top-rank, one-directional — a human `not_china` still wins).

## 5. Idempotency
Every write carries a client-generated **`idempotency_key`** (UUID). FAS keeps a short-lived key→write_id
table; a repeated key returns the original `{status:'committed', write_id}` without re-writing. A network
retry / double-click can never double-pin, double-add, or double-rule.

## 6. Server-side re-validation — FAS never trusts the app's numbers
FAS **re-derives / re-checks** every money rule itself, from the lenses, before committing:
- **Money invariants** (statement.pin): count-grain (`lens_ps_china_companies WHERE verdict='china'`),
  net-of-refunds `usage_collected`, money-as-string (no float), the per-brand `ps_claim_owed` floor
  (`GREATEST(mgmt_fee_owed − wayward_paid, 0)`). The pinned total = FAS's own re-computation, not a number the
  app sent.
- **Added-facts rules** (nationality.rule): only the allowed verdict values; provenance mandatory; sibling
  propagation applied; never overrule an existing human `not_china` with a weaker signal.
- **Partner rules** (partner.upsert): rate bounds; alias uniqueness.
A payload that fails re-validation is rejected `422` with the failed invariant named — nothing is written.

## 7. Dual-side audit (both books agree)
- **App side** logs the initiating action in `app_activity_log` (§7.13): `statement.pinned` / `partner.added` /
  `nationality.ruled`, with `actor_email`, target, outcome, `write_id`.
- **FAS side** logs the committed CIP write (its own audit + the `ps_added_facts`/`ps_claim_statements`
  provenance columns are themselves the trail).
Cross-reference by `write_id`. This is the "show evidence it was selected in the reporting engine" requirement
(§10.2 #2): the trail records *who* clicked *what*, *when*, from the app, and *what* FAS committed.

## 8. Error model
`400` bad envelope · `401` bad/again service token · `403` actor not authorized for the action (re-verify
failed) · `409` idempotency conflict (same key, different payload) · `422` money-rule/added-facts re-validation
failed (invariant named) · `5xx` FAS/CIP write error (nothing committed — writes are transactional). The app
surfaces the named failure to the user; it never silently drops a write.

## 9. Governance (JOS / FAS tool-creation)
This is a **new FAS write tool** → it goes through the FAS/JOS tool-creation contract (PROGRAM 2026-07-14):
the tool is declared, permission-scoped, and audited; it uses its own CIP write credential; and it is
reviewed (human-in-the-loop, matching the Sprint-0b posture) before it ships. The endpoint is the ONLY new
write surface into CIP from the reporting path — everything else stays read-only.

## 10. Sequencing
- **Sprint 1 (this doc):** the spec. **Decision §10.2 #5 = approved** (Tim signed off the six requirements).
- **Sprint 3:** Van + I build the endpoint to this spec, then wire the three screens (§7.8 nationality-ruling
  go-live, §7.10 statement-pin, §7.11 partner-write). Build the endpoint BEFORE any screen that calls it.
- **Open for Van at build time:** the exact CIP write-role name + grants; the idempotency-key retention
  window; the exact HubSpot company-id column used for §11.4 propagation.

## 11. Reviewer-hardening (resolutions to the Sprint-1 adversarial review)
1. **Actor re-verification needs a data path — resolved via a signed capability token, NOT a cross-service DB
   read.** FAS is a different service from the app + its `app_*` DB, so "FAS reads `app_*` to re-check the
   actor" may be unimplementable. Instead: the app (which has ALREADY run `assertCan` for the actor) mints a
   **short-lived signed capability token** — HMAC/JWT over `{actor_email, action, exp≤120s}` with the shared
   service secret — and sends it with the write. FAS **verifies the signature + that the token's `action`
   matches the request** (and `exp` is fresh). That IS the re-verification: FAS trusts the app's `assertCan`
   only because it's cryptographically bound to this one action, not a bearer claim it could forge. (If FAS
   and `app_*` ever share a network, a direct read is a fine alternative — but the token path removes the
   dependency.)
2. **`statement.pin` is a NOW-snapshot only — no back-dating.** The `lens_ps_*` views are current-state (no
   temporal/bitemporal dimension), so FAS **cannot** re-derive a past `as_of`. Drop the `as_of` request field;
   the pin freezes the claim **as of now** (server clock), and that timestamp is the statement's as-of. History
   comes from the *sequence* of pinned statements, not from back-dating one.
3. **A pre-pin data-quality gate is part of the contract (not just money invariants).** Before committing a
   `statement.pin`, FAS **also** re-checks server-side: (a) no source feed is stale past threshold (esp. the
   manual Jake payment feed — `lens_ps_source_freshness` mode/heartbeat); (b) no claimed brand has `unknown`
   verdict + revenue; (c) no open drift. A failing gate → `422 gate_failed:<reason>`, nothing pinned. A direct
   FAS call therefore **cannot** bypass the app-side gate by hitting the endpoint.
4. **Sibling propagation uses an explicit company key — never a fuzzy match.** `nationality.rule` propagates
   across the same-company rows via the **structured company id** (`lens_ps_china_companies.company_id` /
   the ps_brands→company linkage), the SAME grain the money count-rule uses — NOT name/mailbox fuzzy matching
   (the Grownsy→Selgrownsy hazard, [[feedback_split_identity_leaks_decisions]]). If a brand has no company id,
   the ruling applies to that brand_id only + flags "unlinked — verify siblings manually."
5. **Concurrent / opposite rulings — append-only, last-writer-wins by `asserted_at`, everything retained.**
   `ps_added_facts` is append-only, so two near-simultaneous opposite rulings both land; the **latest
   `asserted_at` wins** the effective verdict and BOTH are in the audit trail (who/what/when). The
   one-directional rule still holds — a human `not_china` outranks a weaker machine `china` regardless of
   time. No lost-update: FAS never UPDATEs a fact, only INSERTs, so there is no race to corrupt.
