# The 549 Amazon seller-of-record queue — review list

> **Purpose:** the A-track. These are the 549 brands on `AMAZON-SELLER-LIST.csv` whose nationality we'd resolve from their **Amazon seller-of-record** (INFORM Consumers Act: Amazon must publish each high-volume seller's business name + address). Mechanical rule: address in **China/HK/Macau → china**; anywhere else → **not_china**; **mail-drop → HELD (a question for Tim, never auto-cleared)**; no seller page → stays **unknown**.

> **Status: NOTHING here is applied — every brand keeps its current verdict** (Tim, 2026-07-16: "keep those as unknown for now"). This is a read-only review to decide the next step (incl. **Q0**: does clearing to not_china require the trademark owner AND the seller-of-record to be the SAME non-China entity at a REAL address?).

> **Source:** `venture-ecomlever/.../research-handoff/AMAZON-SELLER-LIST.csv` (+ RESEARCH-LIST / BATCH-2 for domain/email/notes). Verdict + collected joined live from prod (cip_110).


## Where the 549 stand today

- **548** brands on the list.

- **413 are still `unknown` AND billing us** — the priority queue, **$82,734.90** collected across them (money whose ownership we can't yet call).

- **8** are `unknown` and not currently billing.

- **127** already have a verdict (resolved by other signals since the list was drawn) — listed last for reference; the seller check would only confirm them.


## A. Priority — `unknown` AND billing us (money at stake)

| Brand | Collected | Domain | Email | Research note |
| --- | --- | --- | --- | --- |
| Cresimo | $4,546.88 | vimbly.com | nicole@vimbly.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to www.vimblygroup.com, which shows '© Vimbly Group. All rights reserved' and address '79 Madison Avenue,   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Bird Buddy | $3,982.14 | mybirdbuddy.com | kara@mybirdbuddy.com | Homepage has no footer entity and only says "We pride ourselves on doing our best work from New York" with no address; /pages/contact 301-redirects to |
| MIKO | $3,319.56 | shopmiko.com | david_arazi@shopmiko.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service lists the operator's mailing address twice as "1190 Gravesend Neck Road, Suite B Brooklyn NY 11229"; no  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| bedbath | $3,279.85 | bedbathnmore.com | jesse@bedbathnmore.com | Footer shows only '2021 Bed Bath N' More. All rights reserved.'; /pages/contact-us and /policies/terms-of-service both HTTP 404. No entity, address, p |
| Pure Instinct / VWELL / Coochy Plus | $3,122.64 | intimd.com | marketing@intimd.com | Only '© 2026, IntiMD' and phone '(626) 315-8531'; no legal entity form and no address, and /policies/contact-information returned HTTP 404 — a US area |
| Woodenhouse | $2,305.07 | cutluxe.com | dor@cutluxe.com | Homepage returned product listings with no footer entity/address/phone; /policies/terms-of-service returned HTTP 404. Only CJK seen is Japanese produc |
| Smart Home & Garden | $2,258.34 | dtcretail.com | daven@dtcretail.com | Footer shows only '© DTC Retail'; /policies/terms-of-service returned HTTP 404. No legal entity, address, phone, ICP or CJK content. |
| moralve | $2,038.64 | moralve.com | support@moralve.com | Footer is only "© 2026 MORALVE .All Rights Reserved." and /pages/contact-us is a bare contact form with no entity, address or phone; no ICP, +86 or CJ |
| SellerX Germany GmbH PO000SXGDE003245 | $2,030.95 | sellerx.com | maksymilian@sellerx.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — "©SellerX 2021" with headquarters "Chausseestraße 19, 10115 Berlin" — a German GmbH; NOTE it also lists a mainland-China  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| BCOZZY | $1,950.15 | bcozzy.com | contactus@bcozzy.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site states 'BCOZZY Products Ltd', '1221 Brickell Avenue, Suite 900 - #672, Miami Florida 33131, United States', '+1 (88  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| SplashEZ | $1,817.17 | a2playusa.com | yaroslav@a2playusa.com | Contact page states 'A2PLAY LLC, 124 Broadkill Rd #429 Milton, DE 19968-1008 USA' and '+1 877 394 6211'; no ICP, no CJK, no +86. Confidence weak becau |
| JLab | $1,742.53 | jlab.com | apinvoice@jlab.com | Homepage footer was truncated by the fetch before any company details were reached, and /pages/contact-us returned HTTP 404 — no entity, address, phon |
| Planetary Design | $1,662.48 | planetarydesign.us | natalie@planetarydesign.us | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to planetarydesign.com, whose footer reads "© 2026 Planetary Design." with "9255 Bonner Mill Rd, Bonner, M  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| True Fresh | $1,620.25 | smartvisionus.com | info@smartvisionus.com | Footer names "Smart Vision LLC" and the contact page gives "294 Bay Meadows Ave. Bay Shore, NY 11706"; the listed phone "(406) 555-0120" is a reserved |
| INICAT | $1,098.01 | inicat.net | info@inicat.net | DNS resolution fails: 'getaddrinfo ENOTFOUND inicat.net' — the domain does not resolve. |
| Eversprout | $968.51 | eversprout.com | admin@eversprout.com | queued (crawl chunk still running) |
| Colugo | $949.14 | colugo.com | marketplace-admin@colugo.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names 'Colugo LLC' at '929 108th Ave NE, Suite 1410, Bellevue, WA 98004'; no Chinese markers.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via |
| unboxme | $948.47 | unboxme.com | moshe@unboxme.com | Copyright reads '© 2026, Unboxme All Rights Reserved' on both the homepage and /pages/contact — no legal entity form, no address, no phone, no CJK con |
| Jerome Alexander Cosmetics | $926.19 | jeromealexander.com | accountspayable@jeromealexander.com | Homepage and /pages/contact-us show 'Jerome Alexander' as a brand name only — no corporate designation, no address, no phone, no ICP, no CJK. |
| Primely | $910.31 | amerify.co | owais@amerify.co | Homepage and /about list 'Address 30 N Gould St. Sheridan, WY 82801' and 'Call or Text +1 (480) 420 7141'; copyright is bare 'Copyright © 2026' with n |
| ivizel | $833.33 | dr-brace.com | itzik@dr-brace.com | Homepage '© 2026, Dr. Brace All Rights Reserved.' and Terms of Service name only 'Dr. Brace' - a brand, not a legal entity. No address, phone, ICP or |
| Newton Baby | $791.84 | newtonliving.com | matthew.shaw@newtonliving.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to www.newtonbaby.com, whose footer reads "© 2026 Newton Baby LLC"; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check  |
| Carnation | $791.34 | carnation-inc.com | skhazin@carnation-inc.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Carnation Enterprises' with '510 Woodland Knolls Road, Suite #2 Germantown Hills, IL, 61548, USA' and US phone   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Mindsight | $780.10 | mindsightnow.com | ted@mindsightnow.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names the operator "THINGS THAT WORK INC." at "4970 Willow Stone Heights, Colorado Springs CO 80906, Un  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Gorillaz LLC | $765.82 | accelclub.pro | iliya.shkuruk@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Neutralyze | $672.35 | onlinebrandgrowth.com | jon@onlinebrandgrowth.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Footer reads "© 2026 Remus, LLC. All Rights Reserved." with "4909 Linden Forest Lane, Charlotte, NC 28270" and "+1516860  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| Best Brands | $624.57 | bestbrands.com | ecommerce@bestbrands.com | Copyright line names 'Best Brands Consumer Products Inc.'; /contact is HTTP 404 so no address or phone published. No ICP, no CJK, no +86. Weak: entity |
| Divi Scalp Care | $619.21 | diviofficial.com | grace@diviofficial.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026 Divi Official Inc.'; Terms of Service names 'Divi Official, LLC, and its subsidiaries and affiliated com  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Think Tank Scholar | $601.77 | thinktankscholar.com | min@thinktankscholar.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names the operator "Think Tank Scholar, LLC" with a governing-law clause under "the laws of California"  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| COSMO Technologies | $585.25 | cosmotogether.com | eric@cosmotogether.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'COSMO Technologies Inc.' at '1312 17th Street #450 Denver, CO 80202'; no Chinese markers.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark o |
| Ryddelighome | $578.05 |  | mygadgetbox9@gmail.com | nothing; there is no domain to look at |
| SweatBlock | $574.79 | sweatblock.com | kpurles@sweatblock.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names the operator "DC Alpine Partners, LLC – DBA SweatBlock" with a Utah governing-law clause; no ICP,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| NoCry | $572.63 | nocry.com | robin@nocry.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service section 5 states content and trademarks are "the property of NoCry OÜ or Hardly Working OÜ" — OÜ is the  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| glocusent | $570.19 | glocusent.com | ingrid@glocusent.com | queued (crawl chunk still running) |
| BigFly | $522.83 | bill.com | big-fly@bill.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '©2026 BILL Operations, LLC. BILL, the BILL logo, and the "b" logo are trademarks of BILL Operations, LLC.' — US  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| maisonovo | $511.39 | maisonovo.com | support+1@maisonovo.com | Footer is only "© 2026 - MaisoNovo" and /pages/contact returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |
| Nixplay | $499.64 | nixplay.com | accounts@nixplay.com | Homepage and /policies/terms-of-service both show only "© 2026 Nixplay. All rights reserved" and "support@nixplay.com" — no legal entity suffix, no ad |
| Natemia | $496.76 | forumbrands.com | jack@forumbrands.com | queued (crawl chunk still running) |
| liuliuby | $487.14 | liuliuby.com | mliu@liuliuby.com | Homepage footer is only "© 2020 by liuliuby" and /about lists no entity, address or phone; no ICP, +86 or CJK content, so nothing establishes origin e |
| Eve Hansen | $486.12 | evehansen.com | support@evehansen.com | queued (crawl chunk still running) |
| Just Play | $485.72 | justplayproducts.com | slopezmora@justplayproducts.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Contact page names 'Just Play, LLC' at '4850 T-Rex Avenue, Suite 100 Boca Raton, FL 33431 U.S.A.' — a US LLC with a matc  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| Lebanta | $483.50 |  | trylebanta@gmail.com | nothing; there is no domain to look at |
| LUNAKAI | $465.00 | epochbrands.io | razvan@epochbrands.io | queued (crawl chunk still running) |
| moonjuice | $462.97 | moonjuice.com | barry@moonjuice.com | Footer is only "© 2026 Moon Juice" and /pages/contact lists no entity, address or phone; no ICP, +86 or CJK content. |
| vitalisuvorov | $460.98 | themothership.ai | vitalii.suvorov@themothership.ai | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© The Mothership 2023" with "144 Shoreditch High Street, London, E1 6JE, UK"; no ICP, CJK, +86 or China ad  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Mind-Glowing | $460.01 | enomadscompany.com | contact@enomadscompany.com | queued (crawl chunk still running) |
| ezbombs | $425.06 | ezbombs.com | nichole@ezbombs.com | queued (crawl chunk still running) |
| VANDEL | $417.17 | wayward.com | rebecca+1@wayward.com | Footer reads '© 2026 Wayward. All rights reserved.' with no legal entity form, address or phone; /pages/contact returned HTTP 404 and no CJK content w |
| Shacke | $407.09 | shacke.com | contact@shacke.com | Terms of Service names the store operator as "Velocity Media LLC" (US LLC form); no address or phone published, and no ICP, CJK or +86 anywhere. |
| JadeYoga | $404.59 | jadeyoga.com | info@jadeyoga.com | Only '© 2026, [JadeYoga]' plus phone '610-828-4830/888-784-7237 (toll free)'; no legal entity form and no address on the homepage or /pages/contact-us |
| Koala Lifestyle | $403.90 | koalalifestyle.com | kevin@koalalifestyle.com | Footer reads only '© 2026 Koala Lifestyle / All rights reserved' — no legal entity form, address, phone or ICP; /policies/contact-information returned |
| Coda Music Technologies | $397.22 | codamusictech.com | rob@codamusictech.com | Footer: '© 2026 Coda Music Technologies / Seattle, WA' - US city/state only, no street address; no ICP, no +86, no CJK content. |
| BlissLights | $395.56 | blisslights.com | dfeldner@blisslights.com | Footer: '© 2026 BlissLights. All rights reserved.' with US toll-free '888.868.4603'; no ICP, no CJK, no +86, no Chinese address. Weak: no legal suffix |
| Raw Science | $395.16 | traitvis.com | ceo@traitvis.com | Two fetches (https://traitvis.com and https://traitvis.com/about) both returned an empty response body — the site serves no readable content to fetche |
| PrideSports | $389.51 | gathroutdoors.com | mcobden@gathroutdoors.com | queued (crawl chunk still running) |
| HYDRO CELL | $378.45 | hydrocellusa.com | dane.ludolph@hydrocellusa.com | Homepage shows no entity, no address, no phone, no ICP and no CJK content; /pages/contact returned HTTP 404. |
| Crave | $365.39 | cravedirect.com | vitaly@cravedirect.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service lists 'Crave Direct' at '5570 S Irwin Drive Wasilla Alaska US 99623'; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-c |
| AWARLT | $349.24 | awarlt.com | contact@awarlt.com | Footer reads 'American Wellness Authority(TM) 1301 W. Park Ave Suite F Ocean, NJ07712'; no ICP, no CJK, no +86. Weak: name carries no legal suffix (LL |
| JungKwanJang | $348.69 | amp3pr.com | michael+1@amp3pr.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2021 AMP3 Public Relations / All Rights Reserved' with '210 West 29th St. 6th Floor, New York, NY 10001' and   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Klymit | $335.57 | gathroutdoors.com | mcobden@gathroutdoors.com | queued (crawl chunk still running) |
| Click and Carry | $335.37 | fluencerfruit.com | liz+cc@fluencerfruit.com | queued (crawl chunk still running) |
| goodwipes | $334.96 | goodwipes.com | jack@goodwipes.com | queued (crawl chunk still running) |
| Vitamin Bounty | $331.90 | vitaminbounty.com | tarek@vitaminbounty.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page states 'Vitamin Bounty c/o Matherson Organics LLC' at '1901 Avenue of the Stars, 19th Floor Los Angeles, CA  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Hewlett Packard Enterprise Instant-On | $316.98 | phelpsunited.com | wayward.admin@phelpsunited.com | Both https://phelpsunited.com and https://www.phelpsunited.com returned "HTTP 404 Not Found" — no site served. |
| SmartLabels | $304.83 | qrsmartlabels.com | david@qrsmartlabels.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page lists "336 Bon Air Ctr #129 Greenbrae, CA 94904" under "© 2026 SmartLabels. All rights reserved"; no ICP, n  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Ahava | $296.19 | ahava.com | lolo.d@ahava.com | Copyright line reads '© 2026 AHAVA, Inc. All Rights Reserved'; no ICP, no CJK, no +86, no Chinese address. Weak because no physical address is publish |
| TOP-UP | $291.58 |  | eskopina86@gmail.com | nothing; there is no domain to look at |
| Elgin | $286.83 | amplisell.com | brady@amplisell.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Copyright © 2025 AmpliSell. All Rights Reserved.' with '500 Heights Blvd Suite 307 Houston, TX 77007' and '(205  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Gout and You | $283.67 |  | spirok75@gmail.com | nothing; there is no domain to look at |
| ACDC LLC | $278.07 | accelclub.pro | klim.sotnikov+3@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Jungle Powders | $271.19 | junglepowders.com | info@junglepowders.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer gives the address 'Jungle Powders / Vee 4-10 / Parnu, 80011 / Estonia' under 'Copyright © 2026 Jungle Powders' —   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Kapike | $270.70 |  | kapike.official@gmail.com | nothing; there is no domain to look at |
| KAHI | $269.04 | amp3pr.com | michael+2@amp3pr.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2021 AMP3 Public Relations / All Rights Reserved' with '210 West 29th St. 6th Floor, New York, NY 10001' and   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Deep Purple LLC | $266.61 | accelclub.pro | klim.sotnikov+4@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| CaniBrands USA HC Corp | $264.93 | canibrands.com | chrislord@canibrands.com | Homepage and /pages/contact-us both returned 'HTTP 403 Forbidden' - site blocks fetching. |
| Turquaz | $259.52 | robemart.com | bill@robemart.com | Terms of Service state "Robemart.com is a registered trademark of SATAY INTERNATIONAL" and the site banner reads "SHIPS FROM CALIFORNIA" with "(844) 7 |
| ECCOSOPHY | $259.44 | eccosophy.com | sophia@eccosophy.com | queued (crawl chunk still running) |
| Retail Arbitrage | $258.20 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |
| vibesearplugs | $248.68 | discovervibes.com | jamie@discovervibes.com | Footer shows only 'Copyright © 2025 Vibes / All Rights Reserved'; /policies/terms-of-service returned HTTP 404. No entity, address, phone, ICP or CJK |
| ALTA | $242.79 | wayward.com | rebecca+3@wayward.com | Footer reads '© 2026 Wayward. All rights reserved.' with no legal entity form, address or phone; /pages/contact returned HTTP 404 and no CJK content w |
| Sprigrown | $237.74 | growtua.com | larry@growtua.com | queued (crawl chunk still running) |
| Realizations | $230.62 | dallenreber.com | me@dallenreber.com | Both https://dallenreber.com and https://www.dallenreber.com returned 'HTTP 404 Not Found' - no site served. |
| PetLoversHQ | $229.85 | petlovers.com | kevin@petlovers.com | Homepage shows only "©2026 PetLovers. All rights reserved."; both /about and /contact returned HTTP 404 — no entity suffix, address, phone, ICP, or CJ |
| Billion Pets | $229.74 |  | nasir.vaidya786@gmail.com | nothing; there is no domain to look at |
| Zen Dew | $224.94 | b-glowing.com | lisa@b-glowing.com | Footer shows only 'Copyright © 2024 b-glowing - All Rights Reserved'; /pages/contact-us and /pages/contact both HTTP 404. No entity, address, phone, I |
| Food Huggers | $224.83 | foodhuggers.com | fh.admin@foodhuggers.com | queued (crawl chunk still running) |
| Happy Head | $219.53 | happyhead.com | accounting@happyhead.com | queued (crawl chunk still running) |
| Champion | $215.49 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |
| Amanda Creation Inc. | $214.91 |  | mkmiraclemakers@aol.com | nothing; there is no domain to look at |
| Freshero | $214.51 |  | fresherous@gmail.com | nothing; there is no domain to look at |
| LyfeFuel | $212.42 | lyfefuel.com | chris@lyfefuel.com | Footer is only "© 2026, LyfeFuel" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |
| Dreamland Baby | $205.50 | dreamlandbabyco.com | mike@dreamlandbabyco.com | Both apex and www returned 'HTTP 403 Forbidden' - site blocks fetching. |
| SEVEN POTIONS | $201.51 |  | sevenpotions@gmail.com | nothing; there is no domain to look at |
| jakelangley | $200.46 | lumanutrition.com | jake@lumanutrition.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "Valhalla Media LLC" with US phone "(323) 274-1407" (Los Angeles area code); no ICP, +86 or CJK content any  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Funcils | $199.81 |  | anuj2911@gmail.com | nothing; there is no domain to look at |
| Itari | $199.30 | itriace.com | wa-it@itriace.com | DNS resolution fails: 'getaddrinfo ENOTFOUND itriace.com' — the domain does not resolve. |
| Beast Bites Supplements | $192.43 | getbeastbites.com | support@getbeastbites.com | queued (crawl chunk still running) |
| Crafty Happitoys | $188.03 | happi.toys | hello@happi.toys | queued (crawl chunk still running) |
| Super Area Rugs | $186.71 | superarearugs.com | randy@superarearugs.com | Homepage carries only "© 2026 - Super Area Rugs"; /pages/contact returned HTTP 404. No entity form, address, phone, ICP or CJK. |
| Great Bay Home | $185.43 | greatbayhome.com | taylor.oneil@greatbayhome.com | queued (crawl chunk still running) |
| MatthewMangione | $184.48 | coppercompression.com | matthew@coppercompression.com | Homepage shows only '© 2026 Copper Compression'; /pages/contact-us returned HTTP 404. No legal entity, address, phone, ICP or CJK content. |
| Little Spoon | $179.43 | littlespoon.com | affiliate@littlespoon.com | Footer: "© 2026 Little Spoon, Inc." — a US "Inc."; no address or phone given, and no ICP, +86 or CJK content anywhere. |
| Earth Rated | $176.43 | earthrated.com | tamara.t@earthrated.com | Contact page states 'Our office is located in Montreal, Canada.'; footer 'Earth Rated 2026 ©'. No street address or entity suffix published; no ICP, n |
| Aerosmith LLC | $174.09 | accelclub.pro | klim.sotnikov+1@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| NatLeo USA Supplements | $170.92 | natleousasupplements.com | jonathan@natleousasupplements.com | Homepage shows only "© 2023 NanoCumin. All Rights Reserved." and "Copyright © 2022 NatLeo USA Supplements"; /pages/about-us gives no address, phone, o |
| Prepared4X | $167.28 | titanignite.com | andrew.spiller@titanignite.com | Footer shows '© Titan Ignite / All Rights Reserved' and nothing else — no entity form, address, phone, or CJK content on the homepage or /pages/contac |
| Trueseamoss | $155.87 | trueseamoss.com | amazonaffiliate@trueseamoss.com | Copyright reads '© 2026, TrueSeaMoss.' with no entity form, address or phone; /pages/contact mentions only product sourcing 'off the coast of Nha Tran |
| Scotch Porter | $155.35 | scotchporter.com | christian@scotchporter.com | Homepage carries only "© 2026 Scotch Porter. All Rights Reserved."; /pages/contact returned HTTP 404. No entity form, address, phone, ICP or CJK to de |
| Kanga Toys | $153.92 | mikigraphicdesign.com | michelle@mikigraphicdesign.com | Homepage has no footer/copyright line and /pages/contact shows no entity, address or phone; no ICP, +86 or CJK content. |
| LDC Lux Decor Collection | $152.11 | luxdecorcollection.com | zeshan@luxdecorcollection.com | Footer is only "Copyright © Lux Decor Collection" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |
| Classic Turkish Towels | $151.20 | makroteks.com | ismail@makroteks.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "2020 Makroteks ® All Rights Reserved." with "AKHAN MAH. ATATURK BULV. NO: 117 DENIZLI/TURKEY 20155" and "8  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| ORCA | $149.54 | gathroutdoors.com | mcobden@gathroutdoors.com | queued (crawl chunk still running) |
| Spotted Dog Company | $147.27 | poseidonbrands.com | jason.garvin@poseidonbrands.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer shows "Poseidon Brands" with "3525 South School Avenue Suite C, Fayetteville, AR, 72701, United States" and "4799  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Bubzi Co | $144.36 | bubzico.com | elijah@bubzico.com | Homepage and /pages/contact-us show only '© 2026, Bubzi Co' - a brand name, not a legal entity; no address, phone, ICP or CJK content. |
| Optimal Carnivore | $140.50 | optimalcarnivore.com | richard@optimalcarnivore.com | Homepage shows "© 2026, optimalcarnivore"; Terms of Service give only the email "richard@optimalcarnivore.com" with no legal entity, address, or phone |
| Jerk Fit Ventures Inc | $138.47 | jerkfit.com | jeff@jerkfit.com | Footer reads only '© 2026, [JerkFit] [Powered by Shopify]' — no entity, address, phone or ICP on the page; /policies/contact-information returned HTTP |
| HONEYERA | $134.40 | honeyera.com | leo@honeyera.com | Homepage and /pages/contact show no entity, no address, no phone and no ICP — the only contact detail is the email 'support@honeyera.com'. |
| Arden Line | $130.91 | ardenline.com | arden@ardenline.com | Footer '© 2026, Arden Line'; /pages/contact and /policies/terms-of-service give only the email 'arden@ardenline.com' — no legal entity, no address, no |
| MAX'IS Creations | $127.76 | maxiscreations.com | jen@maxiscreations.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "MAX'IS Creations, Inc." at "6 Liberty Square #2751 Boston, MA 02109"; no ICP, +86 or CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check vi |
| Weljoy | $125.60 |  | zhencheng1588@hotmail.com | nothing; there is no domain to look at |
| CLOCKY LLC | $122.74 | clocky.com | team@clocky.com | Footer: '© CLOCKY, LLC 2025' and Terms of Service names 'CLOCKY, LLC'; no address published, no ICP, no CJK content (language selector offers EN/DE/ES |
| MODA Works | $121.71 |  | bestsetpet@gmail.com | nothing; there is no domain to look at |
| kyachminov | $121.54 | argobrands.com | marketing@argobrands.com | Both https://argobrands.com and https://www.argobrands.com return 'HTTP 404 Not Found' at the site root — no site content served. |
| Phoenix Worldwide | $120.82 | pinestatebrands.com | matt@pinestatebrands.com | Homepage shows only "Pine State Brands" with no copyright entity, address, or phone, and /contact returned HTTP 404; no ICP, no +86, no CJK content. |
| Hide & Scratch | $119.12 | hideandscratch.com | admin@hideandscratch.com | Footer reads only '© 2026, [Hide & Scratch]' — no entity form, address, phone or ICP; /pages/contact returned HTTP 404. |
| luxail | $118.74 | customselect.net | rachel@customselect.net | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Custom Select Inc.' with '20 Robert pitt Dr, Monsey NY 10952' and phone '+1 (845) 244-6188'; no Chinese markers  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Intelligent Blends | $117.72 | vitacup.com | tessa@vitacup.com | Footer reads '© 2026, VitaCup/. All rights reserved.' with a US toll-free number '1-(888) 857-VITA (8482)' but no legal entity form and no address; th |
| Core Med Science | $117.30 | vendocommerce.com | jaclyn.carleton@vendocommerce.com | 301-redirects to www.onepltfrm.com whose only footer text is '© PLTFRM. 2026. All Rights Reserved' — no legal entity form, address, phone, ICP or CJK |
| ShopBobbys | $117.04 | shopbobbys.com | raymond@shopbobbys.com | Footer names "shopbobbys.com LLC" (US LLC form) with New-Jersey-area phone "908-289-1507"; /pages/contact 404'd; no ICP, CJK, +86 or China address fou |
| Tiege Hanley | $115.01 | tiege.com | patrick.chojnacki@tiege.com | Homepage carries only "© Tiege Hanley 2026"; /pages/contact returned HTTP 404. No entity form, address, phone, ICP or CJK. |
| Feculs | $113.49 |  | modernrow@outlook.com | nothing; there is no domain to look at |
| SAPHUS | $112.97 |  | saphussoap@gmail.com | nothing; there is no domain to look at |
| riptoned | $112.18 |  | markpasay@gmail.com | nothing; there is no domain to look at |
| Gamakay | $109.05 |  | gkgamakay@gmail.com | nothing; there is no domain to look at |
| Oaktiv | $108.86 | lifeprofitness.com | blumy@lifeprofitness.com | Both https://lifeprofitness.com and https://lifeprofitness.com/pages/contact return "HTTP 403 Forbidden" — the site blocks automated fetching. |
| Checkered Chef | $104.88 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |
| Stonecutter | $100.95 | stonecutter.nyc | dominique@stonecutter.nyc | Homepage carries only "© 2026 Stonecutter NYC. All rights reserved."; /pages/contact returned HTTP 404. No address, phone, ICP or CJK. |
| Superior Brands | $99.14 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |
| Bywoods | $98.96 | broombi.com | brian@broombi.com | Footer reads 'Original Broombi by 3Jalbi and Cogent Global, Inc.' - a US-form corporate entity; no address, phone, ICP or CJK content on homepage or / |
| Sit. Stay. Forever. | $98.84 | sitstayforever.com | steve@sitstayforever.com | Footer gives "© 2026, Sit Stay Forever" with US address "90 Bridge St, Suite 3166, Westbrook, ME 04092" (a virtual-mailbox-style suite, hence weak); n |
| KoolaBaby | $96.59 | ygbgroup.com | shaul@ygbgroup.com | Two fetches (https://ygbgroup.com and https://www.ygbgroup.com) both returned an empty response body — the site serves no readable content to fetchers |
| eComCatalyst | $88.08 | tlooutdoors.com | fred@tlooutdoors.com | Only a US-format phone '912-324-7820' appears; there is no company name in the copyright line, no address, and /pages/contact returned HTTP 404. |
| Homesick Candles | $86.11 | vendocommerce.com | jaclyn.carleton@vendocommerce.com | 301-redirects to www.onepltfrm.com whose only footer text is '© PLTFRM. 2026. All Rights Reserved' — no legal entity form, address, phone, ICP or CJK |
| admintq | $82.24 | toniiq.com | admin@toniiq.com | Site identifies itself only as 'Toniiq - Elevated Nutrients' with no legal entity, address or phone; /pages/contact-us returned HTTP 404. |
| GLUIT | $82.07 | gluit.online | egor@gluit.online | queued (crawl chunk still running) |
| jasonbaer | $81.28 | infinitecommerce.com | jason.baer@infinitecommerce.com | The domain 301-redirects to https://razor-group.com/, whose footer reads 'Razor Group © All Right Reserved' (Razor Group is the Berlin-based aggregato |
| RUGGED & DAPPER | $81.24 | ruggedanddapper.com | dv@ruggedanddapper.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site names the operating entity "RUGGED & DAPPER, LLC" — a US LLC; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check via trademark o |
| HRYCF | $80.44 | hrycftech.com | kimberly@hrycftech.com | The domain serves only a Squarespace 'Coming Soon' placeholder page — the site is parked and carries no company information of any kind. |
| LOFT + IVY | $77.37 | lifeprofitness.com | blumy@lifeprofitness.com | Both https://lifeprofitness.com and https://lifeprofitness.com/pages/contact return "HTTP 403 Forbidden" — the site blocks automated fetching. |
| Velmia | $76.70 | goyaba.co | velmia@goyaba.co | queued (crawl chunk still running) |
| Chill Pill | $74.73 | chillpillshop.com | hello@chillpillshop.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026, The Chill Pill' with US address '4522 W Village Drive #6170 Tampa, FL 33624'; no Chinese markers.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check |
| Clean Litter Club | $73.27 | cleanlitterclub.com | support@cleanlitterclub.com | Homepage shows '© Clean Litter Club 2026' and /pages/contact shows 'Clean Litter Club' with 'no formal legal entity designation found' - no address, p |
| CozyGreensJoyeza | $70.88 | goyaba.co | cozygreens@goyaba.co | queued (crawl chunk still running) |
| beblox llc | $70.52 | bebloxtoy.com | yosef@bebloxtoy.com | TLS failure on both apex and www: 'Hostname/IP does not match certificate's altnames: Host: bebloxtoy.com. is not in the cert's altnames: DNS:*.square |
| Loobanipets | $66.96 |  | loopetcontent@outlook.com | nothing; there is no domain to look at |
| Bunion Bootie | $66.76 |  | lisamrupert@gmail.com | nothing; there is no domain to look at |
| syncgo | $65.97 |  | desksware@gmail.com | nothing; there is no domain to look at |
| Ebacharach | $65.55 | lebproducts.com | eli@lebproducts.com | DNS resolution fails: "getaddrinfo ENOTFOUND lebproducts.com" — the domain does not resolve. |
| HomeSelects | $65.52 | homeselects.com | admin@homeselects.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page gives the physical address '1106 E. TURNER ROAD LODI, CA 95240' and phone '888-770-4910', with no Chinese m  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Winthorpe Conservation | $65.21 | winthorpeconservation.com | chris@winthorpeconservation.com | Copyright reads '© 2026, Winthorpe Conservation' on both the homepage and /pages/contact — no legal entity form, no address, no phone, no ICP and no C |
| Drillbrush | $64.88 | drillbrush.com | info@drillbrush.com | Terms of Service names 'Useful Products LLC' and homepage lists US phone '+1 (315) 527-1817'; no street address published, no ICP, no +86, no CJK cont |
| Dalstrong | $64.44 | dalstrong.com | lesley@dalstrong.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Dalstrong Inc.' at '171 E Liberty St, Suite 206, Toronto, ON M6K 3P6, Canada'; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re- |
| Waggle | $63.98 | mywaggle.com | kevin@mywaggle.com | Footer: "© 2025 - 2026 Waggle. All rights reserved." with US toll-free phone "855-983-5566"; no address or suffixed entity, and no ICP, +86 or CJK con |
| Pleminnky trading | $63.38 | afula-inc.com | billing@afula-inc.com | Homepage, /about and www all returned an empty document body — 'The web page content provided is empty'. No retrievable content. |
| hemme | $63.12 |  | hellohemme@gmail.com | nothing; there is no domain to look at |
| IceBeanie | $62.88 | icebeanie.com | nic@icebeanie.com | Homepage and /pages/contact show no entity, no address, no phone and no ICP — the only contact detail is the email 'support@icebeanie.com'. |
| Rollerex | $62.54 | adventureworldstore.com | info@adventureworldstore.com | Footer shows only '© 2026, AdventureWorldStore'; /pages/contact and /policies/terms-of-service both return HTTP 404. No entity, address, phone, ICP or |
| L.ī.Q. Inc. | $61.91 | liq-home.com | info@liq-home.com | Footer: "© 2026 — L.I.Q. Inc., All rights reserved" — a US-style "Inc."; homepage and /pages/contact show no address, phone, ICP or CJK content (entit |
| Lotus Linen | $61.61 | shoplotuslinen.com | hello@shoplotuslinen.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer gives "1311 E Chestnut Ave, Unit A, Santa Ana, CA 92701" with "(800) 787-8613"; no ICP, CJK, +86 or China address  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Dr Vitamin Solutions | $61.17 | formby.llc | jon@formby.llc | queued (crawl chunk still running) |
| Gripjoy Socks | $57.43 | gripjoy.com | chad@gripjoy.com | queued (crawl chunk still running) |
| The Blissful Dog Inc. | $56.81 | theblissfuldogwholesale.com | ashley@theblissfuldogwholesale.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — 301-redirects to theblissfulpets.com/pages/wholesale, which publishes "50688 235th Avenue Clearbrook, MN 56634" and "1-8  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| venturejakef | $56.00 | ventureformations.com | jake@ventureformations.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads '© 2021 Venture Formations. All Rights Reserved.' with US address '8250 Delta Cir, St. Joseph, MN 56374'; n  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| MEOLY | $55.15 | zeltmak.com | pauls@zeltmak.com | Contact page gives '90 State Street, STE 700 Office 40, Albany, NY, 12207, USA' and '845-303-5908' under 'Copyright © 2026 ZELTMAK'; no ICP, +86 or CJ |
| ASOZI | $54.57 |  | tumzon1@gmail.com | nothing; there is no domain to look at |
| kurkee | $54.39 |  | kurkeeusa@gmail.com | nothing; there is no domain to look at |
| AltroCare | $53.86 | altrocare.com | sylvie@altrocare.com | Terms of service say 'This website is operated by AltroCare' but the address and phone fields are unfilled Shopify template placeholders: '[INSERT BUS |
| OsoCozy | $52.29 | alltogetherenterprises.com | dennis@alltogetherenterprises.com | Footer shows only '© 2026, AllTogetherEnterprises.com' (no legal suffix); /pages/about-us and /policies/terms-of-service both HTTP 404. No entity, add |
| Bulldogology | $51.43 |  | bulldogology@gmail.com | nothing; there is no domain to look at |
| remiliahair | $48.47 | remiliahair.com | eliran@remiliahair.com | Homepage shows "All rights reserved Remilia 2026" and the Terms of Service give only "info@remiliahair.com"; /pages/contact-us returned HTTP 404 — no |
| mkeck | $45.69 | hamptonproducts.com | mkeck@hamptonproducts.com | queued (crawl chunk still running) |
| Baby K'tan | $45.18 | babyktan.com | michal@babyktan.com | Terms of service Section 19 names 'Baby K'tan, LLC' (opening line: 'Baby K'tan Online Store'); no ICP, no CJK, no +86, no Chinese address. Weak: no ph |
| Pup Choice | $44.81 | rkinc.net | ck@rkinc.net | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© RK Ventures Inc. All Rights Reserved." with US toll-free "(866) 229-8430"; no ICP, no +86, no CJK conten  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Thermajane | $44.67 | 1836totalcommerce.com | daniel@1836totalcommerce.com | DNS lookup failed: 'getaddrinfo ENOTFOUND 1836totalcommerce.com' — domain does not resolve. |
| Hailey Ennis | $44.43 | momofuku.com | hennis@momofuku.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer shows "©Momofuku" and the site lists its US restaurant locations including "171 1st Ave, New York 10003" and "102  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| adi120life | $43.85 | 120life.com | adi@120life.com | Footer carries only '© 2026 120/Life' with no legal entity; /pages/contact shows no entity, address or phone; no ICP, no CJK, no +86. |
| Saint Mingiano | $43.34 | saintmingiano.com | saint@saintmingiano.com | Terms of Service name the entity "Silk Road Wholesale LLC" and the footer lists "3 Germay Dr, Unit 4-4845, Wilmington, DE, 19804, United States"; note |
| fullnow | $42.21 |  | amazon.fullnow@gmail.com | nothing; there is no domain to look at |
| Thinksound | $40.98 | mytrustybrands.com | tyler@mytrustybrands.com | DNS resolution fails: "getaddrinfo ENOTFOUND mytrustybrands.com" — the domain does not resolve. |
| KLUBI | $40.26 | klubigifts.com | brad@klubigifts.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact-information page names the trader as 'Voudrais Wholesale , 2014 Goodrich Ave, a, Austin TX 78704, United States'  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| ResoseseHZH | $39.87 |  | zhoucool@outlook.com | nothing; there is no domain to look at |
| SwaddleDesigns | $38.86 | swaddledesigns.com | jeff@swaddledesigns.com | Homepage exposes no entity, address, phone, ICP or CJK; /pages/contact returned HTTP 404. Nothing to decide on. |
| Stripebird | $38.05 | stripebird.com | grant@stripebird.com | Terms of Service names only "Stripebird" ("Our store is hosted on Shopify Inc.") with support@stripebird.com; no legal entity form, address, phone, IC |
| openr | $37.39 |  | open.rumination@gmail.com | nothing; there is no domain to look at |
| OUFER | $36.18 | ouferbodyjewelry.com | nyreeyuan@ouferbodyjewelry.com | Homepage, Terms of Service and /pages/contact-us all show only the brand "OUFER BODY JEWELRY" and the line "+1(747) 239-9981" — no legal entity, no ad |
| Purplesful Snacking inc. | $35.57 |  | mavtlholdings@gmail.com | nothing; there is no domain to look at |
| kiwinurse | $34.79 |  | kiwinurseservice@gmail.com | nothing; there is no domain to look at |
| LivMatte | $34.43 | livmatte.com | support@livmatte.com | Footer shows "© 2026 LIV Matte" with "300 SE 2nd Street Suite 600Fort Lauderdale, FL 33301"; no ICP, +86 or CJK content, but no formally suffixed lega |
| RYVE | $34.24 | willtos.net | operations@willtos.net | DNS does not resolve: 'getaddrinfo ENOTFOUND willtos.net' — the domain is dead. |
| Boshel | $33.78 | boshel.com | support@boshel.com | Homepage and /pages/contact-us both show only the brand string 'BOSHEL STORE' - no legal entity, no address, no phone, no CJK content. |
| burstoralcare | $33.66 | burstoralcare.com | courtney.rconnell@burstoralcare.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Homepage: 'BURST® is a registered trademark of BURST.USA Inc.'; Terms of Service names 'BURST.USA INC. AND ITS AFFILIATE  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Carpe | $33.29 | mycarpe.com | alayna@mycarpe.com | Footer is only "© 2026 Carpe" and /pages/contact lists no entity, address or phone; no ICP, +86 or CJK content. |
| GEM | $32.93 | dailygem.com | brian@dailygem.com | Footer: '© GEM HEALTH, INC. 2023'; Terms of Service names 'Gem Health, Inc.' and references 'Venice, California'. No street address published; no ICP, |
| Organifi | $32.55 | emplicit.co | sara.cotillard@emplicit.co | queued (crawl chunk still running) |
| OREN’S BAMBOO WAREHOUSE | $32.46 |  | oren.rasowsky@gmail.com | nothing; there is no domain to look at |
| Scosche Industries | $32.18 | scosche.com | cmerritt@scosche.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Copyright line reads "©2026 Scosche Industries." with US support line "(800) 363-4490 ext.1"; no ICP, CJK, +86 or China   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Hiker Hunger Outfitters | $32.14 | hikerhunger.com | rory@hikerhunger.com | Only '© 2026, [Hiker Hunger Outfitters] [Powered by Shopify]' and phone '(406) 219-1363'; a US phone number is not proof of non-Chinese ownership, and |
| Marque | $32.01 | marquecycling.com | eric.c@marquecycling.com | Footer: "© 2026 Marque Cycling/" with US phone "714-202-7358" (Orange County, CA area code); no address or suffixed entity, and no ICP, +86 or CJK con |
| survivalgardenseeds | $31.96 | survivalgardenseeds.com | jason@survivalgardenseeds.com | Footer gives "PO Box 303, Rigby, ID 83442" (US) — a PO box only, no street address or entity form, hence weak; no ICP, CJK, +86 or China address anywh |
| Truckules | $31.50 |  | tal22314amazon@gmail.com | nothing; there is no domain to look at |
| NUTRAHARMONY | $31.20 | nutra-harmony.com | store@nutra-harmony.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Redirects to nutraharmony.com, whose Terms of Service list "37901 4TH ST N STE 300, ST PETERSBURG, FL 33702, US" and "+1  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Choice Marts | $30.88 | gikaholdings.com | karolis@gikaholdings.com | queued (crawl chunk still running) |
| Stojo Products Inc. | $30.80 | stojo.co | operations@stojo.co | DNS lookup failed for both the apex and www: "getaddrinfo ENOTFOUND stojo.co". The domain does not resolve. |
| Right 'Bove Touch | $29.89 | quadraclicks.com | hello@quadraclicks.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "QuadraClicks Gaming 8780 19th ST #152 Alta Loma, CA, 91701" with "(408) 758-8695"; no ICP, no +86, no CJK   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Kore Aviation | $28.33 | koreheadset.com | matthew@koreheadset.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads 'Copyright© 2026 KORE Headset LLC' — a US LLC, with no Chinese markers anywhere on the page (no address sho  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| CBRODERICK | $27.88 | hey-miles.com | carly@hey-miles.com | Footer reads only 'Copyright © 2026 Miles.' — no legal entity form, address, phone or ICP; /policies/contact-information repeated the same line and no |
| Wax&Wit | $27.63 |  | brian.iqnatural@gmail.com | nothing; there is no domain to look at |
| Natural Zing | $27.60 |  | naturalzinginfo@gmail.com | nothing; there is no domain to look at |
| Physician's Choice | $27.51 | physicianschoice.com | michaels@physicianschoice.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Terms of Service name the entity "JB7, LLC, d/b/a Physician's Choice" at "6990 West 38th Avenue #304 Wheat Ridge, CO 800  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| XWERKS | $27.48 | xwerks.com | mike@xwerks.com | Footer on /pages/contact reads '© 2026 XWERKS - USA' — a country label but no legal entity form, no address and no phone; no ICP or CJK content found. |
| Just Add Luv | $27.05 | justaddluv.com | contact@justaddluv.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact-information page gives 'Just Add Luv, 2415 West Stonehaven Loop, 305c, Lehi UT 84043, United States' with phone   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| BlauKe | $26.78 | jarganic.com | contact@jarganic.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — The domain 301-redirects to blauke.com, whose footer reads 'Copyright © 2026 BlauKe® all rights reserved. BlauKe® is own  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| 100% Pure New Zealand Honey | $26.68 | themanukacollective.com | jeffry.loho@themanukacollective.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2026 The Manuka Collective. All rights reserved" with New Zealand landline "+64 3 688 7150"; no ICP, CJK  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Bywabee | $26.59 | bywabee.com | bobby@bywabee.com | 301 Moved Permanently to https://bywabee.myshopify.com/ which returns HTTP 404 - store is closed/dead. |
| SipArt Mastery | $26.38 |  | sipartmastery@gmail.com | nothing; there is no domain to look at |
| Siblings | $25.36 | islandcitydigital.com | siblings@islandcitydigital.com | Connection refused: 'connect ECONNREFUSED 192.64.119.129:443' — the host resolves but refuses HTTPS connections. |
| MatchAiA | $25.07 |  | matchaia2024@gmail.com | nothing; there is no domain to look at |
| TRYNDI | $24.69 | tryndi.com | sales@tryndi.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads '© 2026 TRYNDI / Powered by 20MULTI LLC' with address '1401 Lavaca Street, Austin, TX 78701, United States'  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Birdee | $24.48 |  | solutions.amzn@gmail.com | nothing; there is no domain to look at |
| bcomstock | $24.30 |  | bcomstock45@gmail.com | nothing; there is no domain to look at |
| andrewEMJ | $24.22 | everymanjack.com | andrew@everymanjack.com | queued (crawl chunk still running) |
| SITFIT Elliptical | $23.40 | sitfitmobilitygroup.com | info@sitfitmobilitygroup.com | Both https://sitfitmobilitygroup.com and /pages/contact return no extractable text content (empty render) — nothing could be inspected. |
| AnyScope | $22.57 | varzky.com | george@varzky.com | DNS does not resolve: 'getaddrinfo ENOTFOUND varzky.com' and 'getaddrinfo ENOTFOUND www.varzky.com' — the domain is dead. |
| Chopper Mill, Inc. | $22.38 | choppermill.com | jill@choppermill.com | Footer: '© 2026 Chopper Mill, Inc. All Rights Reserved.' and Terms of Service names 'Chopper Mill, Inc.'; no address or phone published, no ICP or CJK |
| Celor | $22.05 | celor.co | support@celor.co | Only '© 2026, Célor Beauty. All rights reserved.' - a brand, not an entity; /pages/contact returned HTTP 404. No address, phone, ICP or CJK content. |
| PolyTeak | $21.78 | redoakcreations.com | johnm@redoakcreations.com | Site serves only a 404 error page credited "Site powered by Weebly. Managed by Bluehost" — no live content. |
| Hail M Cocktails | $21.77 | hailmcocktails.com | mary@hailmcocktails.com | queued (crawl chunk still running) |
| Pet Wellness Direct | $21.71 | marstrandemail.com | petwellnessdirect-affiliates@marstrandemail.com | Redirects (301) to marstrand.agency, whose footer reads "2026 Marstrand Agency. All Rights Reserved." with US phone "805-500-7575"; no address or suff |
| oilbanker | $20.72 |  | oilbanker@gmail.com | nothing; there is no domain to look at |
| Yuca | $20.46 | yuca.co | keith@yuca.co | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site states 'Yuca LTD, a registered company in the United Kingdom' at 'First Floor, Telecom House, 125-135 Preston Road,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| T is for Tame | $20.21 | tisfortame.com | info@tisfortame.com | Copyright reads '© 2026, T is for Tame' — a bare brand name with no legal entity form, no address and no phone on either the homepage or /pages/contac |
| Lumē Deodorant, LLC | $19.89 | lumedeodorant.com | corbin.jensen@lumedeodorant.com | Homepage returned navigation/header markup only with no footer, and /pages/contact-us returned "404 Not found / Lume Deodorant" — no entity, address, |
| Vital Purple | $19.77 |  | naturalzinginfo@gmail.com | nothing; there is no domain to look at |
| elizabethmott | $19.63 | elizabethmott.com | kmontania@elizabethmott.com | queued (crawl chunk still running) |
| tea facto | $19.62 | maisonovo.com | support@maisonovo.com | Footer is only "© 2026 - MaisoNovo" and /pages/contact returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |
| D'Artisan Shoppe | $19.13 | xtra.co.nz | sophis@xtra.co.nz | Server refuses HTTPS connections on both apex and www: 'connect ECONNREFUSED 202.27.184.102:443' — nothing is served. |
| Goode Health | $19.02 | goodehealth.com | mike@goodehealth.com | queued (crawl chunk still running) |
| Henry Schein | $18.60 |  | matchaia2024@gmail.com | nothing; there is no domain to look at |
| Back Bay Audio | $18.23 | benderbrands.co | jeremy@benderbrands.co | Apex refused connection ('connect ECONNREFUSED 162.255.119.89:443'); www loaded but homepage and /about carry only 'info@benderbrands.co' — no entity, |
| Joyful Moose | $17.85 | joyfulmoose.com | julie@joyfulmoose.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Contact-information page names 'Caribou Creek Cases LLC DBA Joyful Moose' at '653 Oxford Rd, Bonners Ferry ID 83805, Uni  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| Clyrio | $17.80 | clyrio.com | amazon@clyrio.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026 Clyrio LLC. All rights reserved.' with address '5400 S Lakeshore Dr Ste 201 Tempe, AZ 85283'; no Chinese  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| kevinleeme | $17.58 | immieats.com | klee@immieats.com | Footer reads only '2026 immi. All rights reserved.' — no legal entity form, address, phone or ICP; /policies/contact-information returned HTTP 404. |
| IGANCE | $16.94 | goyaba.co | igan@goyaba.co | queued (crawl chunk still running) |
| burakbilisik | $16.60 |  | burakbilisik@gmail.com | nothing; there is no domain to look at |
| The Bean Coffee Company | $16.10 | thebeancoffeecompany.com | craig@thebeancoffeecompany.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page gives "1407 S.Coast Highway, Oceanside, CA 92054" with "(800) 683-7967"; no ICP, CJK, +86 or China address.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Flipper Aquarium Products | $15.85 | flippercleaner.com | brian@flippercleaner.com | queued (crawl chunk still running) |
| RazorGroup | $15.74 | razor-group.com | john.durkin@razor-group.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Imprint page names "Razor HQ GmbH & Co. KG" and "Razor HQ Management GmbH" at "c/o Razor Group GmbH, Ritterstraße 16-18,  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| OLIVIAUMMA | $15.64 | purplepeppercommerce.com | accounts@purplepeppercommerce.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "©2025 Purple Pepper Commerce LLC. All rights reserved." — a US LLC; no ICP, no +86, no CJK content.  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re-check  |
| Melinda's Hot Sauce | $14.79 | stayhungrydigital.com | jared@stayhungrydigital.com | Site names "Stay Hungry Digital" with geographic US phone "781.844.7976" (Massachusetts area code); no address or legal entity form given, but no ICP, |
| NATIVEPET24 | $14.63 | thenativepet.com | kcampbell@thenativepet.com | 301-redirects to nativepet.com, which shows only "© 2026 Native Pet"; /pages/contact redirects off-site to a Gorgias help centre. No entity form, addr |
| Mav Beauty Brands | $14.49 | mavbeautybrands.com | girish.giovanni@mavbeautybrands.com | TLS handshake fails: "unable to verify the first certificate" — no page content could be retrieved. |
| Dolce Flav | $14.27 | dolceflav.com | levi@dolceflav.com | Terms of Service names 'DOLCE FOGLIA FLAVORS' and homepage lists US phone '+1 (213) 575-9444'; no street address published, no ICP, no +86, no CJK con |
| Highland | $14.11 | highland.style | boone@highland.style | Page states 'We are based in Boulder, Colorado!' alongside 'Copyright © 2026 Highland', with no Chinese markers; but no legal entity form or street ad |
| Mobi Lock | $13.63 | locksourcing.com | tanguy@locksourcing.com | https://locksourcing.com issues a "301 Moved Permanently" to the QR-shortener "https://qr1.be/LIZM", which serves only the bare text "LIZM" — the doma |
| MatchaDNA | $13.45 | goyaba.co | matchadna@goyaba.co | queued (crawl chunk still running) |
| Toysmith | $13.38 | toysmith.com | agoldberg@toysmith.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer states '© 2026 Toysmith' with address '541 West Valley Hwy S Pacific, WA 98047 USA' and phone '800-356-0474'; no   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Houswise | $13.00 | houswise.com | tom@houswise.com | Homepage and /pages/contact show no entity, no address, no phone and no ICP — only 'Our support hours: Monday - Friday 9:00 AM - 5:00 PM EST'. |
| The Parker-Lambert Agency | $12.53 | parker-lambert.com | dylan.rhodes@parker-lambert.com | Footer says only "Parker-Lambert is an ecommerce, branding, and creative services agency" and /contact returned HTTP 404; no entity suffix, address, p |
| Lovebug Probiotics | $12.44 | lovebugprobiotics.com | ashley@lovebugprobiotics.com | Redirects (301) to lovebug.com, which lists "115 East 34th Street, Suite 1506 New York, NY 10156"; no ICP, +86 or CJK content, but no formally named l |
| Pirate Wizards | $12.31 |  | jamesrbake@gmail.com | nothing; there is no domain to look at |
| ExcelMark | $12.27 | schwaab.com | rbuchanan@schwaab.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "Schwaab, Inc" (US corporate form) with US toll-free "800.935.9877"; no ICP, no CJK, no +86, no China addre  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| adminTPC | $11.92 | talkingpointcards.com | admin@talkingpointcards.com | Homepage shows no entity, address, phone, ICP or CJK (English-only store with FR/DE/ES product variants); /pages/contact returned HTTP 404. |
| Spot Detergent | $11.87 | tru-nutbutter.com | reid@tru-nutbutter.com | Copyright reads '© 2026, The Tru-Nut Company.' but the contact page carries unedited Shopify placeholder data — '12345 North Main Street, New York, NY |
| Novel Brands | $11.35 | novelbrands.com | ava@novelbrands.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© Novel Brands - 2026 All rights reserved" with the address "Fairfield, NJ 07004 - U.S.A"; no ICP, no +86,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| ericmendes | $11.25 | laundryturtle.com | eric@laundryturtle.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer names "Laundry Turtle - 1348671 B.C. LTD." at "1055 W Georgia St. Suite 2400 Vancouver, BC V6E 3P3" — a British C  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Cosmic Freeze | $11.09 |  | dianamazer@gmail.com | nothing; there is no domain to look at |
| BathBlocks | $9.86 | just-think-toys.com | doug@just-think-toys.com | Footer reads only 'Copyright © 2026 Just Think Toys' — no legal entity form, address, phone or ICP; /policies/contact-information returned HTTP 404. |
| RainbowShow | $9.75 |  | heguyun@outlook.com | nothing; there is no domain to look at |
| Pals Socks | $9.34 | palssocks.com | erin@palssocks.com | Apex domain returned an empty response body and the www host failed DNS: "getaddrinfo ENOTFOUND www.palssocks.com". |
| Brick House | $9.27 |  | jonathan.bricker@icloud.com | nothing; there is no domain to look at |
| mconley | $8.82 | raakachocolate.com | max@raakachocolate.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Footer reads "copyright 2024 Raaka chocolate ltd. All rights reserved" with the factory address "58 Seabring St Brooklyn  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| Goli Nutrition | $8.76 | goli.com | anthony@goli.com | queued (crawl chunk still running) |
| Yobee Care | $8.60 | yobeecare.com | support@yobeecare.com | Footer reads '© 2026 Yobee Care, Inc / All Rights Reserved' and the page states 'Yobee® is a registered trademark of Yobee Care Inc.' (owned, not lice |
| SuperNaturalGoods | $8.55 | nexxuscap.com | sngops@nexxuscap.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2023 Nexxus Capital. All rights reserved." with "800 Druid Rd. E Clearwater, FL 33756" and "(727) 953-34  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Menfirst | $8.52 | menfirstusa.com | bea@menfirstusa.com | Redirects (301) to menfirst.com: footer "© 2026, Menfirst" and contact page phone "1-904-900-8730" (Jacksonville, FL area code); no address or suffixe |
| Kind Lips | $8.43 | kindlips.com | josh@kindlips.com | Footer reads only '© 2026 Kind Lips' — no legal entity form, address, phone or ICP; /policies/contact-information returned HTTP 404. |
| sisterlymarket | $8.39 |  | sisterlymarket@gmail.com | nothing; there is no domain to look at |
| Arterra Pet Science | $8.07 | arterrapet.com | amazon@arterrapet.com | Footer '© 2026 Arterra Pet, All Rights Reserved'; terms of service name 'Arterra Pet Sciences' but the address is the unfilled Shopify template placeh |
| Numeira Dead Sea | $7.97 | numeira.com | z.adwan@numeira.com | 301-redirects to global.numeira.com, which shows only "Numeira Global" with no legal suffix, address, or phone; language selector offers EN/AR/DE/JA — |
| Vitavelle Cosmetics | $7.80 | unitedbrands-group.com | info@unitedbrands-group.com | Both https://unitedbrands-group.com and https://www.unitedbrands-group.com fail TLS: 'Host: unitedbrands-group.com. is not in the cert's altnames: DNS |
| Brilliant Beauty | $7.72 | e-comapparel.com | esutton@e-comapparel.com | queued (crawl chunk still running) |
| ieró Beauty™ | $7.56 | ierobeauty.com | alepiashko@ierobeauty.com | Footer reads only '© 2026, ieró Beauty All rights Reserved.' — no legal entity form, address, phone or ICP anywhere on the page. |
| Puppy Pouch | $7.44 | freedomhill-llc.com | dave@freedomhill-llc.com | queued (crawl chunk still running) |
| Sandunes | $7.18 |  | sanduneshome@gmail.com | nothing; there is no domain to look at |
| FordeBaker | $7.00 | fordebaker.com | laurent@fordebaker.com | queued (crawl chunk still running) |
| nechemya | $6.98 | jmcbinc.com | joel@jmcbinc.com | DNS resolution fails: 'getaddrinfo ENOTFOUND jmcbinc.com' — the domain does not resolve. |
| Glow by hormone university | $6.72 | hormoneuniversity.com | hello@hormoneuniversity.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site states 'Hormone Wellness Group LLC, which is an affiliate of Glow Botanica Inc.' at '5830 E Second Street, Ste. 700  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Vivid Scribbles | $6.72 | vividscribbles.com | contact@vividscribbles.com | Copyright reads '© 2026 Vivid Scribbles' with no legal entity form, address or phone; /pages/contact returned HTTP 404 and no CJK content was present. |
| vinsguir | $6.60 |  | vinsguir.pickleball@gmail.com | nothing; there is no domain to look at |
| umamibento | $6.49 |  | umami.bentos@gmail.com | nothing; there is no domain to look at |
| Keith | $6.30 | newenglandstories.us | contact@newenglandstories.us | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2026, New England Stories" with the address "305 Constitution Drive, Taunton Massachusetts 02780, United  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Kronox | $6.00 | cheetahmotorsport.com | julian@cheetahmotorsport.com | 301 redirects to https://kronoxpowersports.com/ whose footer shows only 'KRONOX Powersports' - no legal entity, no address, no phone, no CJK content. |
| Kibou Bag | $5.88 | kiboubag.com | nell@kiboubag.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads '© Kibou 2026' with the physical address '200 16th Street Brooklyn, NY 11215' — a real US street address wi  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| MEEMA | $5.37 | luum.co | a@luum.co | Footer is only "© 2026 luum.co / Powered by Shopify" and the contact page describes "Luum" as "an Amazon launch agency" with no entity, address or pho |
| Timeline | $5.25 | timeline.com | mjaneiro@timeline.com | Copyright line reads '© 2026' with no company name attached; only a US support number '+1-888-631-3359' is shown, and /pages/contact returned HTTP 404 |
| Foldies | $5.04 | thinkcartology.com | taylor@thinkcartology.com | Homepage carries only "© 2026 Cartology. All rights reserved."; /policies/terms-of-service serves a 404 page (Lovable-built site). No address, phone, |
| jdhaley00 | $4.91 |  | phdesign.llc@gmail.com | nothing; there is no domain to look at |
| Osaber | $4.32 | venturesunbounded.com | omar@venturesunbounded.com | Server refuses connections: 'connect ECONNREFUSED 162.255.119.37:443' on the apex and 'Socket is closed' on www — nothing is served on HTTPS. |
| LOOKNOOK | $4.31 | mepurelab.com | lliu@mepurelab.com | Footer is only "© 2026, MepureLab Powered by Shopify" and the Terms of Service names no legal entity, address or phone (only "sales@mepurelab.com"); n |
| TTolbi | $3.98 |  | contact.ttolbi@gmail.com | nothing; there is no domain to look at |
| Oleksii | $3.97 |  | mymailflorida01@gmail.com | nothing; there is no domain to look at |
| leolandau | $3.84 |  | leolandau@gmail.com | nothing; there is no domain to look at |
| Bubble Sponge | $3.72 | bubblesponge.com | info@bubblesponge.com | Footer shows only 'All rights reserved by bubblesponge.com'; /pages/contact-us returned HTTP 404. No entity, address, phone or CJK content. |
| alexdittrich | $3.60 | brightventuresco.com | alex@brightventuresco.com | TLS handshake fails on both apex and www: 'certificate has expired' - site cannot be fetched. |
| Teracube | $3.60 | myteracube.com | sharad@myteracube.com | Footer is only "© 2024 Teracube" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |
| Aromafume | $3.35 | aromatan.com | taha@aromatan.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site names three entities with matching addresses — 'Aromatan Brands Private Limited' (Lower Parel, Mumbai, India), 'Aro  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Ecomcy | $3.27 | ecomcy.co.uk | juan@ecomcy.co.uk | queued (crawl chunk still running) |
| Matjaz | $3.25 |  | matjaz.valencic@yahoo.com | nothing; there is no domain to look at |
| Aiming Fluid Golf | $3.21 |  | aimingfluidgolf@gmail.com | nothing; there is no domain to look at |
| TokyoRush | $3.08 | qintama.com | sales@qintama.com | DNS resolution failed: "getaddrinfo ENOTFOUND qintama.com" — domain does not resolve. |
| Ouch Baby | $3.00 |  | princenasario@gmail.com | nothing; there is no domain to look at |
| VZJZHAN | $2.86 |  | chaolin405@gmail.com | nothing; there is no domain to look at |
| Alodia | $2.72 | alodiahaircare.com | isfahan@alodiahaircare.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of service name 'Alodia Healthy Hair LLC' at 'PO Box 1500, Bowie, Maryland 20717, United States'; no ICP, no CJK,   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Bonded By Stories | $2.70 |  | brightbridgeventures@gmail.com | nothing; there is no domain to look at |
| Aum Active | $2.60 | hooraycommerce.com | marketing@hooraycommerce.com | MY EARLIER WEBSITE CRAWL said CHINA (weak) — The site ships a full Simplified-Chinese localisation — nav items '中文', '服务', '案例分析', '关于我们', '时间轴', '联系我们' — and its ca |
| tukaho | $2.55 | tukaho.com | support@tukaho.com | Copyright reads '© 2026. All rights reserved.' with no entity name attached; /pages/contact shows no company name, address or phone, and no CJK conten |
| Goat Soap | $2.52 | machetesystems.com.au | tim@machetesystems.com.au | MY EARLIER WEBSITE CRAWL said NOT_CHINA (definitive) — Footer names "Machete Systems Pty Ltd, A Smollan Company" at "150 Albert Rd, South Melbourne VIC 3205" with phone "+61 1  *** BUT A US LLC IN A FOOTER PROVES NOTHING |
| SMOLBOL | $2.46 | mismifoods.com | felipe@mismifoods.com | Fetch blocked before any content was returned: "Unable to verify if domain mismifoods.com is safe to fetch." |
| BnD US | $2.10 |  | bnd.us.official@gmail.com | nothing; there is no domain to look at |
| Nuanced Media | $2.10 | nuancedmedia.com | ryanflannagan@nuancedmedia.com | Homepage footer shows only "© 2026 Nuanced Media. All rights reserved." and the /contact page carries no entity suffix, address, or phone; no Chinese |
| Gemonklee | $2.01 |  | gemonklee@outlook.com | nothing; there is no domain to look at |
| itservicesVremi | $1.93 | mohawkgp.com | it-services+vremi@mohawkgp.com | Apex fails TLS — "Host: mohawkgp.com. is not in the cert's altnames: DNS:*.azurewebsites.net" — and www does not resolve ("getaddrinfo ENOTFOUND www.m |
| Matrescence | $1.86 | matrescenceskin.com | raquel@matrescenceskin.com | Footer is only "© 2026 - Matrescence" and /pages/contact lists no entity, address or phone; no ICP, +86 or CJK content. |
| Milspin | $1.83 | milspin.com | dpeters@milspin.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: "© 2026 MILSPIN, All rights reserved." with US address "30 Diana Ct, Cheshire, CT 06410" and phone "+16146648151  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| barebotanicsteam | $1.60 | barebotanics.co | team@barebotanics.co | Footer '© 2026, Bare Botanics Skincare'; terms of service say 'This website is operated by Bare Botanics Skincare' and give only 'hello@barebotanics.c |
| MyMed | $1.60 |  | toolssubscription@gmail.com | nothing; there is no domain to look at |
| mondaymoose | $1.52 | mondaymoose.com | dani@mondaymoose.com | Footer is only "© 2026, Monday Moose" and /pages/contact returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content. |
| ELEMITO | $1.50 |  | elemito.llc@gmail.com | nothing; there is no domain to look at |
| Elevate Pet Provisions | $1.50 | ynhco.com | ethan@ynhco.com | Two fetches (https://ynhco.com and https://ynhco.com/pages/about-us) both returned an empty response body — the site serves no readable content to fet |
| PureHimalayanShilajit | $1.50 | nexxuscap.com | phsops@nexxuscap.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2023 Nexxus Capital. All rights reserved." with "800 Druid Rd. E Clearwater, FL 33756" and "(727) 953-34  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Settini | $1.44 | settini.com | marketing@settini.com | Terms of Service names only "Settini" with SMS line "+18886085301" (non-geographic US toll-free) and contact@settini.com; no legal entity form, no add |
| Supplements Studio | $1.38 |  | mvstudioproducts@gmail.com | nothing; there is no domain to look at |
| Swigzy | $1.35 | swigzy.com | info@swigzy.com | Terms of Service names only "swigzy" with info@swigzy.com; no legal entity form, address, phone, ICP or CJK. |
| GYMGUM | $1.09 |  | gymgumllc@gmail.com | nothing; there is no domain to look at |
| Signs That Pop | $0.96 |  | derron99@gmail.com | nothing; there is no domain to look at |
| Darlington Snacks | $0.90 | darlingtonsnacks.com | jfeasel@darlingtonsnacks.com | Both apex and www returned 'HTTP 403 Forbidden' - site blocks fetching. |
| yaqubnmc1 | $0.72 | themedicaptain.com | yaqub@themedicaptain.com | Terms of Service still carries unfilled Shopify template placeholders "[INSERT BUSINESS ADDRESS]" and "[INSERT BUSINESS PHONE NUMBER]"; only contact i |
| Argosy QR | $0.60 | argosyqr.com | kevin@argosyqr.com | Homepage names 'Argosy QR' with no legal suffix; /pages/contact gives only 'hello@argosyqr.com'; /policies/terms-of-service is HTTP 404. No entity, ad |
| DecorChiq | $0.60 | baard.se | maria@baard.se | Both https://baard.se and https://www.baard.se returned an empty document — no footer, no copyright, no page body. Nothing retrievable. |
| bioworld | $0.50 | bioworldmerch.com | joem@bioworldmerch.com | Homepage footer carries no entity, address or phone; /pages/contact-us and /pages/contact both HTTP 404. No ICP, no CJK, no +86. |
| Dragon Grips and Bright Knight Decals | $0.45 | dragonlairdesigns.com | joel@dragonlairdesigns.com | Footer shows only 'Dragon Lair Designs © 2023'; /policies/terms-of-service returned HTTP 404. No legal entity, address, phone, ICP or CJK content. |
| Levonascent | $0.35 | bmitraders.com | jonathan@bmitraders.com | Both https://bmitraders.com and https://bmitraders.com/pages/contact returned 'HTTP 500 Internal Server Error' - site does not serve content. |
| Kavguine | $0.30 |  | neophonic.low@gmail.com | nothing; there is no domain to look at |
| Aromaque |  | thetotalintegrity.com | liam@thetotalintegrity.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer gives "Total integrity LLC, 1808 Coyote Dr, Ste 103, Chester, VA 23836" with "804-245-3264"; no ICP, CJK, +86 or   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Bean Products |  | beanproducts.com | chuck@beanproducts.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: '© 2026 Bean Products' with '1500 S Western Ave #4BN, Chicago, IL 60608' and '(312) 666-3600'; no ICP, no CJK, n  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| BodyRestoreAdmin |  | liquidbrands.co | erick@liquidbrands.co | Footer shows "© 2026, Liquidbrands.co" and address "1910 Thomes Ave., Cheyenne, WY 82001-3527"; no ICP/+86/CJK found, but no named legal entity either |
| Brain Freeeze™ |  |  | nalconfectionary@gmail.com | nothing; there is no domain to look at |
| bryancano |  | trueclassic.com | bryan.cano@trueclassic.com | Redirects to www.trueclassictees.com whose footer reads '© True Classic Tees LLC. All Rights Reserved 2026' — an explicit US LLC, though no address is |
| Cattasaurus LLC |  |  | taitda.amazon2023@gmail.com | nothing; there is no domain to look at |
| Choq LLC |  | socialinfluence.com | rbiton@socialinfluence.com | Homepage shows no entity, ICP, phone, address or CJK; /about returned HTTP 404. Nothing to decide on. |
| Cloud Scape Linen |  | cloudscapelinen.com | alfred@cloudscapelinen.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer: 'Cloud Scape Linen LLC' with locations 'Coimbatore, India / Delaware, USA / Dubai, UAE' and phone '+1 6462826638  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Cooler Kitchen |  | coolerkitchen.com | brandon@coolerkitchen.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service lists 'Cooler Kitchen' at '18 Fox Run Drive East Hanover New Jersey US 07936'; no ICP, no +86, no CJK c  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| dashofvigor |  |  | mariela.b.dimitrova@gmail.com | nothing; there is no domain to look at |
| DEFINED |  |  | lightitupgroup@outlook.com | nothing; there is no domain to look at |
| DoSensePro |  |  | dosensepro@gmail.com | nothing; there is no domain to look at |
| Drink Harlo |  | drinkharlo.com | st@drinkharlo.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Terms of Service names 'Drink Harlo LLC' at '5940 S Rainbow Blvd, 400-38077, Las Vegas, NV 89118' with US phone '702-919  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| DSLquality |  | dslquality.com | sammy@dslquality.com | Serves a bare Apache default directory listing (only a 'cgi-bin/' folder entry) - no website content is deployed. |
| ECOlunchbox |  | ecolunchboxes.com | sales@ecolunchboxes.com | queued (crawl chunk still running) |
| Elm Dirt |  | elmdirt.com | matt@elmdirt.com | queued (crawl chunk still running) |
| ePlaybooks.com |  | eplaybooks.com | shawn@eplaybooks.com | queued (crawl chunk still running) |
| faithlee |  | naenka.com | faith@naenka.com | Homepage brands itself "Nank(Naenka)" with no entity; the Terms of Service names no company, no address and no phone (only "service@naenka.com") and s |
| FreshKnight |  | nexxuscap.com | freshknight@nexxuscap.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "© 2023 Nexxus Capital. All rights reserved." with "800 Druid Rd. E Clearwater, FL 33756" and "(727) 953-34  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| From Great Origins (FGO) |  | wmplp.com | mackenziek@wmplp.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site identifies 'WM Partners, LP' at '21500 Biscayne Blvd., Suite 600, Aventura, FL 33180, United States' with 'T: 754-2  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Gorillaz LLC (IBOANN) |  | accelclub.pro | iliya.shkuruk@accelclub.pro | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — '301 Moved Permanently' to https://www.accelclub.com/, whose footer reads 'Copyright © 2022 Accel Club. All rights reser  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Haomuren |  |  | zhouzhoujingdz@outlook.com | nothing; there is no domain to look at |
| Hofseth BioCare |  | hofsethbiocare.com | wurb@hofsethbiocare.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads 'Copyright 2025 Hofseth BioCare ASA' — 'ASA' is the Norwegian public limited company form, and the site car  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Husband Pillow, Wife Pillow and More |  |  | au.1hitnotion@gmail.com | nothing; there is no domain to look at |
| Impsiring |  | imspiring.com | info@imspiring.com | Footer reads only 'Copyright © 2026 imspiring.com - All Rights Reserved.' — no entity, address, phone or ICP; /contact returned HTTP 404. |
| itServicesPPD |  | mohawkgp.com | it-services+ppdus@mohawkgp.com | Apex fails TLS — "Host: mohawkgp.com. is not in the cert's altnames: DNS:*.azurewebsites.net" — and www does not resolve ("getaddrinfo ENOTFOUND www.m |
| itservicesPTC |  | mohawkgp.com | it-services+ptc@mohawkgp.com | Apex fails TLS — "Host: mohawkgp.com. is not in the cert's altnames: DNS:*.azurewebsites.net" — and www does not resolve ("getaddrinfo ENOTFOUND www.m |
| La Republica |  | larepublicasuperfoods.com | amazon@larepublicasuperfoods.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Site gives 'La Republica Superfoods, Unit 355, Verdugo City, CA 91046' with phone '(818) 305-5360' — a US address with n  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Life4Legs |  |  | life4legs@gmail.com | nothing; there is no domain to look at |
| Lincove |  | lincove.com | zeke@lincove.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer states "American Bedding Inc. 128 S Robinson Ave. Unit 5 Newburgh NY, 12550" with phone "+1 800-991-7988"; no ICP  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| LitONES |  |  | litones001@gmail.com | nothing; there is no domain to look at |
| LongLifeNutri |  | longlifenutri.com | wayward@longlifenutri.com | Footer is only "Copyright © 2026, LongLifeNutri" and /pages/contact-us returns HTTP 404; no entity, address, phone, ICP, +86 or CJK content found. |
| Lucky Iron Life |  | luckyironfish.com | shraddha@luckyironfish.com | Redirects (301) to luckyironlife.com whose footer reads only "© Lucky Iron Life. All rights reserved." — no entity, address, phone, ICP, +86 or CJK co |
| Lure Essentials |  | lureessentials.com | info@lureessentials.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Page states "Lure Enterprises LLC, dba Lure Essentials" with US phone "707-728-5873" (California area code); no ICP, +86  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Medify Air LLC |  |  | medifyair@gmail.com | nothing; there is no domain to look at |
| Mentor |  |  | solvingalpha.marketing@gmail.com | nothing; there is no domain to look at |
| mrlinden |  | sunblocks.com | mike@sunblocks.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "Copyright 2023 / Carefree Skincare Ventures, LLC" at "4441-106 Six Forks Road, Suite 226 / Raleigh, NC / 2  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| NaturaleBio |  | goyaba.co | naturalebio@goyaba.co | queued (crawl chunk still running) |
| Nguyen Coffee Supply |  | nguyencoffeesupply.com | growth@nguyencoffeesupply.com | Homepage rendered only the headline "Nguyen Coffee Supply – America's First Specialty Vietnamese Coffee" with no footer/legal block, and /pages/contac |
| Noveha |  | tagcrow.com | yeshaya@tagcrow.com | TLS handshake fails on both tagcrow.com and www.tagcrow.com: "certificate has expired". Site cannot be fetched. |
| ONC NATURALCOLORS |  | oncorganic.com | ekaya@oncorganic.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer reads "Copyright © 2026 oncorganic.com. / ONC artofcolor and ONC NaturalColors" with US and UK addresses "2200 Co  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Powerfit |  |  | theglobaldrgroup@gmail.com | nothing; there is no domain to look at |
| pyle |  | pyleusa.com | jonathanb@pyleusa.com | Footer reads "© 2026, Pyle USA. All Rights Reserved" with the Brooklyn-area line "1.718.535.1800"; no street address or entity suffix shown, but no IC |
| ranwin |  |  | winran1@outlook.com | nothing; there is no domain to look at |
| Seller Presto |  | sellerpresto.com | graeme@sellerpresto.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Footer gives "Boho Five Bridge Street East Middlesbrough England TS2 1NY" with UK landline "Tel: 01642 054694"; no ICP,   *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| Stream2Sea |  | stream2sea.com | ezzy@stream2sea.com | MY EARLIER WEBSITE CRAWL said NOT_CHINA (strong) — Contact page gives "Stream2Sea, 2498 Commerce Court, Bowling Green, FL 33873" with "1-866-960-9513 (Toll-Free)"; no ICP,  *** BUT A US LLC IN A FOOTER PROVES NOTHING. Re |
| TANGRAM |  | tangram.kr | help@tangram.kr | TLS handshake fails on both tangram.kr and www.tangram.kr: "certificate has expired". Site cannot be fetched. |
| TETON ELECTRONICS |  | tetonelectronics.com | fayazul.hasan@tetonelectronics.com | Footer reads "Copyright ©2026 Teton. All Rights Reserved." with "2855 Kifer Road Suite 201, Santa Clara, CA 95051 United States" and "+1 (669) 269-234 |
| Tilstar| Zonguru |  | tilstar.com | jon.haley@tilstar.com | Footer shows only '© 2026 TilStar' with no legal entity form, no address, no phone, and no Chinese markers; /pages/contact failed with a TLS error. |
| Titanz2018 |  | redstartec.com | support@redstartec.com | Homepage shows "© Red Star Tec 2016-2024" and the Terms of Service refer to "RedStarTecs" with no legal suffix, address, or phone; /pages/contact-us r |
| Toddlekind |  |  | toddlekind47@gmail.com | nothing; there is no domain to look at |
| Trukid |  | heyoakwell.com | marketing@heyoakwell.com | HTTP 301 Moved Permanently to https://oakwellvc.com/, which itself fails DNS resolution (getaddrinfo ENOTFOUND oakwellvc.com) — the domain redirects t |
| Truly Free |  | trulyfreehome.com | marketing@trulyfreehome.com | Homepage footer was truncated before any entity/address/phone was reachable and /pages/contact returned HTTP 404 — no entity, ICP, phone, address or C |
| vendoaffiliate |  | vendocommerce.com | jaclyn.carleton@vendocommerce.com | 301-redirects to www.onepltfrm.com whose only footer text is '© PLTFRM. 2026. All Rights Reserved' — no legal entity form, address, phone, ICP or CJK |
| V-Pen |  | groupvertical.com | ryan@groupvertical.com | queued (crawl chunk still running) |
| WildFoodsTeam |  | noblebrands.co | team@noblebrands.co | DNS resolution failed: "getaddrinfo ENOTFOUND noblebrands.co" — domain does not resolve. |
| Wise Elk |  |  | kostya.rolin@gmail.com | nothing; there is no domain to look at |
| Yefet Brands |  | mytrustybrands.com | tyler@mytrustybrands.com | DNS resolution fails: "getaddrinfo ENOTFOUND mytrustybrands.com" — the domain does not resolve. |
| Zing Sauce |  |  | thezingsauce@gmail.com | nothing; there is no domain to look at |
| BeepWell | $-2.04 | technisia.com | usama.ali@technisia.com | Connection refused on both technisia.com and www.technisia.com: "connect ECONNREFUSED 168.119.12.80:443". Site cannot be fetched. |


## B. `unknown`, not currently billing

| Brand | Domain | Email | Research note |
| --- | --- | --- | --- |
| Acquco | acqu.co | john.berggren@acqu.co | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| Amazing Freedom Brands | petratools.com | mili@petratools.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| eBrands Global Oy | ebrands.com | finance@ebrands.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| Migrastil | migrastil.com | scott@migrastil.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| Shameless Snacks | ejam.com | ss@ejam.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| Tractive | tractive.com | alex.deleon@tractive.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| Tweexy | tubshroom.com | yaqub@tubshroom.com | website not reachable / no domain — go straight to Amazon seller page + USPTO |
| VitaUp | vitaup.org | support@vitaup.org | website not reachable / no domain — go straight to Amazon seller page + USPTO |


## C. Already resolved (reference — seller check would only confirm)

| Brand | Verdict | Billing | Collected |
| --- | --- | --- | --- |
| Baker's Secret | china | yes | $808.52 |
| Bakscape | china | yes |  |
| Benassie | china | yes | $133.87 |
| Braddell Optics | china | yes | $357.95 |
| Chivalz | china | yes | $1,335.29 |
| CONQUECO | china | yes | $77.28 |
| Culvani | china | yes | $73.08 |
| Everblog | china | yes | $30.00 |
| Eviqo | china | yes | $35.56 |
| Fitouch | china | yes | $15.50 |
| Foonbe | china | yes | $2.86 |
| FUNSPREAD | china | yes | $16.24 |
| HONG KONG HONGYI ECONOMIC & TRADING CORPORATION LIMITED | china | yes | $3,135.92 |
| Ltinist | china | yes | $27.10 |
| Maxracy | china | yes | $0.97 |
| MOUNTRAX | china | yes | $486.44 |
| QOKNUL | china | yes |  |
| Serravine | china | yes | $6.60 |
| StarVal | china | yes | $6.30 |
| vynrik | china | yes | $3.75 |
| 5 Stars United LLC | not_china | yes | $3,296.13 |
| AC Global Distribution | not_china | yes | $3,899.28 |
| Ahimsa Kids, Inc. | not_china | yes | $2,042.55 |
| AMZAdvisers | not_china | yes | $876.81 |
| AmziProven | not_china | yes | $2,166.68 |
| Artistro | not_china | yes | $4,275.64 |
| ASTRALSHIP | not_china | yes | $1,446.23 |
| AtlantisNutrition | not_china | yes | $342.42 |
| Back Bay | not_china | yes | $1,779.71 |
| BACtrack | not_china | yes | $847.93 |
| Balm of Gilead | Functional Skin Care & Pure Essential Oils | not_china | yes | $1,345.27 |
| Basepaws | not_china | yes | $2,051.38 |
| Beauty by Earth | not_china | yes | $576.01 |
| Better Boat, Hippie Crafter & Silly Feet | not_china | yes | $3,644.69 |
| BioTrust Nutrition LLC | not_china | yes | $515.39 |
| Birdrock Home | not_china | yes | $1,586.33 |
| Blue Ocean Brands | not_china | yes | $1,536.77 |
| BohdanMMC | not_china | yes | $491.74 |
| Boundless EC US LLC | not_china | yes | $9,433.38 |
| BRMUD | not_china | yes | $3,506.31 |
| Bunmo | not_china | yes | $4,321.10 |
| chateauhomecollection | not_china | yes | $5,413.90 |
| Chew and Heal | not_china | yes | $2,950.05 |
| CocoaVia | not_china | yes | $2,415.81 |
| Daresay | not_china | yes | $516.35 |
| Doctors Choice | not_china | yes | $2,137.62 |
| Dood Woof | not_china | yes | $1,329.79 |
| Dr. Frederick's Original | not_china | yes | $2,852.88 |
| Dr. Matthew | not_china | yes | $1,166.68 |
| Durelife nutrition | not_china | yes | $1,996.95 |
| Dyce Games | not_china | yes | $465.03 |
| Earth's Daughter | not_china | yes | $351.59 |
| Emplicit | not_china | yes | $5,108.69 |
| EraOrganics | not_china | yes | $2,026.10 |
| Etta Vita | not_china | yes | $3,749.59 |
| EU Natural LLC | not_china | yes | $3,554.60 |
| Eva Naturals | not_china | yes | $859.00 |
| FrontRowGroup | not_china | yes | $3,134.67 |
| Gaines Family Farmstead | not_china | yes | $547.79 |
| GEMELLE | not_china | yes | $619.77 |
| Gifts for Readers and Writers | not_china | yes | $567.66 |
| Global Healing | not_china | yes | $1,173.98 |
| Go North Group AB | not_china | yes | $4,411.04 |
| guyweinberg121 | not_china | yes | $2,465.72 |
| Happy Innovations | not_china | yes | $5,796.93 |
| Hempway | not_china | yes | $991.86 |
| HOME GROWN | not_china | yes | $2,862.12 |
| HumanN from the Makers of SuperBeets | not_china | yes | $13,244.22 |
| Inglesina USA | not_china | yes | $2,465.52 |
| Itsumomo | not_china | yes | $2,893.34 |
| Jinx | not_china | yes | $692.70 |
| JobSite | not_china | yes | $3,065.39 |
| JOEY'Z | not_china | yes | $1,243.94 |
| Jonathan Derkits | not_china | yes | $479.04 |
| kegg | not_china | yes | $342.70 |
| kerenmoshe984 | not_china | yes | $1,147.23 |
| LANE LINEN | not_china | yes | $662.64 |
| Led Zeppelin LLC | not_china | yes | $19,192.41 |
| Linkin Park LLC | not_china | yes | $713.67 |
| LIVFRESH | not_china | yes | $6,185.41 |
| Locsanity | not_china | yes | $4.76 |
| Lubracil LLC | not_china | yes | $1,052.57 |
| M&J Trading Group | not_china | yes | $644.29 |
| Maneuver Marketing Pte. Ltd. | not_china | yes | $7,012.91 |
| Manukora | not_china | yes | $2,698.74 |
| Marée | not_china | yes | $22,903.32 |
| Mulwark | not_china | yes | $1,503.83 |
| Natural Cure Labs | not_china | yes | $407.66 |
| Nirvana LLC | not_china | yes | $1,255.40 |
| Nootie KOHA Pet | not_china | yes | $1,545.15 |
| northstilesgroup | not_china | yes | $1,735.51 |
| Orbio World | not_china | yes | $1,890.74 |
| Pantrymade | not_china | yes | $630.15 |
| Parrot Uncle | not_china | yes | $771.77 |
| Pearl West Group | not_china | yes | $4,771.49 |
| PetAmi, PAVILIA, OPUX, Sun Cube | not_china | yes | $3,078.48 |
| PetCove | not_china | yes | $2,396.38 |
| petespasta | not_china | yes | $1,531.97 |
| PIURIFY | not_china | yes | $1,576.97 |
| Plantifique | not_china | yes | $1,898.67 |
| pmdbeauty | not_china | yes | $3,819.44 |
| Productech Corporation | not_china | yes | $4,376.85 |
| PROSPEK | not_china | yes | $1,245.73 |
| ProSupps | not_china | yes | $725.34 |
| Purely Optimal | not_china | yes | $2,899.87 |
| Purify Life | not_china | yes | $3,272.77 |
| Purple Ladybug | not_china | yes | $2,835.68 |
| renuv | not_china | yes | $1,177.89 |
| Revivol-XR | not_china | yes | $1,058.75 |
| RHCP LLC | not_china | yes | $1,232.11 |
| RONCOHEN | not_china | yes | $18,651.89 |
| Royal Therapy | not_china | yes | $427.30 |
| Sandhu's | not_china | yes | $3,383.24 |
| Shinesty | not_china | yes | $1,229.77 |
| Skin Grip | not_china | yes | $1,843.04 |
| Slobproof | not_china | yes | $295.07 |
| SnapPower | not_china | yes | $2,605.74 |
| Snoozer | not_china | yes | $1,396.09 |
| SURI | not_china | yes | $1,460.28 |
| The Herbal Zen | not_china | yes | $2,484.51 |
| Thrasio | not_china | yes | $818.25 |
| ToiletTree | not_china | yes | $1,795.35 |
| trapo | not_china | yes | $447.99 |
| Tumella | not_china | yes | $19,223.01 |
| Vital Source Nutrition | not_china | yes | $1,122.20 |
| Vykee Nutrition | not_china | yes | $973.80 |
| Wholesome Wellness | not_china | yes | $2,954.33 |
