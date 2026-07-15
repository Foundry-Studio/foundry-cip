# QUESTIONS FOR TIM

Things I need a ruling on. **I do not guess at these. I do not act on them. They wait.**

---

## OPEN

### Q0 — WHAT CLEARS A BRAND AS *NOT* CHINESE? ⚠️ BLOCKS ALL 430
**This is the big one. My brief has no answer to it, so the research agent cannot clear anything.**

I told them *"a US LLC proves nothing"* (true — Chinese sellers register Wyoming shells by the
thousand). But I never said what **does** clear a brand. So every one of these came back
`UNRESOLVED`, with the same reason: *"the updated plan requires more than LLC form."*

| brand | USPTO trademark owner | Amazon seller of record | agree? |
|---|---|---|---|
| ACE Supply | `Ae Diagnostics L.L.C.` — 305 SW Hickory Glen, **Grimes, IA** | same entity, Grimes IA | ✅ |
| Acupoint | `WNG BRANDS LLC` — **Dallas, TX** | same entity, Dallas TX | ✅ |
| adi120life | `120/Life LLC` — 1644 N Honore St, **Chicago IL** | same entity, Chicago IL | ✅ |
| admintq | `Toniiq LLC` — 2045 W Grand Ave, **Chicago** | same entity, Chicago | ✅ |
| adminTPC | `Outstanding Products Pty Ltd` — **NSW, AUSTRALIA** | same entity, NSW AU | ✅ |
| ALTA | `Alta Fitness LLC` — **Austin, TX** | same entity, Austin TX | ✅ |

**And it correctly REFUSED to clear the two shells** — which is the proof the test discriminates:

| brand | seller of record | |
|---|---|---|
| 5 Stars United | `1712 Pioneer Ave Ste 500, CHEYENNE WY` | ❌ a **Wyoming mail drop** |
| AC Global Distribution | `8 The Green Suite #5530, DOVER DE` | ❌ a **Delaware mail drop**, no trademark owner found |

**MY PROPOSED RULE (Tim decides, I do not act):**
> A brand is `NOT_CHINA` when **the trademark owner AND the Amazon seller of record name the SAME
> entity**, in a non-China country, at a **REAL street address** — *not* a registered-agent mail
> drop (`30 N Gould St Sheridan WY`, `1309 Coffeen Ave`, `8 The Green Suite Dover DE`,
> `1712 Pioneer Ave Cheyenne WY`).
>
> **Two independent legal records agreeing + a real address ≠ "a US LLC alone."**

**Alternative:** nothing ever clears a brand; we only confirm China, everything else stays unknown
forever. That's defensible for an audit — but it means 430 brands sit unresolved permanently.

---

### Q0b — Throughput: they did 15 of 430 and timed out.
Their worker died and browser capacity was unavailable for the Amazon seller pass. Not a quality
problem — a capacity one. Worth knowing before we send batch 2.

---

### Q1 — `marketing@service908.com`: one owner, or a shared service?
**Blocks: B1.** Affects 10 brands, 4 of them billing ($1,382 collected).

A generic `marketing@` mailbox on a domain called `service908.com`, spanning 10 unrelated brand
names. My shared-mailbox rule flipped four real billing brands to China on it — **dormzie** ($859),
**Qun** ($207), **Zipoute Snorkel** ($183), **SAKOLD** ($131) — none of which have any other China
evidence.

Cuts both ways: one of the 10 brands on it is literally named
`DongGuanShiHengHengYuMaoYiYouXianGongSi` (a Dongguan trading company), so the mailbox is certainly
*connected* to China. But a `marketing@` address serving 10 brands reads more like an agency or a
service provider than one seller's portfolio.

**If it's an owner** → the 4 stay. **If it's a service** → they lose their only evidence.

---

### Q2 — `zhou_yintong@163.com`: agency or owner? My own migrations disagree.
**Blocks: B2.** Sole basis for LICORNE ($366 collected), Delupet, Haptop, Perseek.

> `cip_72_unknown_is_not_zero.py` — *"zhou_yintong@163.com → 18 … **(an agency)**"*
> `cip_80_china_scope_signals.py` — *"same mailbox = same owner, same portfolio (**zhou_yintong@163.com alone runs 18 of them**)"*

Same mailbox. Same 18 brands. Described as an agency in one migration and an owner in the next — and
the China verdict rests on the "owner" reading. It's a `163.com` address either way, so the *person*
is Chinese; the question is whether their 18 brands are *theirs*.

---

### Q3 — RobKushner: ask Jake?
**Blocks: B3.** $328.69 claimable, billing.

Its only China evidence is a Hong Kong billing domain (`urbantrendhk.com`) plus your policy that HK
counts as China. **But Urban Trend HK could equally be a Hong Kong DISTRIBUTOR for a Western brand**
— which is BrüMate's structure inverted.

I wrote *"WEAKEST CALL IN THE SET — DO NOT INVOICE WITHOUT ASKING JAKE"* into the evidence field
myself, and then left it sitting in the China book at the top of the strength ladder where no query
would ever surface the warning.

---

## ANSWERED — do not re-ask

| # | question | Tim's ruling |
|---|---|---|
| — | Is Hong Kong Chinese-based? | **Yes.** Also Macau. No separate bucket. |
| — | Is Eric's sheet alone enough? | **Yes.** *"ANY that are on an eric list or something are definitely, you dont even need to ask me, CHinese."* Exclusion list, heavy performer, any of them. |
| — | Do import records help? | **No.** *"EVERYONE imports from china. no shipping info helps."* |
| — | The 3 `chinese_partner`-only brands | **Tim inspects them himself.** *"DONT ASSUME THAT WAYWARD DATA IS CORRECT… if its chinese refered those other brands, they are LIKELY chinese."* |
| — | The Metabase views | **Later.** *"dont worry about metabase now."* |
| — | Worth researching the 2,194 never-billed unknowns? | **No** — only 8 of them are real brands; the rest are Stripe ghosts. |
