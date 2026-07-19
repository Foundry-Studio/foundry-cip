# Opportunity-queue nationality — reconciled decision (2026-07-18)

Reconciliation of **6 independent passes** — Claude (12 web-research agents) + Accio, Perplexity, ChatGPT, Gemini-1, and Gemini-2 (a narrow 'known-US-brand' filter) — over the 401 unknown+billing brands ($94,050.52). Adjudicated by hand; the two DEFINITE buckets have been **flipped into the verdict system**.

| Final bucket | Brands | $ | Action |
| --- | --: | --: | --- |
| definitely_china | 12 | $2,799.12 | **flipped → china** |
| likely_china | 19 | $1,556.58 | residual (human review) |
| unknown | 61 | $11,148.69 | residual (human review) |
| likely_not_china | 163 | $40,770.55 | residual (human review) |
| definitely_not_china | 146 | $37,775.58 | **flipped → not_china** |
| **total** | **401** | **$94,050.52** | |

**Residual still needing a human call:** the two 'probably' buckets = **182 brands ($42,327.13)** [19 likely-China + 163 likely-not], plus **61 still-unknown ($11,148.69)**.

## 0. Money impact

Backlog Wayward owes Project Silk (`sum(ps_claim_owed)` china, floored) went **$13,712.58 → $13,809.71** (+$97.13) with the 12 China flips (11 reconciliation + Nixplay). Modest because the flipped brands' collected revenue is small; the value of this pass is mostly **confirming $37.8k of billing is genuinely NOT owed** (not-China) so it's off the chase list. Proof URLs for every China flip are stored in `ps_nationality_signals.evidence` (source_system `manual:reconciliation_2026_07_18`).

## 1. Flipped → CHINA (12 — hard records)

Each rests on a verifiable China record (CN/HK trademark owner, China seller-of-record, or a Chinese parent), corroborated across sources and NOT dependent on Accio (see §4).

| Brand | $ | Evidence |
| --- | --: | --- |
| INICAT | $1,098.01 | MINICAT (Shenzhen) Trading Co Ltd trademark + TikTok Shop Shenzhen business address |
| glocusent | $570.19 | Shenzhen Glocusent Technology Co Ltd (Alibaba + USPTO/Justia trademark; 4 sources agree) |
| Nixplay | $499.64 | HK-headquartered operating company (Creedon Technologies HK Ltd) — **Tim ruling: HK = China** |
| Ahava | $296.19 | Owned by Fosun International (mainland-China conglomerate) since 2016 — parent-company rule |
| Gamakay | $109.05 | Jieke Trading (Shenzhen) Co Ltd trademark + +86 mainland phone on the refund policy |
| HRYCF | $80.44 | Shenzhen Yahui E-Commerce Co Ltd trademark + Shenzhen seller-of-record |
| MEOLY | $55.15 | Shantou Meiou Trading Company Ltd (Guangdong) trademark owner (Justia) |
| OUFER | $36.18 | Qingdao OUFER Industry Co Ltd (USPTO, 'organized under the laws of China') |
| kiwinurse | $34.79 | Fanzhida Technology (Shenzhen) Co Ltd trademark owner (Justia) |
| SHINEFY | $10.28 | Yantai Shanlan Electronic Commerce Co Ltd — Walmart seller-of-record (Yantai, China) |
| vinsguir | $6.60 | HK Benxin Technology E-Commerce Co Ltd trademark owner (Hong Kong) |
| Aum Active | $2.60 | Operated/managed by Hooray Commerce (Shenzhen brand accelerator, Chinese principals) |

## 2. Flipped → NOT-China (146)

Rule: ≥2 of the evidence-grounded sources (Claude / Perplexity / ChatGPT) called it not-China incl. ≥1 'definitely', with **zero** China signals from any source. Every one spot-checked carries a real operator (named founder + verifiable non-China HQ), not a bare US LLC. Top by $:

| Brand | $ | Operator |
| --- | --: | --- |
| AMZ Advisers | $4,100.83 | AMZ Advisers is a full-service Amazon/eCommerce marketing agency headquartered in New Haven / New Canaan, Connecticut, f |
| Bird Buddy | $3,982.14 | Founded 2020 by named founders Franci Zidar, Ziga Vrtacic and Kyle Buzzard; R&D HQ in Ljubljana, Slovenia with a Delawar |
| SellerX Germany GmbH PO000SXGDE003245 | $2,365.23 | SellerX is a Berlin-based Amazon aggregator ('unicorn') founded Aug 2020 by Philipp Triebel and Malte Horeyseck, who met |
| Smart Home & Garden | $2,286.06 | Payee domain dtcretail.com belongs to 'DTC Retail LLC', a US ecommerce consulting agency run by a named ex-Amazon princi |
| Planetary Design | $2,169.04 | Planetary Design is a Bonner, Montana company (in a repurposed lumber mill) making coffee gear since ~1992; CEO Jess Nep |
| JLab | $1,742.53 | JLab Audio is a Carlsbad, CA audio brand founded 2005 by Joshua Rosenfield; longtime CEO Win Cramer; a top-5 US headphon |
| Tractive | $1,253.53 | Tractive is an Austrian GPS pet-tracking company headquartered in Pasching, Austria, founded 2012 by Michael Hurnaus, Mi |
| Colugo | $949.14 | Colugo is a DTC baby-gear/stroller brand founded 2018 by Ted Iobst (Wharton MBA) and Christy Iobst/MacGregor, HQ Philade |
| unboxme | $948.47 | Unboxme is a 100% woman-owned custom gift-box company founded 2017, HQ Commerce City/Denver, CO; co-founders Tzilka Bell |
| Jerome Alexander Cosmetics | $926.19 | Legacy US cosmetics brand founded 1968 by Jerome Alexander (a real, publicly-named person/chairman), 50+ year history on |
| Newton Baby | $791.84 | Newton Baby, Inc. founded 2013 by named founder Michael Rothbard; HQ 295 Fifth Avenue, New York, NY |
| Divi Scalp Care | $619.21 | Divi Official Inc. founded 2021 by named US influencer Dani Austin (Ramirez) and co-founder Jordan Ramirez; ~$40M first- |
| COSMO Technologies | $585.25 | COSMO Technologies, Inc. is a Denver, CO family-tech company founded 2020 by named founder/CEO Russell York (ex-defense/ |
| SweatBlock | $574.79 | SweatBlock operates as DC Alpine Partners, LLC (Highland/American Fork, Utah); owner Chase Purles (matches payout contac |
| PrideSports | $513.20 | PrideSports = Pride Manufacturing (founded 1930), HQ Brentwood, Tennessee; makes Pride Golf Tee, Softspikes, CHAMP |

…and 131 more (full list in `reconciliation-final.csv`).

## 3. Residual — for human review

### 3a. Likely-China watchlist (19) — soft China signals, no hard record yet

| Brand | $ | Why still 'likely' |
| --- | --: | --- |
| Ryddelighome | $578.05 | No website exists for the brand; payout contact is a free mailbox (mygadgetbox9@gmail.com); brand name is an i |
| Funcils | $199.81 | Real art/craft-supplies brand: own site funcils.com, Amazon storefront, Instagram @funcils (watercolor sets, a |
| Itari | $199.30 | Itari (sold as 'Itriace'/'ItriAce') sells portable thermal printers and tattoo-stencil printers that are Phome |
| Weljoy | $125.60 | Anonymous aromatherapy-diffuser / essential-oil-organizer Amazon brand with no site; only contact is a free ma |
| Feculs | $113.49 | Amazon 'FECULS OFFICIAL' trademark is owned by an individual, SHI, YULIAN (a Chinese/pinyin personal name), co |
| Loobanipets | $66.96 | LOOBANI's US trademark (Reg. 5483604 / Serial 87269371) is owned by an individual, 'Xuhui, Li' (a Chinese pers |
| syncgo | $65.97 | SyncGo is a Windows desktop-calendar software product from Desksware (desksware.com); the site exposes no comp |
| fullnow | $42.21 | Seller is FULLNOW LLC, active on Amazon.com, Amazon.co.uk and especially Amazon.es (top-rated in Spain) since  |
| ResoseseHZH | $39.87 | Brand 'Resosese' on Amazon sells cheap novelty/STEM toys (bathtub race-car tracks, RC robot kits, 'fart blaste |
| MatchAiA | $25.07 | matchaia.com states its matcha is 'organically grown in the mountains of China' and that they 'work closely wi |
| SITFIT Elliptical | $23.40 | Seller of record 'SITFIT Mobility Group, LLC' registered at 19790 W Dixie Hwy Suite #1204, Aventura, FL 33180  |
| AnyScope | $22.57 | AnyScope is a digital-otoscope / ear-camera with wax-removal tools, launched as a batch of near-identical vari |
| Celor | $22.05 | celor.co ('Celor Beauty') sells hydrogel under-eye patches and foot-peel masks; homepage/footer shows no legal |
| Houswise | $13.00 | HOUSWISE trademark and operating entity is Furmia LLC, listed in Flushing, New York (a locale heavily used by  |
| RainbowShow | $9.75 | Only contact is a free mailbox with a pinyin personal name (heguyun@outlook.com — 'He Guyun'), a recognized Ch |
| LOOKNOOK | $4.31 | Listed domain mepurelab.com self-describes as a brand consultancy doing 'ODM/OEM product development, supply c |
| VZJZHAN | $2.86 | No domain; 'VZJZHAN' is an unpronounceable random-capital string typical of Chinese Amazon private-label trade |
| Gemonklee | $2.01 | No domain; Amazon brand 'Gemonklee' (invented, unpronounceable name) sells unrelated multi-category goods — al |
| Kavguine | $0.30 | Amazon-only herbal-supplement brand (wormwood, sea moss/black seed, turmeric) under the invented name 'Kavguin |

### 3b. Likely-NOT-China (163, $40,770.55)

Real non-China lean but thinner than the flipped set (single strong source or softer evidence). Full list in the CSV.

### 3c. Still unknown (61, $11,148.69)

Woodenhouse ($2,305), moralve ($2,039), True Fresh ($1,671), Lebanta ($491), LUNAKAI ($465), Mind-Glowing ($460), Retail Arbitrage ($452), Raw Science ($395), TOP-UP ($292), ALTA ($243), Sprigrown ($238), HydroNova ($231), Freshero ($215), STRIV Labs ($206), Crafty Happitoys ($188), Coreminded ($182), HONEYERA ($134), SAPHUS ($113), GLUIT ($82), BottleShield ($78), Piticco ($67), Rollerex ($64), hemme ($63), CORE FIBER ($63), Stofinity ($45), openr ($37), Truckules ($32), Bywabee ($27), Siblings ($25), Birdee ($24), bcomstock ($24), Biotequelab ($23), oilbanker ($21), D'Artisan Shoppe ($19), IGANCE ($17), burakbilisik ($17), Serei ($15), Vitamizdd ($12), Brick House ($9), Brilliant Beauty ($8), Sandunes ($7), nechemya ($7), VitaUp ($5), jdhaley00 ($5), Osaber ($4), TTolbi ($4), Bubble Sponge ($4), TokyoRush ($3), Ouch Baby ($3), Bonded By Stories ($3), BnD US ($2), MyMed ($2), mondaymoose ($2), ELEMITO ($2), Settini ($1), Swigzy ($1), Signs That Pop ($1), ANTOMILIO ($1), yaqubnmc1 ($1), DecorChiq ($1), sharmony ($1)

## 4. Method & source reliability

- **Accio fabricated its Amazon seller-of-record evidence** — its 'seller business name' citations used made-up seller URLs (sequential IDs like `A1I2J3K4L5M6N`, `A6N7P8Q9R0S1T`). So Accio's China calls were **discounted unless independently corroborated**. It classified 155 brands definitely_not and 16 definitely_china on that basis.

- **Gemini-2** was a different task ('is this a famous US brand') — only ever `definitely_not_china` (48) or `unknown` (353); used as not-China corroboration only.

- **Commitment varied wildly** — unknowns ranged 86 (Claude) → 373 (Gemini-1). Claude, Perplexity and ChatGPT did real per-brand record-hunting and anchor the reconciliation.

- **27 conflicts** (a source said China, another not) were adjudicated by hand on evidence strength: a real record (Justia/USPTO trademark owner, Walmart/Amazon seller-of-record, a Chinese parent) beats vibes; a verified non-China founder+HQ beats a bare US LLC. Notable: **Ahava** → China (Fosun parent, over two sources that read it as Israeli); **Nixplay** kept *likely*-China (HK holding co but British founder/VC — flagged for you).

- **Caveat:** Amazon seller-of-record pages were often rate-limited during the runs, so several China-pattern brands remain in *likely*-China (§3a) rather than flipped.

## 5. Reversibility

All 157 flips are `manual_review` rows tagged `source_system='manual:reconciliation_2026_07_18'`, `asserted_by='Reconciliation 2026-07-18 (Claude + Accio/Perplexity/ChatGPT/Gemini)'`. To undo any/all: `DELETE FROM ps_nationality_signals WHERE source_system='manual:reconciliation_2026_07_18'` (optionally AND wayward_brand_id=…). These are reconciliation calls, distinct from Tim's personal rulings.
