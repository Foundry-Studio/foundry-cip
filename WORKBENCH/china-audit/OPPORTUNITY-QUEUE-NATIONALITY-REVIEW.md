# Brand Nationality Classification — Review Task

**401 brands · $94,050.52 of revenue at stake · task version 2026-07-18**

Companion machine-readable file: `opportunity-queue.csv` (same rows, plus empty
columns for your answers — you may fill and return that instead of prose).

---

## 1. Background (read once)

A US-based e-commerce brand aggregator manages hundreds of consumer brands that
sell on Amazon and DTC sites. A partner is owed a commission on the subset of
those brands that are **Chinese-owned or Chinese-controlled companies**. We are
auditing every brand to decide, one by one, whether the *operating company
behind the brand* is Chinese.

The brands listed below are ones we are **actively billing but cannot yet
classify**. We need an independent, evidence-based nationality call on each.

## 2. Your task

Put **every** brand into **exactly one** of these five buckets:

| Bucket | Use when |
| --- | --- |
| **definitely_china** | Hard, verifiable proof the operating company is Chinese-owned/controlled — e.g. the Amazon **seller-of-record business address is in mainland China, Hong Kong, or Macau**; a Chinese parent company; a China HQ with real staff; a China ICP license for the site. |
| **likely_china** | Several soft signals point to China control but no single hard proof — e.g. +86 phone, WeChat contact, a pinyin personal name on a free mailbox, Shenzhen/Yiwu/Guangzhou shipping origin, a "brand accelerator" running dozens of unrelated brands, CJK text on the site. |
| **unknown** | After genuine research there is **not enough evidence either way** — no Amazon seller page found, dead/missing website, or genuinely conflicting signals. Do not use this as a lazy default; say what you tried. |
| **likely_not_china** | A **real** non-China operating presence appears (verifiable non-China HQ, named non-China founders with a public history) but it is not fully nailed down. |
| **definitely_not_china** | Hard, verifiable proof of a **genuine** non-China operating company **and** its principals — ideally the Amazon seller-of-record is at a real non-China address that matches the trademark owner. Not merely a US paper wrapper. |

## 3. THE GOLDEN RULE — do not skip this

> **A US entity, a US address, US trademarks/IP, or a US-looking English website
> does NOT make a brand non-Chinese.**
>
> Chinese-controlled sellers routinely: form a US LLC, rent a US mail-drop or
> registered-agent address, register US trademarks and hold the US IP, and run a
> polished English website with a US phone number — while the company that
> **owns and operates** the brand sits in China (often Shenzhen).
>
> Classify by **who owns and controls the operating company** — not by where a
> shell entity, a footer, or a trademark filing *says* it is. A US LLC in a
> website footer proves nothing on its own.

So the decisive questions are:
1. **Who owns the company?** (parent company, cap table, founders' nationality/base)
2. **Who operates it day to day, and from where?** (HQ, staff, warehouse, support)
3. **Who is the Amazon seller-of-record, and what is their published business
   address?** (Under the US INFORM Consumers Act, Amazon must publish each
   high-volume seller's legal business name + address — this is often the single
   most decisive record.)

A brand can have US IP / a US entity **and still be `definitely_china`** if it is
owned or operated by a Chinese company. That combination is common — treat it as
a red flag to investigate, not as evidence of innocence.

## 4. Where to look (evidence sources)

- **Amazon seller-of-record page** (INFORM Consumers Act — business name + address). Highest-value source.
- **Trademark owner** (USPTO / WIPO) — who actually owns the brand mark.
- **WHOIS / domain** — registrant, registrar, creation date, name servers, hosting country.
- **ICP license lookup** — a Chinese ICP filing ties the site to a China-registered entity.
- **LinkedIn / Crunchbase / corporate registries** — founders, HQ, headcount, parent.
- **The website itself** — but read it skeptically: +86 phones, WeChat IDs, CJK text, Shenzhen/HK addresses, machine-translated English, or an anonymous footer are China signals; a US LLC in the footer is not exculpatory (see §3).
- **News / press / import records** where available.

## 5. How to report back

Return a **Markdown or JSON** file. For **every** brand include:

- `brand` — exactly as listed
- `bucket` — one of the five values above
- `confidence` — 0–100
- `evidence` — a list; each item = a specific finding **with its source URL**
- `reasoning` — 1–3 sentences tying the evidence to the bucket
- `what_would_change_my_mind` — the one record that would move the call

Rules: **cite a source URL for every non-obvious claim.** Do not classify from
the brand name alone. If you cannot find the Amazon seller page, say so. When
torn between *definitely* and *likely*, choose *likely*. It is fine to return in
batches (e.g. rows 1–100) and to leave a brand `unknown` with your notes.

```json
[
  {
    "brand": "Example Brand",
    "bucket": "likely_china",
    "confidence": 70,
    "evidence": [
      {"claim": "Amazon seller-of-record 'Shenzhen X Trading Co., Ltd', address Shenzhen, Guangdong CN", "source_url": "https://www.amazon.com/sp?seller=..."},
      {"claim": "Support email is a pinyin name on gmail; site footer has no legal entity", "source_url": "https://examplebrand.com/contact"}
    ],
    "reasoning": "Seller-of-record is a Shenzhen company despite a US-style brand site; no non-China operating entity found.",
    "what_would_change_my_mind": "A trademark owner + seller-of-record both at a real non-China address."
  }
]
```

## 6. The list

Columns: **$ at stake** = revenue we've billed against this brand (priority only —
not evidence). **Prior findings** = an earlier automated pass; it is **UNVERIFIED
— verify it, do not trust it** (note it often flags "a US LLC in a footer proves
nothing"). Blank domain = we had no website on file; research from the brand name.

Natural batches: rows 1–100, 101–200, 201–300, 301–401.

| # | Brand | $ at stake | Domain | Contact email | Prior findings (UNVERIFIED — verify) | Other signals |
| --: | --- | --: | --- | --- | --- | --- |
| 1 | Cresimo | $4,546.88 | vimbly.com | nicole@vimbly.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to www.vimblygroup.com, which shows '© Vimbly Group. All rights reserved' and address '79 Madison Avenue,   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 2 | AMZ Advisers | $4,100.83 |  |  |  |  |
| 3 | Bird Buddy | $3,982.14 | mybirdbuddy.com | kara@mybirdbuddy.com | Homepage has no footer entity and only says "We pride ourselves on doing our best work from New York" with no address; /pages/contact 301-redirects to |  |
| 4 | Pure Instinct / VWELL / Coochy Plus | $3,495.29 | intimd.com | marketing@intimd.com | Only '© 2026, IntiMD' and phone '(626) 315-8531'; no legal entity form and no address, and /policies/contact-information returned HTTP 404 — a US area |  |
| 5 | MIKO | $3,319.56 | shopmiko.com | david_arazi@shopmiko.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service lists the operator's mailing address twice as "1190 Gravesend Neck Road, Suite B Brooklyn NY 11229"; no  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 6 | bedbath | $3,281.20 | bedbathnmore.com | jesse@bedbathnmore.com | Footer shows only '2021 Bed Bath N' More. All rights reserved.'; /pages/contact-us and /policies/terms-of-service both HTTP 404. No entity, address, p |  |
| 7 | SellerX Germany GmbH PO000SXGDE003245 | $2,365.23 | sellerx.com | maksymilian@sellerx.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — "©SellerX 2021" with headquarters "Chausseestraße 19, 10115 Berlin" — a German GmbH; NOTE it also lists a mainland-China  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 8 | Woodenhouse | $2,305.07 | cutluxe.com | dor@cutluxe.com | Homepage returned product listings with no footer entity/address/phone; /policies/terms-of-service returned HTTP 404. Only CJK seen is Japanese produc |  |
| 9 | Smart Home & Garden | $2,286.06 | dtcretail.com | daven@dtcretail.com | Footer shows only '© DTC Retail'; /policies/terms-of-service returned HTTP 404. No legal entity, address, phone, ICP or CJK content. |  |
| 10 | Planetary Design | $2,169.04 | planetarydesign.us | natalie@planetarydesign.us | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to planetarydesign.com, whose footer reads "© 2026 Planetary Design." with "9255 Bonner Mill Rd, Bonner, M  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 11 | moralve | $2,038.64 | moralve.com | support@moralve.com | Footer is only "© 2026 MORALVE .All Rights Reserved." and /pages/contact-us is a bare contact form with no entity, address or phone; no ICP, +86 or CJ |  |
| 12 | BCOZZY | $1,950.15 | bcozzy.com | contactus@bcozzy.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site states 'BCOZZY Products Ltd', '1221 Brickell Avenue, Suite 900 - #672, Miami Florida 33131, United States', '+1 (88  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 13 | SplashEZ | $1,817.17 | a2playusa.com | yaroslav@a2playusa.com | Contact page states 'A2PLAY LLC, 124 Broadkill Rd #429 Milton, DE 19968-1008 USA' and '+1 877 394 6211'; no ICP, no CJK, no +86. Confidence weak becau |  |
| 14 | JLab | $1,742.53 | jlab.com | apinvoice@jlab.com | Homepage footer was truncated by the fetch before any company details were reached, and /pages/contact-us returned HTTP 404 — no entity, address, phon |  |
| 15 | True Fresh | $1,671.05 | smartvisionus.com | info@smartvisionus.com | Footer names "Smart Vision LLC" and the contact page gives "294 Bay Meadows Ave. Bay Shore, NY 11706"; the listed phone "(406) 555-0120" is a reserved |  |
| 16 | Gorillaz LLC | $1,300.92 | accelclub.pro | iliya.shkuruk@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 17 | Tractive | $1,253.53 | tractive.com | alex.deleon@tractive.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |  |
| 18 | INICAT | $1,098.01 | inicat.net | info@inicat.net | DNS resolution fails: 'getaddrinfo ENOTFOUND inicat.net' — the domain does not resolve. |  |
| 19 | Eversprout | $968.51 | eversprout.com | admin@eversprout.com | queued (crawl chunk still running) |  |
| 20 | Colugo | $949.14 | colugo.com | marketplace-admin@colugo.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names 'Colugo LLC' at '929 108th Ave NE, Suite 1410, Bellevue, WA 98004'; no Chinese markers.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. *** |  |
| 21 | unboxme | $948.47 | unboxme.com | moshe@unboxme.com | Copyright reads '© 2026, Unboxme All Rights Reserved' on both the homepage and /pages/contact — no legal entity form, no address, no phone, no CJK con |  |
| 22 | Jerome Alexander Cosmetics | $926.19 | jeromealexander.com | accountspayable@jeromealexander.com | Homepage and /pages/contact-us show 'Jerome Alexander' as a brand name only — no corporate designation, no address, no phone, no ICP, no CJK. |  |
| 23 | Primely | $910.31 | amerify.co | owais@amerify.co | Homepage and /about list 'Address 30 N Gould St. Sheridan, WY 82801' and 'Call or Text +1 (480) 420 7141'; copyright is bare 'Copyright © 2026' with n |  |
| 24 | ivizel | $833.33 | dr-brace.com | itzik@dr-brace.com | Homepage '© 2026, Dr. Brace All Rights Reserved.' and Terms of Service name only 'Dr. Brace' - a brand, not a legal entity. No address, phone, ICP or |  |
| 25 | Newton Baby | $791.84 | newtonliving.com | matthew.shaw@newtonliving.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to www.newtonbaby.com, whose footer reads "© 2026 Newton Baby LLC"; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. *** |  |
| 26 | Carnation | $791.34 | carnation-inc.com | skhazin@carnation-inc.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Carnation Enterprises' with '510 Woodland Knolls Road, Suite #2 Germantown Hills, IL, 61548, USA' and US phone   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 27 | Mindsight | $780.10 | mindsightnow.com | ted@mindsightnow.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names the operator "THINGS THAT WORK INC." at "4970 Willow Stone Heights, Colorado Springs CO 80906, Un  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 28 | Neutralyze | $672.35 | onlinebrandgrowth.com | jon@onlinebrandgrowth.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Footer reads "© 2026 Remus, LLC. All Rights Reserved." with "4909 Linden Forest Lane, Charlotte, NC 28270" and "+1516860  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 29 | Best Brands | $628.63 | bestbrands.com | ecommerce@bestbrands.com | Copyright line names 'Best Brands Consumer Products Inc.'; /contact is HTTP 404 so no address or phone published. No ICP, no CJK, no +86. Weak: entity |  |
| 30 | Divi Scalp Care | $619.21 | diviofficial.com | grace@diviofficial.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026 Divi Official Inc.'; Terms of Service names 'Divi Official, LLC, and its subsidiaries and affiliated com  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 31 | Think Tank Scholar | $601.77 | thinktankscholar.com | min@thinktankscholar.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names the operator "Think Tank Scholar, LLC" with a governing-law clause under "the laws of California"  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 32 | COSMO Technologies | $585.25 | cosmotogether.com | eric@cosmotogether.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'COSMO Technologies Inc.' at '1312 17th Street #450 Denver, CO 80202'; no Chinese markers.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. *** |  |
| 33 | Ryddelighome | $578.05 |  | mygadgetbox9@gmail.com | nothing; there is no domain to look at |  |
| 34 | SweatBlock | $574.79 | sweatblock.com | kpurles@sweatblock.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names the operator "DC Alpine Partners, LLC – DBA SweatBlock" with a Utah governing-law clause; no ICP,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 35 | NoCry | $572.63 | nocry.com | robin@nocry.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service section 5 states content and trademarks are "the property of NoCry OÜ or Hardly Working OÜ" — OÜ is the  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 36 | glocusent | $570.19 | glocusent.com | ingrid@glocusent.com | queued (crawl chunk still running) |  |
| 37 | BigFly | $536.55 | bill.com | big-fly@bill.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '©2026 BILL Operations, LLC. BILL, the BILL logo, and the "b" logo are trademarks of BILL Operations, LLC.' — US  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 38 | PrideSports | $513.20 | gathroutdoors.com | mcobden@gathroutdoors.com | queued (crawl chunk still running) |  |
| 39 | maisonovo | $511.39 | maisonovo.com | support+1@maisonovo.com | Footer is only "© 2026 - MaisoNovo" and /pages/contact returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |  |
| 40 | Nixplay | $499.64 | nixplay.com | accounts@nixplay.com | Homepage and /policies/terms-of-service both show only "© 2026 Nixplay. All rights reserved" and "support@nixplay.com" — no legal entity suffix, no ad |  |
| 41 | Natemia | $496.76 | forumbrands.com | jack@forumbrands.com | queued (crawl chunk still running) |  |
| 42 | Lebanta | $490.72 |  | trylebanta@gmail.com | nothing; there is no domain to look at |  |
| 43 | liuliuby | $487.14 | liuliuby.com | mliu@liuliuby.com | Homepage footer is only "© 2020 by liuliuby" and /about lists no entity, address or phone; no ICP, +86 or CJK content, so nothing establishes origin e |  |
| 44 | Eve Hansen | $486.12 | evehansen.com | support@evehansen.com | queued (crawl chunk still running) |  |
| 45 | Just Play | $485.72 | justplayproducts.com | slopezmora@justplayproducts.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Contact page names 'Just Play, LLC' at '4850 T-Rex Avenue, Suite 100 Boca Raton, FL 33431 U.S.A.' — a US LLC with a matc  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 46 | vitalisuvorov | $472.35 | themothership.ai | vitalii.suvorov@themothership.ai | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© The Mothership 2023" with "144 Shoreditch High Street, London, E1 6JE, UK"; no ICP, CJK, +86 or China ad  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 47 | LUNAKAI | $465.00 | epochbrands.io | razvan@epochbrands.io | queued (crawl chunk still running) |  |
| 48 | moonjuice | $462.97 | moonjuice.com | barry@moonjuice.com | Footer is only "© 2026 Moon Juice" and /pages/contact lists no entity, address or phone; no ICP, +86 or CJK content. |  |
| 49 | Mind-Glowing | $460.01 | enomadscompany.com | contact@enomadscompany.com | queued (crawl chunk still running) |  |
| 50 | Retail Arbitrage | $451.91 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |  |
| 51 | ezbombs | $425.06 | ezbombs.com | nichole@ezbombs.com | queued (crawl chunk still running) |  |
| 52 | Shacke | $407.09 | shacke.com | contact@shacke.com | Terms of Service names the store operator as "Velocity Media LLC" (US LLC form); no address or phone published, and no ICP, CJK or +86 anywhere. |  |
| 53 | JadeYoga | $404.59 | jadeyoga.com | info@jadeyoga.com | Only '© 2026, [JadeYoga]' plus phone '610-828-4830/888-784-7237 (toll free)'; no legal entity form and no address on the homepage or /pages/contact-us |  |
| 54 | Koala Lifestyle | $403.90 | koalalifestyle.com | kevin@koalalifestyle.com | Footer reads only '© 2026 Koala Lifestyle / All rights reserved' — no legal entity form, address, phone or ICP; /policies/contact-information returned |  |
| 55 | Coda Music Technologies | $397.22 | codamusictech.com | rob@codamusictech.com | Footer: '© 2026 Coda Music Technologies / Seattle, WA' - US city/state only, no street address; no ICP, no +86, no CJK content. |  |
| 56 | VANDEL | $395.83 | wayward.com | rebecca+1@wayward.com | Footer reads '© 2026 Wayward. All rights reserved.' with no legal entity form, address or phone; /pages/contact returned HTTP 404 and no CJK content w |  |
| 57 | BlissLights | $395.56 | blisslights.com | dfeldner@blisslights.com | Footer: '© 2026 BlissLights. All rights reserved.' with US toll-free '888.868.4603'; no ICP, no CJK, no +86, no Chinese address. Weak: no legal suffix |  |
| 58 | Raw Science | $395.16 | traitvis.com | ceo@traitvis.com | Two fetches (https://traitvis.com and https://traitvis.com/about) both returned an empty response body — the site serves no readable content to fetche |  |
| 59 | HYDRO CELL | $378.45 | hydrocellusa.com | dane.ludolph@hydrocellusa.com | Homepage shows no entity, no address, no phone, no ICP and no CJK content; /pages/contact returned HTTP 404. |  |
| 60 | LuxClub | $375.41 |  |  |  |  |
| 61 | Prepared4X | $374.64 | titanignite.com | andrew.spiller@titanignite.com | Footer shows '© Titan Ignite / All Rights Reserved' and nothing else — no entity form, address, phone, or CJK content on the homepage or /pages/contac |  |
| 62 | Crave | $365.39 | cravedirect.com | vitaly@cravedirect.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service lists 'Crave Direct' at '5570 S Irwin Drive Wasilla Alaska US 99623'; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller… |  |
| 63 | AWARLT | $349.24 | awarlt.com | contact@awarlt.com | Footer reads 'American Wellness Authority(TM) 1301 W. Park Ave Suite F Ocean, NJ07712'; no ICP, no CJK, no +86. Weak: name carries no legal suffix (LL |  |
| 64 | JungKwanJang | $348.69 | amp3pr.com | michael+1@amp3pr.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2021 AMP3 Public Relations / All Rights Reserved' with '210 West 29th St. 6th Floor, New York, NY 10001' and   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 65 | Ergonomic Innovations | $343.17 |  | jeremy@qualityhomelifestyle.com |  | contact-country: GB / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 66 | Klymit | $335.57 | gathroutdoors.com | mcobden@gathroutdoors.com | queued (crawl chunk still running) |  |
| 67 | Click and Carry | $335.37 | fluencerfruit.com | liz+cc@fluencerfruit.com | queued (crawl chunk still running) |  |
| 68 | goodwipes | $334.96 | goodwipes.com | jack@goodwipes.com | queued (crawl chunk still running) |  |
| 69 | Vitamin Bounty | $331.90 | vitaminbounty.com | tarek@vitaminbounty.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page states 'Vitamin Bounty c/o Matherson Organics LLC' at '1901 Avenue of the Stars, 19th Floor Los Angeles, CA  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 70 | Hewlett Packard Enterprise Instant-On | $316.98 | phelpsunited.com | wayward.admin@phelpsunited.com | Both https://phelpsunited.com and https://www.phelpsunited.com returned "HTTP 404 Not Found" — no site served. |  |
| 71 | SmartLabels | $304.83 | qrsmartlabels.com | david@qrsmartlabels.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page lists "336 Bon Air Ctr #129 Greenbrae, CA 94904" under "© 2026 SmartLabels. All rights reserved"; no ICP, n  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 72 | Ahava | $296.19 | ahava.com | lolo.d@ahava.com | Copyright line reads '© 2026 AHAVA, Inc. All Rights Reserved'; no ICP, no CJK, no +86, no Chinese address. Weak because no physical address is publish |  |
| 73 | TOP-UP | $291.58 |  | eskopina86@gmail.com | nothing; there is no domain to look at |  |
| 74 | Elgin | $286.83 | amplisell.com | brady@amplisell.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Copyright © 2025 AmpliSell. All Rights Reserved.' with '500 Heights Blvd Suite 307 Houston, TX 77007' and '(205  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 75 | Gout and You | $285.62 |  | spirok75@gmail.com | nothing; there is no domain to look at |  |
| 76 | ACDC LLC | $278.07 | accelclub.pro | klim.sotnikov+3@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 77 | Jungle Powders | $271.19 | junglepowders.com | info@junglepowders.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer gives the address 'Jungle Powders / Vee 4-10 / Parnu, 80011 / Estonia' under 'Copyright © 2026 Jungle Powders' —   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 78 | Kapike | $270.70 |  | kapike.official@gmail.com | nothing; there is no domain to look at |  |
| 79 | KAHI | $269.04 | amp3pr.com | michael+2@amp3pr.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2021 AMP3 Public Relations / All Rights Reserved' with '210 West 29th St. 6th Floor, New York, NY 10001' and   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 80 | Deep Purple LLC | $266.61 | accelclub.pro | klim.sotnikov+4@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 81 | CaniBrands USA HC Corp | $264.93 | canibrands.com | chrislord@canibrands.com | Homepage and /pages/contact-us both returned 'HTTP 403 Forbidden' - site blocks fetching. |  |
| 82 | Turquaz | $259.52 | robemart.com | bill@robemart.com | Terms of Service state "Robemart.com is a registered trademark of SATAY INTERNATIONAL" and the site banner reads "SHIPS FROM CALIFORNIA" with "(844) 7 |  |
| 83 | ECCOSOPHY | $259.44 | eccosophy.com | sophia@eccosophy.com | queued (crawl chunk still running) |  |
| 84 | vibesearplugs | $248.68 | discovervibes.com | jamie@discovervibes.com | Footer shows only 'Copyright © 2025 Vibes / All Rights Reserved'; /policies/terms-of-service returned HTTP 404. No entity, address, phone, ICP or CJK |  |
| 85 | ALTA | $242.79 | wayward.com | rebecca+3@wayward.com | Footer reads '© 2026 Wayward. All rights reserved.' with no legal entity form, address or phone; /pages/contact returned HTTP 404 and no CJK content w |  |
| 86 | Sudstainables | $240.22 |  | getsocial@sojournerbags.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 87 | Sprigrown | $237.74 | growtua.com | larry@growtua.com | queued (crawl chunk still running) |  |
| 88 | Zen Dew | $231.45 | b-glowing.com | lisa@b-glowing.com | Footer shows only 'Copyright © 2024 b-glowing - All Rights Reserved'; /pages/contact-us and /pages/contact both HTTP 404. No entity, address, phone, I |  |
| 89 | HydroNova | $231.18 |  |  |  |  |
| 90 | Realizations | $230.62 | dallenreber.com | me@dallenreber.com | Both https://dallenreber.com and https://www.dallenreber.com returned 'HTTP 404 Not Found' - no site served. |  |
| 91 | PetLoversHQ | $229.85 | petlovers.com | kevin@petlovers.com | Homepage shows only "©2026 PetLovers. All rights reserved."; both /about and /contact returned HTTP 404 — no entity suffix, address, phone, ICP, or CJ |  |
| 92 | Billion Pets | $229.74 |  | nasir.vaidya786@gmail.com | nothing; there is no domain to look at |  |
| 93 | Food Huggers | $224.83 | foodhuggers.com | fh.admin@foodhuggers.com | queued (crawl chunk still running) |  |
| 94 | Happy Head | $219.53 | happyhead.com | accounting@happyhead.com | queued (crawl chunk still running) |  |
| 95 | Champion | $215.49 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |  |
| 96 | Cutluxe | $215.37 |  |  |  |  |
| 97 | Amanda Creation Inc. | $215.27 |  | mkmiraclemakers@aol.com | nothing; there is no domain to look at |  |
| 98 | Freshero | $214.51 |  | fresherous@gmail.com | nothing; there is no domain to look at |  |
| 99 | LyfeFuel | $212.42 | lyfefuel.com | chris@lyfefuel.com | Footer is only "© 2026, LyfeFuel" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |  |
| 100 | STRIV Labs | $206.05 |  |  |  | DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 101 | Dreamland Baby | $205.50 | dreamlandbabyco.com | mike@dreamlandbabyco.com | Both apex and www returned 'HTTP 403 Forbidden' - site blocks fetching. |  |
| 102 | SEVEN POTIONS | $201.51 |  | sevenpotions@gmail.com | nothing; there is no domain to look at |  |
| 103 | jakelangley | $200.46 | lumanutrition.com | jake@lumanutrition.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "Valhalla Media LLC" with US phone "(323) 274-1407" (Los Angeles area code); no ICP, +86 or CJK content any  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 104 | Funcils | $199.81 |  | anuj2911@gmail.com | nothing; there is no domain to look at |  |
| 105 | Itari | $199.30 | itriace.com | wa-it@itriace.com | DNS resolution fails: 'getaddrinfo ENOTFOUND itriace.com' — the domain does not resolve. |  |
| 106 | Beast Bites Supplements | $192.43 | getbeastbites.com | support@getbeastbites.com | queued (crawl chunk still running) |  |
| 107 | Crafty Happitoys | $188.03 | happi.toys | hello@happi.toys | queued (crawl chunk still running) |  |
| 108 | Super Area Rugs | $186.71 | superarearugs.com | randy@superarearugs.com | Homepage carries only "© 2026 - Super Area Rugs"; /pages/contact returned HTTP 404. No entity form, address, phone, ICP or CJK. |  |
| 109 | Gold Standard | $186.06 |  | goldstandardapproved@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 110 | Great Bay Home | $185.43 | greatbayhome.com | taylor.oneil@greatbayhome.com | queued (crawl chunk still running) |  |
| 111 | MatthewMangione | $184.48 | coppercompression.com | matthew@coppercompression.com | Homepage shows only '© 2026 Copper Compression'; /pages/contact-us returned HTTP 404. No legal entity, address, phone, ICP or CJK content. |  |
| 112 | Coreminded | $182.50 |  | ron@coreminded.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 113 | Little Spoon | $179.43 | littlespoon.com | affiliate@littlespoon.com | Footer: "© 2026 Little Spoon, Inc." — a US "Inc."; no address or phone given, and no ICP, +86 or CJK content anywhere. |  |
| 114 | Earth Rated | $176.43 | earthrated.com | tamara.t@earthrated.com | Contact page states 'Our office is located in Montreal, Canada.'; footer 'Earth Rated 2026 ©'. No street address or entity suffix published; no ICP, n |  |
| 115 | Aerosmith LLC | $174.09 | accelclub.pro | klim.sotnikov+1@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 116 | NatLeo USA Supplements | $170.92 | natleousasupplements.com | jonathan@natleousasupplements.com | Homepage shows only "© 2023 NanoCumin. All Rights Reserved." and "Copyright © 2022 NatLeo USA Supplements"; /pages/about-us gives no address, phone, o |  |
| 117 | Clinexil | $169.20 |  | deephpsharma@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 118 | Trueseamoss | $155.87 | trueseamoss.com | amazonaffiliate@trueseamoss.com | Copyright reads '© 2026, TrueSeaMoss.' with no entity form, address or phone; /pages/contact mentions only product sourcing 'off the coast of Nha Tran |  |
| 119 | Scotch Porter | $155.35 | scotchporter.com | christian@scotchporter.com | Homepage carries only "© 2026 Scotch Porter. All Rights Reserved."; /pages/contact returned HTTP 404. No entity form, address, phone, ICP or CJK to de |  |
| 120 | Kanga Toys | $153.92 | mikigraphicdesign.com | michelle@mikigraphicdesign.com | Homepage has no footer/copyright line and /pages/contact shows no entity, address or phone; no ICP, +86 or CJK content. |  |
| 121 | LDC Lux Decor Collection | $152.11 | luxdecorcollection.com | zeshan@luxdecorcollection.com | Footer is only "Copyright © Lux Decor Collection" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |  |
| 122 | Classic Turkish Towels | $151.20 | makroteks.com | ismail@makroteks.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "2020 Makroteks ® All Rights Reserved." with "AKHAN MAH. ATATURK BULV. NO: 117 DENIZLI/TURKEY 20155" and "8  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 123 | Smirly | $150.09 |  | help@heycart.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 124 | ORCA | $149.54 | gathroutdoors.com | mcobden@gathroutdoors.com | queued (crawl chunk still running) |  |
| 125 | Spotted Dog Company | $147.27 | poseidonbrands.com | jason.garvin@poseidonbrands.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer shows "Poseidon Brands" with "3525 South School Avenue Suite C, Fayetteville, AR, 72701, United States" and "4799  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 126 | Bubzi Co | $144.36 | bubzico.com | elijah@bubzico.com | Homepage and /pages/contact-us show only '© 2026, Bubzi Co' - a brand name, not a legal entity; no address, phone, ICP or CJK content. |  |
| 127 | Optimal Carnivore | $140.50 | optimalcarnivore.com | richard@optimalcarnivore.com | Homepage shows "© 2026, optimalcarnivore"; Terms of Service give only the email "richard@optimalcarnivore.com" with no legal entity, address, or phone |  |
| 128 | Jerk Fit Ventures Inc | $138.47 | jerkfit.com | jeff@jerkfit.com | Footer reads only '© 2026, [JerkFit] [Powered by Shopify]' — no entity, address, phone or ICP on the page; /policies/contact-information returned HTTP |  |
| 129 | HONEYERA | $134.40 | honeyera.com | leo@honeyera.com | Homepage and /pages/contact show no entity, no address, no phone and no ICP — the only contact detail is the email 'support@honeyera.com'. |  |
| 130 | Arden Line | $130.91 | ardenline.com | arden@ardenline.com | Footer '© 2026, Arden Line'; /pages/contact and /policies/terms-of-service give only the email 'arden@ardenline.com' — no legal entity, no address, no |  |
| 131 | MAX'IS Creations | $127.76 | maxiscreations.com | jen@maxiscreations.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "MAX'IS Creations, Inc." at "6 Liberty Square #2751 Boston, MA 02109"; no ICP, +86 or CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. *** |  |
| 132 | Weljoy | $125.60 |  | zhencheng1588@hotmail.com | nothing; there is no domain to look at |  |
| 133 | CLOCKY LLC | $124.36 | clocky.com | team@clocky.com | Footer: '© CLOCKY, LLC 2025' and Terms of Service names 'CLOCKY, LLC'; no address published, no ICP, no CJK content (language selector offers EN/DE/ES |  |
| 134 | MODA Works | $121.71 |  | bestsetpet@gmail.com | nothing; there is no domain to look at |  |
| 135 | kyachminov | $121.54 | argobrands.com | marketing@argobrands.com | Both https://argobrands.com and https://www.argobrands.com return 'HTTP 404 Not Found' at the site root — no site content served. |  |
| 136 | eBrands Global | $121.21 |  |  |  |  |
| 137 | Phoenix Worldwide | $120.82 | pinestatebrands.com | matt@pinestatebrands.com | Homepage shows only "Pine State Brands" with no copyright entity, address, or phone, and /contact returned HTTP 404; no ICP, no +86, no CJK content. |  |
| 138 | Hide & Scratch | $119.12 | hideandscratch.com | admin@hideandscratch.com | Footer reads only '© 2026, [Hide & Scratch]' — no entity form, address, phone or ICP; /pages/contact returned HTTP 404. |  |
| 139 | luxail | $118.74 | customselect.net | rachel@customselect.net | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Custom Select Inc.' with '20 Robert pitt Dr, Monsey NY 10952' and phone '+1 (845) 244-6188'; no Chinese markers  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 140 | Intelligent Blends | $117.72 | vitacup.com | tessa@vitacup.com | Footer reads '© 2026, VitaCup/. All rights reserved.' with a US toll-free number '1-(888) 857-VITA (8482)' but no legal entity form and no address; th |  |
| 141 | ShopBobbys | $117.58 | shopbobbys.com | raymond@shopbobbys.com | Footer names "shopbobbys.com LLC" (US LLC form) with New-Jersey-area phone "908-289-1507"; /pages/contact 404'd; no ICP, CJK, +86 or China address fou |  |
| 142 | Core Med Science | $117.30 | vendocommerce.com | jaclyn.carleton@vendocommerce.com | 301-redirects to www.onepltfrm.com whose only footer text is '© PLTFRM. 2026. All Rights Reserved' — no legal entity form, address, phone, ICP or CJK |  |
| 143 | Tiege Hanley | $115.01 | tiege.com | patrick.chojnacki@tiege.com | Homepage carries only "© Tiege Hanley 2026"; /pages/contact returned HTTP 404. No entity form, address, phone, ICP or CJK. |  |
| 144 | Feculs | $113.49 |  | modernrow@outlook.com | nothing; there is no domain to look at |  |
| 145 | SAPHUS | $112.97 |  | saphussoap@gmail.com | nothing; there is no domain to look at |  |
| 146 | riptoned | $112.18 |  | markpasay@gmail.com | nothing; there is no domain to look at |  |
| 147 | Gamakay | $109.05 |  | gkgamakay@gmail.com | nothing; there is no domain to look at |  |
| 148 | Oaktiv | $108.86 | lifeprofitness.com | blumy@lifeprofitness.com | Both https://lifeprofitness.com and https://lifeprofitness.com/pages/contact return "HTTP 403 Forbidden" — the site blocks automated fetching. |  |
| 149 | jasonbaer | $108.69 | infinitecommerce.com | jason.baer@infinitecommerce.com | The domain 301-redirects to https://razor-group.com/, whose footer reads 'Razor Group © All Right Reserved' (Razor Group is the Berlin-based aggregato |  |
| 150 | Pure Zen Tea | $104.95 |  | fabiogullo@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 151 | Checkered Chef | $104.88 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |  |
| 152 | TubShroom | $104.45 |  |  |  |  |
| 153 | Stonecutter | $100.95 | stonecutter.nyc | dominique@stonecutter.nyc | Homepage carries only "© 2026 Stonecutter NYC. All rights reserved."; /pages/contact returned HTTP 404. No address, phone, ICP or CJK. |  |
| 154 | Superior Brands | $99.14 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |  |
| 155 | Bywoods | $98.96 | broombi.com | brian@broombi.com | Footer reads 'Original Broombi by 3Jalbi and Cogent Global, Inc.' - a US-form corporate entity; no address, phone, ICP or CJK content on homepage or / |  |
| 156 | Sit. Stay. Forever. | $98.84 | sitstayforever.com | steve@sitstayforever.com | Footer gives "© 2026, Sit Stay Forever" with US address "90 Bridge St, Suite 3166, Westbrook, ME 04092" (a virtual-mailbox-style suite, hence weak); n |  |
| 157 | KoolaBaby | $96.59 | ygbgroup.com | shaul@ygbgroup.com | Two fetches (https://ygbgroup.com and https://www.ygbgroup.com) both returned an empty response body — the site serves no readable content to fetchers |  |
| 158 | eComCatalyst | $88.08 | tlooutdoors.com | fred@tlooutdoors.com | Only a US-format phone '912-324-7820' appears; there is no company name in the copyright line, no address, and /pages/contact returned HTTP 404. |  |
| 159 | Homesick Candles | $86.11 | vendocommerce.com | jaclyn.carleton@vendocommerce.com | 301-redirects to www.onepltfrm.com whose only footer text is '© PLTFRM. 2026. All Rights Reserved' — no legal entity form, address, phone, ICP or CJK |  |
| 160 | Comfify | $85.92 |  |  |  |  |
| 161 | admintq | $82.24 | toniiq.com | admin@toniiq.com | Site identifies itself only as 'Toniiq - Elevated Nutrients' with no legal entity, address or phone; /pages/contact-us returned HTTP 404. |  |
| 162 | GLUIT | $82.07 | gluit.online | egor@gluit.online | queued (crawl chunk still running) |  |
| 163 | RUGGED & DAPPER | $81.24 | ruggedanddapper.com | dv@ruggedanddapper.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site names the operating entity "RUGGED & DAPPER, LLC" — a US LLC; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. *** |  |
| 164 | HRYCF | $80.44 | hrycftech.com | kimberly@hrycftech.com | The domain serves only a Squarespace 'Coming Soon' placeholder page — the site is parked and carries no company information of any kind. |  |
| 165 | Study Key | $79.75 |  | studykeyteam@gmail.com |  | contact-country: CA / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 166 | BottleShield | $77.80 |  | silversolnask@gmail.com |  | contact-country: NL / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 167 | LOFT + IVY | $77.37 | lifeprofitness.com | blumy@lifeprofitness.com | Both https://lifeprofitness.com and https://lifeprofitness.com/pages/contact return "HTTP 403 Forbidden" — the site blocks automated fetching. |  |
| 168 | Velmia | $76.70 | goyaba.co | velmia@goyaba.co | queued (crawl chunk still running) |  |
| 169 | Chill Pill | $74.73 | chillpillshop.com | hello@chillpillshop.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026, The Chill Pill' with US address '4522 W Village Drive #6170 Tampa, FL 33624'; no Chinese markers.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. **… |  |
| 170 | Clean Litter Club | $73.27 | cleanlitterclub.com | support@cleanlitterclub.com | Homepage shows '© Clean Litter Club 2026' and /pages/contact shows 'Clean Litter Club' with 'no formal legal entity designation found' - no address, p |  |
| 171 | AEROSQUAD | $73.20 |  | lilstickyfingersinc@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 172 | CozyGreensJoyeza | $70.88 | goyaba.co | cozygreens@goyaba.co | queued (crawl chunk still running) |  |
| 173 | beblox llc | $70.52 | bebloxtoy.com | yosef@bebloxtoy.com | TLS failure on both apex and www: 'Hostname/IP does not match certificate's altnames: Host: bebloxtoy.com. is not in the cert's altnames: DNS:*.square |  |
| 174 | Piticco | $67.04 |  | catanneavelino@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 175 | Loobanipets | $66.96 |  | loopetcontent@outlook.com | nothing; there is no domain to look at |  |
| 176 | Bunion Bootie | $66.76 |  | lisamrupert@gmail.com | nothing; there is no domain to look at |  |
| 177 | syncgo | $65.97 |  | desksware@gmail.com | nothing; there is no domain to look at |  |
| 178 | Ebacharach | $65.55 | lebproducts.com | eli@lebproducts.com | DNS resolution fails: "getaddrinfo ENOTFOUND lebproducts.com" — the domain does not resolve. |  |
| 179 | HomeSelects | $65.52 | homeselects.com | admin@homeselects.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page gives the physical address '1106 E. TURNER ROAD LODI, CA 95240' and phone '888-770-4910', with no Chinese m  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 180 | Winthorpe Conservation | $65.21 | winthorpeconservation.com | chris@winthorpeconservation.com | Copyright reads '© 2026, Winthorpe Conservation' on both the homepage and /pages/contact — no legal entity form, no address, no phone, no ICP and no C |  |
| 181 | Drillbrush | $64.88 | drillbrush.com | info@drillbrush.com | Terms of Service names 'Useful Products LLC' and homepage lists US phone '+1 (315) 527-1817'; no street address published, no ICP, no +86, no CJK cont |  |
| 182 | Dalstrong | $64.44 | dalstrong.com | lesley@dalstrong.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Dalstrong Inc.' at '171 E Liberty St, Suite 206, Toronto, ON M6K 3P6, Canada'; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon selle… |  |
| 183 | Rollerex | $64.11 | adventureworldstore.com | info@adventureworldstore.com | Footer shows only '© 2026, AdventureWorldStore'; /pages/contact and /policies/terms-of-service both return HTTP 404. No entity, address, phone, ICP or |  |
| 184 | Waggle | $63.98 | mywaggle.com | kevin@mywaggle.com | Footer: "© 2025 - 2026 Waggle. All rights reserved." with US toll-free phone "855-983-5566"; no address or suffixed entity, and no ICP, +86 or CJK con |  |
| 185 | Pleminnky trading | $63.38 | afula-inc.com | billing@afula-inc.com | Homepage, /about and www all returned an empty document body — 'The web page content provided is empty'. No retrievable content. |  |
| 186 | hemme | $63.12 |  | hellohemme@gmail.com | nothing; there is no domain to look at |  |
| 187 | CORE FIBER | $63.02 |  |  |  | DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 188 | IceBeanie | $62.88 | icebeanie.com | nic@icebeanie.com | Homepage and /pages/contact show no entity, no address, no phone and no ICP — the only contact detail is the email 'support@icebeanie.com'. |  |
| 189 | L.ī.Q. Inc. | $61.91 | liq-home.com | info@liq-home.com | Footer: "© 2026 — L.I.Q. Inc., All rights reserved" — a US-style "Inc."; homepage and /pages/contact show no address, phone, ICP or CJK content (entit |  |
| 190 | Lotus Linen | $61.61 | shoplotuslinen.com | hello@shoplotuslinen.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer gives "1311 E Chestnut Ave, Unit A, Santa Ana, CA 92701" with "(800) 787-8613"; no ICP, CJK, +86 or China address  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 191 | Dr Vitamin Solutions | $61.17 | formby.llc | jon@formby.llc | queued (crawl chunk still running) |  |
| 192 | Gripjoy Socks | $57.43 | gripjoy.com | chad@gripjoy.com | queued (crawl chunk still running) |  |
| 193 | LeRoy's Rocky Mountain | $57.35 |  | michael@leroysrockymountain.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 194 | The Blissful Dog Inc. | $56.81 | theblissfuldogwholesale.com | ashley@theblissfuldogwholesale.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to theblissfulpets.com/pages/wholesale, which publishes "50688 235th Avenue Clearbrook, MN 56634" and "1-8  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 195 | venturejakef | $56.00 | ventureformations.com | jake@ventureformations.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads '© 2021 Venture Formations. All Rights Reserved.' with US address '8250 Delta Cir, St. Joseph, MN 56374'; n  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 196 | MEOLY | $55.15 | zeltmak.com | pauls@zeltmak.com | Contact page gives '90 State Street, STE 700 Office 40, Albany, NY, 12207, USA' and '845-303-5908' under 'Copyright © 2026 ZELTMAK'; no ICP, +86 or CJ |  |
| 197 | ASOZI | $54.57 |  | tumzon1@gmail.com | nothing; there is no domain to look at |  |
| 198 | kurkee | $54.39 |  | kurkeeusa@gmail.com | nothing; there is no domain to look at |  |
| 199 | Saint Mingiano | $54.00 | saintmingiano.com | saint@saintmingiano.com | Terms of Service name the entity "Silk Road Wholesale LLC" and the footer lists "3 Germay Dr, Unit 4-4845, Wilmington, DE, 19804, United States"; note |  |
| 200 | AltroCare | $53.86 | altrocare.com | sylvie@altrocare.com | Terms of service say 'This website is operated by AltroCare' but the address and phone fields are unfilled Shopify template placeholders: '[INSERT BUS |  |
| 201 | OsoCozy | $52.29 | alltogetherenterprises.com | dennis@alltogetherenterprises.com | Footer shows only '© 2026, AllTogetherEnterprises.com' (no legal suffix); /pages/about-us and /policies/terms-of-service both HTTP 404. No entity, add |  |
| 202 | Bulldogology | $51.43 |  | bulldogology@gmail.com | nothing; there is no domain to look at |  |
| 203 | remiliahair | $48.47 | remiliahair.com | eliran@remiliahair.com | Homepage shows "All rights reserved Remilia 2026" and the Terms of Service give only "info@remiliahair.com"; /pages/contact-us returned HTTP 404 — no |  |
| 204 | mkeck | $45.69 | hamptonproducts.com | mkeck@hamptonproducts.com | queued (crawl chunk still running) |  |
| 205 | Baby K'tan | $45.18 | babyktan.com | michal@babyktan.com | Terms of service Section 19 names 'Baby K'tan, LLC' (opening line: 'Baby K'tan Online Store'); no ICP, no CJK, no +86, no Chinese address. Weak: no ph |  |
| 206 | Pup Choice | $44.81 | rkinc.net | ck@rkinc.net | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© RK Ventures Inc. All Rights Reserved." with US toll-free "(866) 229-8430"; no ICP, no +86, no CJK conten  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 207 | Thermajane | $44.67 | 1836totalcommerce.com | daniel@1836totalcommerce.com | DNS lookup failed: 'getaddrinfo ENOTFOUND 1836totalcommerce.com' — domain does not resolve. |  |
| 208 | Stofinity | $44.56 |  | info.tdclassic@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 209 | Hailey Ennis | $44.43 | momofuku.com | hennis@momofuku.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer shows "©Momofuku" and the site lists its US restaurant locations including "171 1st Ave, New York 10003" and "102  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 210 | adi120life | $43.85 | 120life.com | adi@120life.com | Footer carries only '© 2026 120/Life' with no legal entity; /pages/contact shows no entity, address or phone; no ICP, no CJK, no +86. |  |
| 211 | fullnow | $42.21 |  | amazon.fullnow@gmail.com | nothing; there is no domain to look at |  |
| 212 | Myhalos | $41.01 |  | shane@firstoptionproducts.com |  | contact-country: IE / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 213 | Thinksound | $40.98 | mytrustybrands.com | tyler@mytrustybrands.com | DNS resolution fails: "getaddrinfo ENOTFOUND mytrustybrands.com" — the domain does not resolve. |  |
| 214 | KLUBI | $40.26 | klubigifts.com | brad@klubigifts.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact-information page names the trader as 'Voudrais Wholesale , 2014 Goodrich Ave, a, Austin TX 78704, United States'  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 215 | ResoseseHZH | $39.87 |  | zhoucool@outlook.com | nothing; there is no domain to look at |  |
| 216 | SwaddleDesigns | $38.86 | swaddledesigns.com | jeff@swaddledesigns.com | Homepage exposes no entity, address, phone, ICP or CJK; /pages/contact returned HTTP 404. Nothing to decide on. |  |
| 217 | Stripebird | $38.05 | stripebird.com | grant@stripebird.com | Terms of Service names only "Stripebird" ("Our store is hosted on Shopify Inc.") with support@stripebird.com; no legal entity form, address, phone, IC |  |
| 218 | openr | $37.39 |  | open.rumination@gmail.com | nothing; there is no domain to look at |  |
| 219 | OUFER | $36.18 | ouferbodyjewelry.com | nyreeyuan@ouferbodyjewelry.com | Homepage, Terms of Service and /pages/contact-us all show only the brand "OUFER BODY JEWELRY" and the line "+1(747) 239-9981" — no legal entity, no ad |  |
| 220 | Purplesful Snacking inc. | $35.57 |  | mavtlholdings@gmail.com | nothing; there is no domain to look at |  |
| 221 | kiwinurse | $34.79 |  | kiwinurseservice@gmail.com | nothing; there is no domain to look at |  |
| 222 | LivMatte | $34.43 | livmatte.com | support@livmatte.com | Footer shows "© 2026 LIV Matte" with "300 SE 2nd Street Suite 600Fort Lauderdale, FL 33301"; no ICP, +86 or CJK content, but no formally suffixed lega |  |
| 223 | RYVE | $34.24 | willtos.net | operations@willtos.net | DNS does not resolve: 'getaddrinfo ENOTFOUND willtos.net' — the domain is dead. |  |
| 224 | AmpliSell | $33.87 |  |  |  |  |
| 225 | Boshel | $33.78 | boshel.com | support@boshel.com | Homepage and /pages/contact-us both show only the brand string 'BOSHEL STORE' - no legal entity, no address, no phone, no CJK content. |  |
| 226 | burstoralcare | $33.66 | burstoralcare.com | courtney.rconnell@burstoralcare.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Homepage: 'BURST® is a registered trademark of BURST.USA Inc.'; Terms of Service names 'BURST.USA INC. AND ITS AFFILIATE  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 227 | Carpe | $33.29 | mycarpe.com | alayna@mycarpe.com | Footer is only "© 2026 Carpe" and /pages/contact lists no entity, address or phone; no ICP, +86 or CJK content. |  |
| 228 | GEM | $32.93 | dailygem.com | brian@dailygem.com | Footer: '© GEM HEALTH, INC. 2023'; Terms of Service names 'Gem Health, Inc.' and references 'Venice, California'. No street address published; no ICP, |  |
| 229 | Culina Craftique | $32.91 |  | shubham.ranjan@havenise.com |  | contact-country: IN / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 230 | Organifi | $32.55 | emplicit.co | sara.cotillard@emplicit.co | queued (crawl chunk still running) |  |
| 231 | OREN’S BAMBOO WAREHOUSE | $32.46 |  | oren.rasowsky@gmail.com | nothing; there is no domain to look at |  |
| 232 | Scosche Industries | $32.18 | scosche.com | cmerritt@scosche.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Copyright line reads "©2026 Scosche Industries." with US support line "(800) 363-4490 ext.1"; no ICP, CJK, +86 or China   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 233 | Hiker Hunger Outfitters | $32.14 | hikerhunger.com | rory@hikerhunger.com | Only '© 2026, [Hiker Hunger Outfitters] [Powered by Shopify]' and phone '(406) 219-1363'; a US phone number is not proof of non-Chinese ownership, and |  |
| 234 | Marque | $32.01 | marquecycling.com | eric.c@marquecycling.com | Footer: "© 2026 Marque Cycling/" with US phone "714-202-7358" (Orange County, CA area code); no address or suffixed entity, and no ICP, +86 or CJK con |  |
| 235 | survivalgardenseeds | $31.96 | survivalgardenseeds.com | jason@survivalgardenseeds.com | Footer gives "PO Box 303, Rigby, ID 83442" (US) — a PO box only, no street address or entity form, hence weak; no ICP, CJK, +86 or China address anywh |  |
| 236 | Truckules | $31.50 |  | tal22314amazon@gmail.com | nothing; there is no domain to look at |  |
| 237 | NUTRAHARMONY | $31.20 | nutra-harmony.com | store@nutra-harmony.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Redirects to nutraharmony.com, whose Terms of Service list "37901 4TH ST N STE 300, ST PETERSBURG, FL 33702, US" and "+1  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 238 | Choice Marts | $30.88 | gikaholdings.com | karolis@gikaholdings.com | queued (crawl chunk still running) |  |
| 239 | Stojo Products Inc. | $30.80 | stojo.co | operations@stojo.co | DNS lookup failed for both the apex and www: "getaddrinfo ENOTFOUND stojo.co". The domain does not resolve. |  |
| 240 | Right 'Bove Touch | $29.89 | quadraclicks.com | hello@quadraclicks.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "QuadraClicks Gaming 8780 19th ST #152 Alta Loma, CA, 91701" with "(408) 758-8695"; no ICP, no +86, no CJK   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 241 | Kore Aviation | $28.33 | koreheadset.com | matthew@koreheadset.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads 'Copyright© 2026 KORE Headset LLC' — a US LLC, with no Chinese markers anywhere on the page (no address sho  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 242 | Nano Bond | $28.06 |  | luke@nanobondus.com |  | contact-country: CA / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 243 | CBRODERICK | $27.88 | hey-miles.com | carly@hey-miles.com | Footer reads only 'Copyright © 2026 Miles.' — no legal entity form, address, phone or ICP; /policies/contact-information repeated the same line and no |  |
| 244 | Wax&Wit | $27.63 |  | brian.iqnatural@gmail.com | nothing; there is no domain to look at |  |
| 245 | Natural Zing | $27.60 |  | naturalzinginfo@gmail.com | nothing; there is no domain to look at |  |
| 246 | Physician's Choice | $27.51 | physicianschoice.com | michaels@physicianschoice.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Terms of Service name the entity "JB7, LLC, d/b/a Physician's Choice" at "6990 West 38th Avenue #304 Wheat Ridge, CO 800  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 247 | XWERKS | $27.48 | xwerks.com | mike@xwerks.com | Footer on /pages/contact reads '© 2026 XWERKS - USA' — a country label but no legal entity form, no address and no phone; no ICP or CJK content found. |  |
| 248 | Just Add Luv | $27.05 | justaddluv.com | contact@justaddluv.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact-information page gives 'Just Add Luv, 2415 West Stonehaven Loop, 305c, Lehi UT 84043, United States' with phone   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 249 | BlauKe | $26.78 | jarganic.com | contact@jarganic.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — The domain 301-redirects to blauke.com, whose footer reads 'Copyright © 2026 BlauKe® all rights reserved. BlauKe® is own  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 250 | 100% Pure New Zealand Honey | $26.68 | themanukacollective.com | jeffry.loho@themanukacollective.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2026 The Manuka Collective. All rights reserved" with New Zealand landline "+64 3 688 7150"; no ICP, CJK  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 251 | Bywabee | $26.59 | bywabee.com | bobby@bywabee.com | 301 Moved Permanently to https://bywabee.myshopify.com/ which returns HTTP 404 - store is closed/dead. |  |
| 252 | SipArt Mastery | $26.38 |  | sipartmastery@gmail.com | nothing; there is no domain to look at |  |
| 253 | TesLiner | $26.34 |  |  |  | DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 254 | Paper Plan | $25.88 |  |  |  | DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 255 | Siblings | $25.36 | islandcitydigital.com | siblings@islandcitydigital.com | Connection refused: 'connect ECONNREFUSED 192.64.119.129:443' — the host resolves but refuses HTTPS connections. |  |
| 256 | MatchAiA | $25.07 |  | matchaia2024@gmail.com | nothing; there is no domain to look at |  |
| 257 | TRYNDI | $24.69 | tryndi.com | sales@tryndi.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads '© 2026 TRYNDI / Powered by 20MULTI LLC' with address '1401 Lavaca Street, Austin, TX 78701, United States'  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 258 | Birdee | $24.48 |  | solutions.amzn@gmail.com | nothing; there is no domain to look at |  |
| 259 | elizabethmott | $24.33 | elizabethmott.com | kmontania@elizabethmott.com | queued (crawl chunk still running) |  |
| 260 | bcomstock | $24.30 |  | bcomstock45@gmail.com | nothing; there is no domain to look at |  |
| 261 | andrewEMJ | $24.22 | everymanjack.com | andrew@everymanjack.com | queued (crawl chunk still running) |  |
| 262 | SITFIT Elliptical | $23.40 | sitfitmobilitygroup.com | info@sitfitmobilitygroup.com | Both https://sitfitmobilitygroup.com and /pages/contact return no extractable text content (empty render) — nothing could be inspected. |  |
| 263 | Biotequelab | $23.18 |  | product@suplcorp.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 264 | AnyScope | $22.57 | varzky.com | george@varzky.com | DNS does not resolve: 'getaddrinfo ENOTFOUND varzky.com' and 'getaddrinfo ENOTFOUND www.varzky.com' — the domain is dead. |  |
| 265 | Chopper Mill, Inc. | $22.38 | choppermill.com | jill@choppermill.com | Footer: '© 2026 Chopper Mill, Inc. All Rights Reserved.' and Terms of Service names 'Chopper Mill, Inc.'; no address or phone published, no ICP or CJK |  |
| 266 | Celor | $22.05 | celor.co | support@celor.co | Only '© 2026, Célor Beauty. All rights reserved.' - a brand, not an entity; /pages/contact returned HTTP 404. No address, phone, ICP or CJK content. |  |
| 267 | Wild Drops | $21.85 |  | andrey@wilddrops.co |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 268 | PolyTeak | $21.78 | redoakcreations.com | johnm@redoakcreations.com | Site serves only a 404 error page credited "Site powered by Weebly. Managed by Bluehost" — no live content. |  |
| 269 | Hail M Cocktails | $21.77 | hailmcocktails.com | mary@hailmcocktails.com | queued (crawl chunk still running) |  |
| 270 | Pet Wellness Direct | $21.71 | marstrandemail.com | petwellnessdirect-affiliates@marstrandemail.com | Redirects (301) to marstrand.agency, whose footer reads "2026 Marstrand Agency. All Rights Reserved." with US phone "805-500-7575"; no address or suff |  |
| 271 | oilbanker | $20.72 |  | oilbanker@gmail.com | nothing; there is no domain to look at |  |
| 272 | Yuca | $20.46 | yuca.co | keith@yuca.co | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site states 'Yuca LTD, a registered company in the United Kingdom' at 'First Floor, Telecom House, 125-135 Preston Road,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 273 | T is for Tame | $20.21 | tisfortame.com | info@tisfortame.com | Copyright reads '© 2026, T is for Tame' — a bare brand name with no legal entity form, no address and no phone on either the homepage or /pages/contac |  |
| 274 | Lumē Deodorant, LLC | $19.89 | lumedeodorant.com | corbin.jensen@lumedeodorant.com | Homepage returned navigation/header markup only with no footer, and /pages/contact-us returned "404 Not found / Lume Deodorant" — no entity, address, |  |
| 275 | Vital Purple | $19.77 |  | naturalzinginfo@gmail.com | nothing; there is no domain to look at |  |
| 276 | tea facto | $19.62 | maisonovo.com | support@maisonovo.com | Footer is only "© 2026 - MaisoNovo" and /pages/contact returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |  |
| 277 | D'Artisan Shoppe | $19.13 | xtra.co.nz | sophis@xtra.co.nz | Server refuses HTTPS connections on both apex and www: 'connect ECONNREFUSED 202.27.184.102:443' — nothing is served. |  |
| 278 | Goode Health | $19.02 | goodehealth.com | mike@goodehealth.com | queued (crawl chunk still running) |  |
| 279 | Henry Schein | $18.60 |  | matchaia2024@gmail.com | nothing; there is no domain to look at |  |
| 280 | Back Bay Audio | $18.23 | benderbrands.co | jeremy@benderbrands.co | Apex refused connection ('connect ECONNREFUSED 162.255.119.89:443'); www loaded but homepage and /about carry only 'info@benderbrands.co' — no entity, |  |
| 281 | Joyful Moose | $17.85 | joyfulmoose.com | julie@joyfulmoose.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Contact-information page names 'Caribou Creek Cases LLC DBA Joyful Moose' at '653 Oxford Rd, Bonners Ferry ID 83805, Uni  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 282 | Clyrio | $17.80 | clyrio.com | amazon@clyrio.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026 Clyrio LLC. All rights reserved.' with address '5400 S Lakeshore Dr Ste 201 Tempe, AZ 85283'; no Chinese  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 283 | kevinleeme | $17.58 | immieats.com | klee@immieats.com | Footer reads only '2026 immi. All rights reserved.' — no legal entity form, address, phone or ICP; /policies/contact-information returned HTTP 404. |  |
| 284 | IGANCE | $16.94 | goyaba.co | igan@goyaba.co | queued (crawl chunk still running) |  |
| 285 | burakbilisik | $16.60 |  | burakbilisik@gmail.com | nothing; there is no domain to look at |  |
| 286 | The Bean Coffee Company | $16.10 | thebeancoffeecompany.com | craig@thebeancoffeecompany.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page gives "1407 S.Coast Highway, Oceanside, CA 92054" with "(800) 683-7967"; no ICP, CJK, +86 or China address.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 287 | Flipper Aquarium Products | $15.85 | flippercleaner.com | brian@flippercleaner.com | queued (crawl chunk still running) |  |
| 288 | RazorGroup | $15.74 | razor-group.com | john.durkin@razor-group.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Imprint page names "Razor HQ GmbH & Co. KG" and "Razor HQ Management GmbH" at "c/o Razor Group GmbH, Ritterstraße 16-18,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 289 | OLIVIAUMMA | $15.64 | purplepeppercommerce.com | accounts@purplepeppercommerce.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "©2025 Purple Pepper Commerce LLC. All rights reserved." — a US LLC; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon seller. *** |  |
| 290 | PetraTools | $15.00 |  | mili@petratools.com |  |  |
| 291 | Serei | $14.85 |  | hello@sereiskinco.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 292 | Melinda's Hot Sauce | $14.79 | stayhungrydigital.com | jared@stayhungrydigital.com | Site names "Stay Hungry Digital" with geographic US phone "781.844.7976" (Massachusetts area code); no address or legal entity form given, but no ICP, |  |
| 293 | NATIVEPET24 | $14.63 | thenativepet.com | kcampbell@thenativepet.com | 301-redirects to nativepet.com, which shows only "© 2026 Native Pet"; /pages/contact redirects off-site to a Gorgias help centre. No entity form, addr |  |
| 294 | Straight Coastin' | $14.61 |  | fullcirclecommerceinc@gmail.com |  | contact-country: CA / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 295 | Mav Beauty Brands | $14.49 | mavbeautybrands.com | girish.giovanni@mavbeautybrands.com | TLS handshake fails: "unable to verify the first certificate" — no page content could be retrieved. |  |
| 296 | Dolce Flav | $14.27 | dolceflav.com | levi@dolceflav.com | Terms of Service names 'DOLCE FOGLIA FLAVORS' and homepage lists US phone '+1 (213) 575-9444'; no street address published, no ICP, no +86, no CJK con |  |
| 297 | Highland | $14.11 | highland.style | boone@highland.style | Page states 'We are based in Boulder, Colorado!' alongside 'Copyright © 2026 Highland', with no Chinese markers; but no legal entity form or street ad |  |
| 298 | Mobi Lock | $13.63 | locksourcing.com | tanguy@locksourcing.com | https://locksourcing.com issues a "301 Moved Permanently" to the QR-shortener "https://qr1.be/LIZM", which serves only the bare text "LIZM" — the doma |  |
| 299 | MatchaDNA | $13.45 | goyaba.co | matchadna@goyaba.co | queued (crawl chunk still running) |  |
| 300 | Toysmith | $13.38 | toysmith.com | agoldberg@toysmith.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer states '© 2026 Toysmith' with address '541 West Valley Hwy S Pacific, WA 98047 USA' and phone '800-356-0474'; no   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 301 | Spot Detergent | $13.01 | tru-nutbutter.com | reid@tru-nutbutter.com | Copyright reads '© 2026, The Tru-Nut Company.' but the contact page carries unedited Shopify placeholder data — '12345 North Main Street, New York, NY |  |
| 302 | Houswise | $13.00 | houswise.com | tom@houswise.com | Homepage and /pages/contact show no entity, no address, no phone and no ICP — only 'Our support hours: Monday - Friday 9:00 AM - 5:00 PM EST'. |  |
| 303 | Dolcezza by Alluluv | $12.55 |  | wearegoldmamas@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 304 | The Parker-Lambert Agency | $12.53 | parker-lambert.com | dylan.rhodes@parker-lambert.com | Footer says only "Parker-Lambert is an ecommerce, branding, and creative services agency" and /contact returned HTTP 404; no entity suffix, address, p |  |
| 305 | Lovebug Probiotics | $12.44 | lovebugprobiotics.com | ashley@lovebugprobiotics.com | Redirects (301) to lovebug.com, which lists "115 East 34th Street, Suite 1506 New York, NY 10156"; no ICP, +86 or CJK content, but no formally named l |  |
| 306 | Pirate Wizards | $12.31 |  | jamesrbake@gmail.com | nothing; there is no domain to look at |  |
| 307 | ExcelMark | $12.27 | schwaab.com | rbuchanan@schwaab.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "Schwaab, Inc" (US corporate form) with US toll-free "800.935.9877"; no ICP, no CJK, no +86, no China addre  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 308 | adminTPC | $11.92 | talkingpointcards.com | admin@talkingpointcards.com | Homepage shows no entity, address, phone, ICP or CJK (English-only store with FR/DE/ES product variants); /pages/contact returned HTTP 404. |  |
| 309 | Vitamizdd | $11.73 |  | bgoldstein169@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 310 | Novel Brands | $11.35 | novelbrands.com | ava@novelbrands.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© Novel Brands - 2026 All rights reserved" with the address "Fairfield, NJ 07004 - U.S.A"; no ICP, no +86,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 311 | ericmendes | $11.25 | laundryturtle.com | eric@laundryturtle.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "Laundry Turtle - 1348671 B.C. LTD." at "1055 W Georgia St. Suite 2400 Vancouver, BC V6E 3P3" — a British C  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 312 | Cosmic Freeze | $11.09 |  | dianamazer@gmail.com | nothing; there is no domain to look at |  |
| 313 | SHINEFY | $10.28 |  | habibajmi111@gmail.com |  | contact-country: PK / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 314 | BathBlocks | $9.86 | just-think-toys.com | doug@just-think-toys.com | Footer reads only 'Copyright © 2026 Just Think Toys' — no legal entity form, address, phone or ICP; /policies/contact-information returned HTTP 404. |  |
| 315 | RainbowShow | $9.75 |  | heguyun@outlook.com | nothing; there is no domain to look at |  |
| 316 | Pals Socks | $9.34 | palssocks.com | erin@palssocks.com | Apex domain returned an empty response body and the www host failed DNS: "getaddrinfo ENOTFOUND www.palssocks.com". |  |
| 317 | Brick House | $9.27 |  | jonathan.bricker@icloud.com | nothing; there is no domain to look at |  |
| 318 | Menfirst | $9.21 | menfirstusa.com | bea@menfirstusa.com | Redirects (301) to menfirst.com: footer "© 2026, Menfirst" and contact page phone "1-904-900-8730" (Jacksonville, FL area code); no address or suffixe |  |
| 319 | mconley | $8.82 | raakachocolate.com | max@raakachocolate.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Footer reads "copyright 2024 Raaka chocolate ltd. All rights reserved" with the factory address "58 Seabring St Brooklyn  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 320 | Goli Nutrition | $8.76 | goli.com | anthony@goli.com | queued (crawl chunk still running) |  |
| 321 | Yobee Care | $8.60 | yobeecare.com | support@yobeecare.com | Footer reads '© 2026 Yobee Care, Inc / All Rights Reserved' and the page states 'Yobee® is a registered trademark of Yobee Care Inc.' (owned, not lice |  |
| 322 | Benefit Spice: Spice for Good | $8.58 |  | jsk@benefitspice.com |  | contact-country: AF / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 323 | SuperNaturalGoods | $8.55 | nexxuscap.com | sngops@nexxuscap.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2023 Nexxus Capital. All rights reserved." with "800 Druid Rd. E Clearwater, FL 33756" and "(727) 953-34  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 324 | Migrastil | $8.51 | migrastil.com | scott@migrastil.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |  |
| 325 | Kind Lips | $8.43 | kindlips.com | josh@kindlips.com | Footer reads only '© 2026 Kind Lips' — no legal entity form, address, phone or ICP; /policies/contact-information returned HTTP 404. |  |
| 326 | sisterlymarket | $8.39 |  | sisterlymarket@gmail.com | nothing; there is no domain to look at |  |
| 327 | Arterra Pet Science | $8.07 | arterrapet.com | amazon@arterrapet.com | Footer '© 2026 Arterra Pet, All Rights Reserved'; terms of service name 'Arterra Pet Sciences' but the address is the unfilled Shopify template placeh |  |
| 328 | Numeira Dead Sea | $7.97 | numeira.com | z.adwan@numeira.com | 301-redirects to global.numeira.com, which shows only "Numeira Global" with no legal suffix, address, or phone; language selector offers EN/AR/DE/JA — |  |
| 329 | Vitavelle Cosmetics | $7.80 | unitedbrands-group.com | info@unitedbrands-group.com | Both https://unitedbrands-group.com and https://www.unitedbrands-group.com fail TLS: 'Host: unitedbrands-group.com. is not in the cert's altnames: DNS |  |
| 330 | Brilliant Beauty | $7.72 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |  |
| 331 | ieró Beauty™ | $7.56 | ierobeauty.com | alepiashko@ierobeauty.com | Footer reads only '© 2026, ieró Beauty All rights Reserved.' — no legal entity form, address, phone or ICP anywhere on the page. |  |
| 332 | Puppy Pouch | $7.44 | freedomhill-llc.com | dave@freedomhill-llc.com | queued (crawl chunk still running) |  |
| 333 | ZenHalal | $7.20 |  |  |  | DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 334 | Sandunes | $7.18 |  | sanduneshome@gmail.com | nothing; there is no domain to look at |  |
| 335 | FordeBaker | $7.00 | fordebaker.com | laurent@fordebaker.com | queued (crawl chunk still running) |  |
| 336 | nechemya | $6.98 | jmcbinc.com | joel@jmcbinc.com | DNS resolution fails: 'getaddrinfo ENOTFOUND jmcbinc.com' — the domain does not resolve. |  |
| 337 | Glow by hormone university | $6.72 | hormoneuniversity.com | hello@hormoneuniversity.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site states 'Hormone Wellness Group LLC, which is an affiliate of Glow Botanica Inc.' at '5830 E Second Street, Ste. 700  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 338 | Vivid Scribbles | $6.72 | vividscribbles.com | contact@vividscribbles.com | Copyright reads '© 2026 Vivid Scribbles' with no legal entity form, address or phone; /pages/contact returned HTTP 404 and no CJK content was present. |  |
| 339 | vinsguir | $6.60 |  | vinsguir.pickleball@gmail.com | nothing; there is no domain to look at |  |
| 340 | umamibento | $6.49 |  | umami.bentos@gmail.com | nothing; there is no domain to look at |  |
| 341 | Keith | $6.30 | newenglandstories.us | contact@newenglandstories.us | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2026, New England Stories" with the address "305 Constitution Drive, Taunton Massachusetts 02780, United  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 342 | Kronox | $6.00 | cheetahmotorsport.com | julian@cheetahmotorsport.com | 301 redirects to https://kronoxpowersports.com/ whose footer shows only 'KRONOX Powersports' - no legal entity, no address, no phone, no CJK content. |  |
| 343 | Kibou Bag | $5.88 | kiboubag.com | nell@kiboubag.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads '© Kibou 2026' with the physical address '200 16th Street Brooklyn, NY 11215' — a real US street address wi  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 344 | MEEMA | $5.37 | luum.co | a@luum.co | Footer is only "© 2026 luum.co / Powered by Shopify" and the contact page describes "Luum" as "an Amazon launch agency" with no entity, address or pho |  |
| 345 | Timeline | $5.25 | timeline.com | mjaneiro@timeline.com | Copyright line reads '© 2026' with no company name attached; only a US support number '+1-888-631-3359' is shown, and /pages/contact returned HTTP 404 |  |
| 346 | Foldies | $5.04 | thinkcartology.com | taylor@thinkcartology.com | Homepage carries only "© 2026 Cartology. All rights reserved."; /policies/terms-of-service serves a 404 page (Lovable-built site). No address, phone, |  |
| 347 | VitaUp | $4.93 | vitaup.org | support@vitaup.org | website not reachable / no domain — go straight to Amazon seller page + USPTO |  |
| 348 | jdhaley00 | $4.91 |  | phdesign.llc@gmail.com | nothing; there is no domain to look at |  |
| 349 | AURA IN BLOOM | $4.75 |  | reybarcelo@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 350 | Osaber | $4.32 | venturesunbounded.com | omar@venturesunbounded.com | Server refuses connections: 'connect ECONNREFUSED 162.255.119.37:443' on the apex and 'Socket is closed' on www — nothing is served on HTTPS. |  |
| 351 | LOOKNOOK | $4.31 | mepurelab.com | lliu@mepurelab.com | Footer is only "© 2026, MepureLab Powered by Shopify" and the Terms of Service names no legal entity, address or phone (only "sales@mepurelab.com"); n |  |
| 352 | TTolbi | $3.98 |  | contact.ttolbi@gmail.com | nothing; there is no domain to look at |  |
| 353 | Oleksii | $3.97 |  | mymailflorida01@gmail.com | nothing; there is no domain to look at |  |
| 354 | Barely Halal | $3.90 |  | faizan@trybarelyhalal.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 355 | leolandau | $3.84 |  | leolandau@gmail.com | nothing; there is no domain to look at |  |
| 356 | Bubble Sponge | $3.72 | bubblesponge.com | info@bubblesponge.com | Footer shows only 'All rights reserved by bubblesponge.com'; /pages/contact-us returned HTTP 404. No entity, address, phone or CJK content. |  |
| 357 | Teracube | $3.60 | myteracube.com | sharad@myteracube.com | Footer is only "© 2024 Teracube" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |  |
| 358 | alexdittrich | $3.60 | brightventuresco.com | alex@brightventuresco.com | TLS handshake fails on both apex and www: 'certificate has expired' - site cannot be fetched. |  |
| 359 | Aromafume | $3.35 | aromatan.com | taha@aromatan.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site names three entities with matching addresses — 'Aromatan Brands Private Limited' (Lower Parel, Mumbai, India), 'Aro  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 360 | Ecomcy | $3.27 | ecomcy.co.uk | juan@ecomcy.co.uk | queued (crawl chunk still running) |  |
| 361 | Matjaz | $3.25 |  | matjaz.valencic@yahoo.com | nothing; there is no domain to look at |  |
| 362 | Aiming Fluid Golf | $3.21 |  | aimingfluidgolf@gmail.com | nothing; there is no domain to look at |  |
| 363 | TokyoRush | $3.08 | qintama.com | sales@qintama.com | DNS resolution failed: "getaddrinfo ENOTFOUND qintama.com" — domain does not resolve. |  |
| 364 | Ouch Baby | $3.00 |  | princenasario@gmail.com | nothing; there is no domain to look at |  |
| 365 | VZJZHAN | $2.86 |  | chaolin405@gmail.com | nothing; there is no domain to look at |  |
| 366 | Alodia | $2.72 | alodiahaircare.com | isfahan@alodiahaircare.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of service name 'Alodia Healthy Hair LLC' at 'PO Box 1500, Bowie, Maryland 20717, United States'; no ICP, no CJK,   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 367 | Bonded By Stories | $2.70 |  | brightbridgeventures@gmail.com | nothing; there is no domain to look at |  |
| 368 | Aum Active | $2.60 | hooraycommerce.com | marketing@hooraycommerce.com | MY EARLIER WEBSITE CRAWL said CHINA (weak) — The site ships a full Simplified-Chinese localisation — nav items '中文', '服务', '案例分析', '关于我们', '时间轴', '联系我们' — and its ca |  |
| 369 | tukaho | $2.55 | tukaho.com | support@tukaho.com | Copyright reads '© 2026. All rights reserved.' with no entity name attached; /pages/contact shows no company name, address or phone, and no CJK conten |  |
| 370 | Goat Soap | $2.52 | machetesystems.com.au | tim@machetesystems.com.au | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Footer names "Machete Systems Pty Ltd, A Smollan Company" at "150 Albert Rd, South Melbourne VIC 3205" with phone "+61 1  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon … |  |
| 371 | SMOLBOL | $2.46 | mismifoods.com | felipe@mismifoods.com | Fetch blocked before any content was returned: "Unable to verify if domain mismifoods.com is safe to fetch." |  |
| 372 | BnD US | $2.10 |  | bnd.us.official@gmail.com | nothing; there is no domain to look at |  |
| 373 | Nuanced Media | $2.10 | nuancedmedia.com | ryanflannagan@nuancedmedia.com | Homepage footer shows only "© 2026 Nuanced Media. All rights reserved." and the /contact page carries no entity suffix, address, or phone; no Chinese |  |
| 374 | Gemonklee | $2.01 |  | gemonklee@outlook.com | nothing; there is no domain to look at |  |
| 375 | itservicesVremi | $1.93 | mohawkgp.com | it-services+vremi@mohawkgp.com | Apex fails TLS — "Host: mohawkgp.com. is not in the cert's altnames: DNS:*.azurewebsites.net" — and www does not resolve ("getaddrinfo ENOTFOUND www.m |  |
| 376 | Loquacious Games | $1.90 |  | david@loquaciousgames.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 377 | Matrescence | $1.86 | matrescenceskin.com | raquel@matrescenceskin.com | Footer is only "© 2026 - Matrescence" and /pages/contact lists no entity, address or phone; no ICP, +86 or CJK content. |  |
| 378 | Milspin | $1.83 | milspin.com | dpeters@milspin.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: "© 2026 MILSPIN, All rights reserved." with US address "30 Diana Ct, Cheshire, CT 06410" and phone "+16146648151  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 379 | Level Up Pup | $1.65 |  | leveluppup1@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 380 | MyMed | $1.60 |  | toolssubscription@gmail.com | nothing; there is no domain to look at |  |
| 381 | barebotanicsteam | $1.60 | barebotanics.co | team@barebotanics.co | Footer '© 2026, Bare Botanics Skincare'; terms of service say 'This website is operated by Bare Botanics Skincare' and give only 'hello@barebotanics.c |  |
| 382 | mondaymoose | $1.52 | mondaymoose.com | dani@mondaymoose.com | Footer is only "© 2026, Monday Moose" and /pages/contact returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |  |
| 383 | Elevate Pet Provisions | $1.50 | ynhco.com | ethan@ynhco.com | Two fetches (https://ynhco.com and https://ynhco.com/pages/about-us) both returned an empty response body — the site serves no readable content to fet |  |
| 384 | ELEMITO | $1.50 |  | elemito.llc@gmail.com | nothing; there is no domain to look at |  |
| 385 | PureHimalayanShilajit | $1.50 | nexxuscap.com | phsops@nexxuscap.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2023 Nexxus Capital. All rights reserved." with "800 Druid Rd. E Clearwater, FL 33756" and "(727) 953-34  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark owner + Amazon sell… |  |
| 386 | Settini | $1.44 | settini.com | marketing@settini.com | Terms of Service names only "Settini" with SMS line "+18886085301" (non-geographic US toll-free) and contact@settini.com; no legal entity form, no add |  |
| 387 | Supplements Studio | $1.38 |  | mvstudioproducts@gmail.com | nothing; there is no domain to look at |  |
| 388 | Swigzy | $1.35 | swigzy.com | info@swigzy.com | Terms of Service names only "swigzy" with info@swigzy.com; no legal entity form, address, phone, ICP or CJK. |  |
| 389 | GYMGUM | $1.09 |  | gymgumllc@gmail.com | nothing; there is no domain to look at |  |
| 390 | Signs That Pop | $0.96 |  | derron99@gmail.com | nothing; there is no domain to look at |  |
| 391 | Darlington Snacks | $0.90 | darlingtonsnacks.com | jfeasel@darlingtonsnacks.com | Both apex and www returned 'HTTP 403 Forbidden' - site blocks fetching. |  |
| 392 | ANTOMILIO | $0.75 |  | antomiliobiz@gmail.com |  | contact-country: CA / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 393 | yaqubnmc1 | $0.72 | themedicaptain.com | yaqub@themedicaptain.com | Terms of Service still carries unfilled Shopify template placeholders "[INSERT BUSINESS ADDRESS]" and "[INSERT BUSINESS PHONE NUMBER]"; only contact i |  |
| 394 | DecorChiq | $0.60 | baard.se | maria@baard.se | Both https://baard.se and https://www.baard.se returned an empty document — no footer, no copyright, no page body. Nothing retrievable. |  |
| 395 | Argosy QR | $0.60 | argosyqr.com | kevin@argosyqr.com | Homepage names 'Argosy QR' with no legal suffix; /pages/contact gives only 'hello@argosyqr.com'; /policies/terms-of-service is HTTP 404. No entity, ad |  |
| 396 | sharmony | $0.56 |  | sinabro.trading@gmail.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 397 | bioworld | $0.50 | bioworldmerch.com | joem@bioworldmerch.com | Homepage footer carries no entity, address or phone; /pages/contact-us and /pages/contact both HTTP 404. No ICP, no CJK, no +86. |  |
| 398 | acorn+oak | $0.47 |  | ken@shopacorn.com |  | contact-country: US / DB-signals: wayward_country_other(negative->not_china); wayward_country_other(negative->not_china) |
| 399 | Dragon Grips and Bright Knight Decals | $0.45 | dragonlairdesigns.com | joel@dragonlairdesigns.com | Footer shows only 'Dragon Lair Designs © 2023'; /policies/terms-of-service returned HTTP 404. No legal entity, address, phone, ICP or CJK content. |  |
| 400 | Levonascent | $0.35 | bmitraders.com | jonathan@bmitraders.com | Both https://bmitraders.com and https://bmitraders.com/pages/contact returned 'HTTP 500 Internal Server Error' - site does not serve content. |  |
| 401 | Kavguine | $0.30 |  | neophonic.low@gmail.com | nothing; there is no domain to look at |  |


---

*Generated 2026-07-18 from the live billing/verdict system (401 brands
with verdict=unknown and positive net revenue). Amounts are net of refunds.
Research context joined from prior crawl notes (356/401 matched);
the rest are name-only. Nothing here is a final verdict — these are the exact
brands whose nationality is undecided. Return findings to the person who gave you
this file.*
