# Data and API findings: Valio Aimo "Trusted Trade Agents" (Junction 2026)

> Team reference document. **As of Sat 2026-11-14 01:17 Helsinki time (UTC+2).**
> Built from six exploration runs (catalog, search, price, availability, signals, end-to-end) and six
> independent verification runs made between Fri 13.11 23:05 and Sat 14.11 01:11, plus a final re-check of
> 206 product ids at Sat 01:16:57. Verifier corrections are applied, refuted claims are removed, and claims
> nobody could verify appear only in [section 11](#11-unverified--open-claims).

**How to read this document**

- Every finding has a stable id: `D-` data files, `A-` mock API, `F-` formulas, `S-` search, `R-` ranking,
  `W-` worked example, `X-` exceptions and demo fixtures, `G-` gateway design, `Q-` questions for mentors,
  `U-` unverified claims. Add new ids at the end of a section and never renumber.
- **Observed** means seen in the files or in API responses. **Inferred** means our interpretation (for example
  code meanings). **Recommendation** means what we should build.
- Prices are EUR excluding VAT per sales unit unless stated otherwise. Product names are the Finnish (`fi`) names.
- The mock API serves one frozen snapshot for delivery date **Mon 2026-11-16** (A-01). All live numbers come from
  that snapshot. Time-dependent results (cut-offs) are evaluated at Sat 14.11 01:17 unless stated otherwise.

## Contents

1. [TL;DR](#1-tldr)
2. [Data files](#2-data-files)
3. [Mock API as observed](#3-mock-api-as-observed)
4. [Derived facts and formulas](#4-derived-facts-and-formulas)
5. [Search](#5-search)
6. [Ranking signals and good-better-best](#6-ranking-signals-and-good-better-best)
7. [Worked example: 1,000 L lactose-free milk by Monday](#7-worked-example-1000-l-lactose-free-milk-by-monday)
8. [Exception catalogue and demo fixtures](#8-exception-catalogue-and-demo-fixtures)
9. [Design implications for the agent gateway](#9-design-implications-for-the-agent-gateway)
10. [Open questions for the Valio Aimo mentors](#10-open-questions-for-the-valio-aimo-mentors)
11. [Unverified / open claims](#11-unverified--open-claims)
12. [How to reproduce](#12-how-to-reproduce)

---

## 1. TL;DR

| # | Fact | Ids |
|---|---|---|
| 1 | The mock is a **frozen snapshot for Mon 2026-11-16**. `/availability` and `/price` ignore `requestedDate` (past dates included) and `customer`. Answers were identical from Fri 23:16 to Sat 01:17 (final re-check: 6,289 availability and 2,008 price entries compared with earlier captures, 0 differences). Only `timeNow` and the echoed date change. | A-01, A-02 |
| 2 | **Cut-offs are not enforced.** `availableDate` stays 2026-11-16 after `closingTime` has passed. Every Terminal cut-off for Monday (Tue 10.11 to Thu 12.11; Fri 13.11 for six sales-blocked items) had passed before the challenge started. Stock closes Sun 15.11 17:00 (about 86 % of Stock lines) or Fri 13.11 13:00 (about 14 %). On Saturday only about a third of products can still make Monday, all of them Stock. **After Sun 15.11 17:00 none can.** The gateway must decide feasibility itself, with an injectable clock. | A-03, F-04, X-06 |
| 3 | Availability states: Stock about 41 %, Terminal about 41 %, not deliverable about 18 % (empty `scheduleLines`). Terminal amount is always the sentinel **999999** (quantity unknown). A Stock amount is 0 (about 6 %, then `availableDate` is missing), an untracked placeholder equal to **floor(9,999,999,999 / unit size)** (about 20 %; it can be as low as 24,999,999, so a 1e8 threshold is wrong), or a real integer (about 74 %, median 42). | A-04, A-05, F-03 |
| 4 | About **1 % of lines use a different unit than the catalog `salesUnit`**, and both price and amount follow the API unit. Example: 465244 is catalog ST = 0.5 L, but the API unit is KI = 6 × 0.5 L and 6.22 EUR buys 3.0 L. Read the unit from `scheduleLines[].salesUnit`; `/price` has no unit field. | A-08, X-14 |
| 5 | **Content per unit:** `catalogPrice.value / comparisonPrice.value` gives litres or kg per API unit for about 97 % of food (the comparison price is missing for about 22 % of all products, mostly non-food). A static derivation covers about 88 % of products and agrees with the API about 94 % of the time. Remaining conflicts: drained weight, unit mismatch, a wrong `comparisonPrice` (476738, 469955) or wrong product data (464076). Use a 2-of-3 vote and send conflicts to a human. | F-01, D-06 |
| 6 | **Price:** `catalogPrice.value` is the net unit price excluding VAT. VAT comes from `tax.taxRate` (13.5 food, 25.5 non-food, 10 newspapers) and is rounded half-up per unit, so 1,000 × 1.15 = 1,150.00 while VAT on the total gives 1,146.35. A non-net price is list minus a tier (20, 18, 15 or 0 %). Customer net prices (`netPriceFound`) cover about 1 % of products, are time-boxed (all but one seen end 2026-12-31) and can be **above** list. | A-11, A-12, F-06 |
| 7 | **Validity windows are not applied:** the same price comes back for any date, including net prices that expire 2026-12-31 when 2027 is requested. The gateway must check `validFrom` / `validTo` against the delivery date, as Helsinki local dates. | A-09, F-07 |
| 8 | **Bad ids look like real products.** Unknown or malformed ids give `error: true` in `/price` (HTTP 200), but in `/availability` they get the same empty-`scheduleLines` shape as a real non-deliverable product. Deposit material codes cannot be priced. Validate ids (6 digits, contiguous range 460000–477545) before calling. | A-07, A-18 |
| 9 | **Catalog:** 17,546 products = 14,478 full GS1 Synkka records + 3,068 minimal ERP records (ALL-CAPS names; no brand, VAT code, claims or allergens). Allergens, claims and labels exist only as GS1 codes in `synkkaData.classifications`. Missing data means unknown, never free-from: about 31 % of food has no allergen data. | D-02, D-04 |
| 10 | **Diet traps:** lactose-free = claim `FREE_FROM_LACTOSE` (4,178 products), not `LOW_LACTOSE` (321: "vähälaktoosinen", HYLA). Lactose-free products still contain milk (1,485 declare `AM` CONTAINS). Gluten-free products can contain wheat starch (30 declare `UW`) or oats (192 declare only `GO`). | D-04, S-05 |
| 11 | **Substitution rules** exist on only 196 products (250 rules, 75 % one-way, 1 self-loop). 36 % drop a claim or label or add an allergen, 30 % change the sales unit, and only about a third of blocked originals have an orderable substitute. Treat rules as hints, re-check everything and add a similarity fallback. | D-12, X-26..X-33 |
| 12 | **Signals are sparse and coarse.** Delivery reliability covers 25.2 % of products (56 % of values are exactly 1.0). Carbon covers 62.9 % and is a category average (every lactose-free milk is 1.1 kg CO2e/kg). Use them for group comparisons and approval triggers, not to choose between near-identical SKUs. | D-10, D-11 |
| 13 | **Headline example:** 1,000 L lactose-free milk by Monday = 1,000 × **464306** (Valio Arki Eila kevytmaitojuoma 1 l, net price 1.01) = **1,010.00 EUR excl. VAT**, from Stock, order by Sun 15.11 17:00. Of the 29 genuine options, 8 cover 1,000 L from Stock, 4 only partially, 16 Terminal options are past their cut-off and 1 cannot be delivered. | W-03, W-04 |
| 14 | **Search:** match the product type on the end of Finnish compound words in the `fi` name and apply hard claim and allergen filters. Naive keyword search fails badly: "laktoositon maito" returns milk chocolate and ice cream. The LLM must supply compound heads and exclusions (kirjolohi is not lohi; maapähkinävoi is not voi). | S-01..S-05 |
| 15 | **We build the trust layer ourselves.** There is no order endpoint, no quantity-based pricing, no deposit price and no real lead-time calendar. Quotes with validity, order placement mock, approvals with deadlines, and audit live in our gateway. | G-01..G-12 |

---

## 2. Data files

### D-01 Files and provenance (Observed)

| File | Size / rows | Content | Notes |
|---|---|---|---|
| `data/raw/products.json` | 87 MB, 17,546 products | Static catalog | JSON array, 147 distinct JSON paths, all in the schema, no type mismatches |
| `data/raw/product_schema.json` (same as `docs/reference/product-data-schema.json`) | 30 KB | JSON Schema with field descriptions | Typo `descrption` on `keyIngredients`. Says `tax.taxRate` from the price API is the VAT source of truth |
| `data/raw/delivery_reliability.csv` | 4,425 rows | `productId,deliveryReliability` (0..1) | See D-10 |
| `data/raw/carbon_footprint.csv` | 11,033 rows | `productId,AVG kg CO2-eq/kg` | Category average, see D-11 |
| `data/raw/openapi.json` (same as `docs/reference/valio-aimo-openapi.json`) | 12 KB | OpenAPI for `/ping`, `/price`, `/availability`, downloads | Files "do not change during the challenge unless announced". Asks teams not to poll prices or availability for all products. "Undisclosed rate limits" |

The JSON Schema title states the data is "inspired by real-world" but "does not contain fully accurate product
information" and must not be used outside Junction 2026.

### D-02 Two kinds of product record (Observed)

| | Full GS1 Synkka record | Minimal ERP record |
|---|---|---|
| Count | 14,478 (82.5 %) | 3,068 (17.5 %) |
| How to detect | `synkkaData.gtin` present | `synkkaData.gtin` absent |
| Names | Mixed case, fi / sv / en | 3,056 ALL-CAPS fi names, e.g. 460013 `TOMAATTI COEUR DE BOEUF ES`; sv missing on 1,444 |
| Brand, vatCode, min/max temperature, unitConversions, producers | Yes | Never |
| Claims and allergens | When declared | Never. Labels are temperature labels only (2,800 records) |
| keyIngredients (fi) / nutritionalContent | 12,920 / 11,520 | 1,124 / 731 |
| Typical content | Branded food, disposables | Kitchenware (808), fresh produce (617), office supplies (224). Vendors WULFF OY AB 232, SAMBONET 177 |

Consequence: a request with an allergen or diet constraint can never be auto-approved for a minimal record.

### D-03 Data dictionary for `products.json` (Observed)

Coverage is over all 17,546 products unless stated. "Full only" means the field never appears on minimal records.

| Field | Meaning | Coverage | Example / note |
|---|---|---|---|
| `id` | Product code used in all APIs and CSVs | 100 % | Unique 6-digit strings 460000–477545, no gaps. `"464306"` |
| `salesUnit` | Unit the catalog says the product is sold and priced in | 100 %, 17 codes | KI 8,005, ST 5,607, KG 1,068. The API may use another unit (A-08) |
| `baseUnit` | Smallest handling unit (the `units[]` entry with size 1) | 100 %, 16 codes | Equal to `salesUnit` for 10,924 (62.3 %) |
| `units[]` | Packaging hierarchy `{unitId, sizeInBaseUnits, gtin}` | 100 % | 464306: ST 1, KI 20, KRS 160, PAL 160. 8,476 of 44,357 rows have no `gtin` |
| `allowedLotSize` | Order step in sales units ("quantity must be a multiple of it") | 100 % | 0.01 on 96.2 %. Larger steps only on 672 KG-sold and 2 KI products (F-02) |
| `category` | 5-digit category code, no names | 100 %, 349 codes | 10400 = liquid milk (inferred, D-09) |
| `vendorName` | Supplier, split by warehouse | 100 %, 648 strings | `VALIO OY TUORE` / `VALIO OY PAKASTE` |
| `temperatureCondition` | Storage class code 1–9; meanings not published | 99.7 % (61 missing) | Decoding in D-08 |
| `countryOfOrigin` | ISO alpha-2, lower case | 99.9 %, 98 values | fi 44.7 %. Non-ISO values zy 179, xs 11, zz 5 |
| `salesUnitGtin` | GTIN of the sales unit | 99.1 % | Always equals `units[salesUnit].gtin`. 958 fail the check digit, all of them 2-prefixed in-store codes |
| `deposits[]` | Returnable packaging charged per sales unit | 506 products (2.9 %) | 461051 Red Bull: `{"material":"4","unit":"ST","quantity":24.0}`. Not priceable (A-18) |
| `substitutions[]` | `{product, substituteProduct}` rules | Key on 196, non-empty on 189 | D-12 |
| `deleted` | Always false | 100 % | Ignore |
| `synkkaData.names[]` | Name per language | fi 100 %, en 99.99 %, sv 91.8 % | en is a copy of fi on 783 products |
| `synkkaData.brand` | Brand | 82.4 %, full only | 168 brands with stray whitespace |
| `synkkaData.gtin` | Consumer-unit GTIN | 82.5 %, full only | Equals `units[baseUnit].gtin` for 93.7 % |
| `synkkaData.vatCode` | VAT class | 82.5 %, full only | Messy (159 × `MEDIUM MEDIUM`, 4 × empty). Use `tax.taxRate` (A-12) |
| `synkkaData.classifications[]` | Allergens, claims, labels, nutrition | Groups present on 17,535 | See D-04 |
| `synkkaData.nutritionalContent[]` | Canonical nutrition table, mostly per 100 g or 100 ml | 12,251 (69.8 %, about 90 % of food) | `{"id":"CHOAVL","value":3.1,"unit":"GRM","basisQuantity":100.0,...}`. Lactose (`LACS`) on 3,573 products |
| `synkkaData.keyIngredients[]` | Ingredient statement text | fi 80.0 % (includes 1,124 minimal records) | Allergens are written in UPPERCASE, e.g. "pastöroitu MAITO" |
| `synkkaData.ingredients[]` | Structured, but only the one characterising ingredient, with origin stage | 21.3 %, full only | 460000: potato 56 %, `FARMING`, country 246 (FI). 48 entries have sequence 0 |
| `synkkaData.marketingTexts[]` | Marketing text | fi 67.9 %, full only | |
| storage / usage / preparation / disposal texts | Instructions | fi 49.4 / 21.1 / 19.8 / 26.4 % | |
| `synkkaData.unitConversions[]` | One packaging level with net weight, volume and dimensions | 82.5 %, full only | Usually describes the sales unit, not a fixed GS1 level (D-07) |
| `synkkaData.minTemperature` / `maxTemperature` | Storage temperature in °C | 57.9 % / 58.5 %, full only | Dairy typically 2 / 6 |
| `synkkaData.variableUnit` | Sold by variable (catch) weight | true on 632, of which 628 KG-sold | |
| `synkkaData.producers[]` | Manufacturer GLN and name | 82.5 %, 334 GLNs | The real producer behind a warehouse vendor name |
| `synkkaData.countriesOfOrigin[]` | Numeric ISO codes | 82.4 % | 246 = Finland. Sometimes disagrees with `countryOfOrigin` (U-09) |
| `synkkaData.fishingReports[]` | Species, FAO area, gear, production method | 353 (2.0 %) | TRR 79, SAL 70, HER 59. Typos such as `MARINE_FISHERY1` |
| `synkkaData.safetyData[]` | GHS statements, lower-case codes | 667 (3.8 %) | `h319`, `p280` |
| `synkkaData.medias[]` | Image ids only, no URLs | 76.2 % | No primary flag on 1,394 products |
| `synkkaData.lastUpdated` | Last Synkka update | Full only | 2022-10-22 to 2025-10-05, 93 % in 2025 |

### D-04 Where allergens, claims, labels and nutrition live (Observed)

All of them live only in `synkkaData.classifications[]`, as groups `{name, type, values[]}` whose values are GS1
code-list ids. Raw excerpt from 464306 (lactose-free milk drink):

```json
{"type":"ENUM","name":"allergen","values":[{"id":"AM","unit":"CONTAINS"}]}
{"type":"ENUM","name":"nutritionalClaim","values":[{"id":"FREE_FROM_LACTOSE","synkkaId":"LACTOSE","unit":"FREE_FROM"}, ...]}
{"type":"ENUM","name":"packagingMarkedLabel","values":[{"id":"GOODS_FROM_FINLAND_BLUE_SWAN","synkkaId":"GOODS_FROM_FINLAND_BLUE_SWAN"},{"id":"coolTemperature"}]}
```

| Group `name` | Products with values | Value units | Use |
|---|---|---|---|
| `allergen` | 7,205 | CONTAINS 15,610 · MAY_CONTAIN 9,956 · UNDECLARED 303 | Allergens per GS1 AllergenTypeCode |
| `nonAllergen` | 5,119 | FREE_FROM 68,597 | Explicit "free from" declarations |
| `nutritionalClaim` | 7,618 | FREE_FROM 11,836 · DIET 5,334 · HIGH 823 · LOW 820 · NO_ADDED 662 | Diet and nutrition claims |
| `packagingMarkedLabel` | 17,255 | none | Quality, origin and eco labels, plus `warmTemperature` / `coolTemperature` / `freezeTemperature` |
| `nutritionFact` | 12,244 | GRM, KJO, E14 ... | Copy of `nutritionalContent` (identical on 9,833 of 12,244) |
| `gda` | 11,513 | GRM, KJO, E14 | Subset of `nutritionFact` |
| `mineral` / `vitamin` / `composition` | 1,783 / 727 / 14 | MGM, MC, GRM | Caffeine and taurine sit in `composition` |
| `packaging` | 0 | | Always empty |

**Claims** (products): `FREE_FROM_LACTOSE` 4,178 (23.8 %) · `FREE_FROM_GLUTEN` 3,049 (17.4 %) · `VEGAN` 2,959 (16.9 %) ·
`VEGETARIAN` 2,358 (13.4 %) · `FREE_FROM_PRESERVATIVES` 1,526 · `FREE_FROM_COLOURING_AGENTS` 932 · `FREE_FROM_ADDITIVES` 690 ·
`NO_ADDED_SUGARS` 662 · `HIGH_FIBRE` 420 · `FREE_FROM_EGGS` 418 · `HIGH_PROTEIN` 417 · `LOW_SODIUM_SALT` 390 ·
`FREE_FROM_SWEETENERS` 358 · `FREE_FROM_SOY` 337 · `LOW_LACTOSE` 321 · `FREE_FROM_FAT` 158 · `FREE_FROM_WHEAT` 141 · `LOW_FAT` 110.
No product has both `FREE_FROM_LACTOSE` and `LOW_LACTOSE`.

**Labels** (products): `GOODS_FROM_FINLAND_BLUE_SWAN` (Hyvää Suomesta) 2,057 · `MADE_IN_FINLAND_FLAG_WITH_KEY` (Avainlippu) 1,772 ·
`FINNISH_HEART_SYMBOL` 826 · `EU_ORGANIC_FARMING` 456 · `SVANEN` 362 · `RAINFOREST_ALLIANCE` 234 · `EU_ECO_LABEL` 195 ·
`MARINE_STEWARDSHIP_COUNCIL_LABEL` 104 · `FAIR_TRADE_MARK` 92 · `AQUACULTURE_STEWARDSHIP_COUNCIL` 51 · `KRAV_MARK` 26 ·
`OFFICIAL_ECO_LABEL_SUN` 17 · `SOIL_ASSOCIATION_ORGANIC_SYMBOL` 11 · `PUHTAASTI_KOTIMAINEN` 7 · `DOLPHIN_SAFE` 7 · `UTZ_CERTIFIED` 3.
Temperature labels: warm 10,057 (57.3 %), cool 4,060 (23.1 %), freeze 3,245 (18.5 %). There is **no Sirkkalehti code** and
no text mention of it. Use the exact ids above (not "MSC", "ASC" or "FAIR_TRADE").

**Allergen codes.** GS1 AllergenTypeCode (observed in the data, meanings from the GS1 code list): `AM` milk, `AW` cereals
containing gluten, `UW` wheat, `GB` barley, `NR` rye, `GO` oats, `GS` spelt, `AE` egg, `AY` soy, `AN` tree nuts (sub-codes `SA`
almond, `SH` hazelnut, `SW` walnut, `SC` cashew, `SP` pecan, `SR` Brazil nut, `SM` macadamia, `ST` pistachio; checked against
product texts, e.g. 119 of 138 pistachio products carry `ST` and 71 of 73 walnut products carry `SW`), `AP` peanut,
`AS` sesame, `AF` fish, `AC` crustaceans, `UM` molluscs, `BC` celery, `BM` mustard, `AU` sulphites, `NL` lupin, `ML` lactose,
`X99` "no declarable allergens". Inferred from the products that carry them: `NC` cocoa, `NE` peas, `NK` coriander, `NW` carrot,
`NM` maize, `NP` pulses, `CM` chicken, `BF` beef, `PO` pork, `PN` pine nut. Unknown: `BP`, `SO`, `ABD`, `ADQ`, `UN`.
Most frequent CONTAINS codes: AM 3,160 · AW 2,794 · UW 2,550 · AE 1,317 · AY 1,104 · GO 569 · AF 476 · BM 467 · ML 449.

**Semantic traps** (Observed; build these rules into code, see S-05):

| Trap | Evidence |
|---|---|
| Missing allergen data means unknown | About 31 % of food products have no allergen or nonAllergen values at all: 2,493 of 11,921 full-record food products, plus every minimal record (0 of 3,068 have any) |
| Lactose-free still contains milk | 1,485 `FREE_FROM_LACTOSE` products declare `AM` CONTAINS (361 more `AM` MAY_CONTAIN), including 464306. Never treat `AM` as a lactose conflict |
| `ML` (lactose) is coded inconsistently | `ML` CONTAINS on all 19 regular Arla milks but none of the 31 regular Valio milks in 10400 (lactose 3.8–4.9 g/100). Its absence does not mean lactose-free. 4 lactose-free products declare `ML` CONTAINS (465346, 465554, 465920, 470988) |
| Lactose-free claim with lactose | 23 `FREE_FROM_LACTOSE` products have `LACS` > 0.01 g/100 g, e.g. 460050 remoulade `LACS` = 1.0 |
| Gluten-free can contain wheat or oats | Of 3,049 `FREE_FROM_GLUTEN`: 30 declare `UW` CONTAINS (e.g. 460124 Fria kuituleipä, gluten-free wheat starch), 11 declare `AW`, 43 declare any of `UW`/`AW`/`GB`/`NR`, 192 declare only `GO` (oats) |
| Cross-code contradictions | 16 products list `AW` as free-from while declaring `UW` CONTAINS (19 if barley and rye count), e.g. 467828 Rummo Pappardelle, 466324 Kikkoman. 468044 and 469429 list the same code as both CONTAINS/MAY_CONTAIN and FREE_FROM |
| `X99` encoded as CONTAINS | `X99` appears as allergen CONTAINS on 121 products (e.g. 460548 juice) and in nonAllergen on 74 |
| Vegan with lactose | 7 `VEGAN` products declare `ML` CONTAINS (all Santa Maria spices) |
| Vegetarian is not vegan | 466745 Valio MiFU jauhis is `VEGETARIAN` + lactose-free but not `VEGAN` (milk protein) |

### D-05 Unit codes (Observed counts; meanings Inferred)

Unit codes are SAP-style technical codes without translations (schema). The UN/ECE mapping is our proposal; keep the raw code.

| Code | as `salesUnit` | as `baseUnit` | in `units[]` | Inferred meaning | Proposed UN/ECE Rec 20/21 |
|---|---|---|---|---|---|
| KI | 8,005 | 1,573 | 14,157 | Case or carton ("Kiste") | XCS |
| ST | 5,607 | 9,770 | 9,832 | Piece ("Stück") | H87 |
| KG | 1,068 | 1,106 | 1,131 | Kilogram (catch weight possible) | KGM |
| PAK | 880 | 1,725 | 1,813 | Pack | XPK |
| BAG | 697 | 1,222 | 1,246 | Bag | XBG |
| RAS | 328 | 494 | 524 | Box or tray ("rasia") | XBX (to confirm) |
| PRK | 320 | 533 | 534 | Jar or tub ("purkki") | XJR |
| BOT | 310 | 893 | 903 | Bottle | XBO |
| SK | 120 | 89 | 129 | Sack ("säkki") | XSA |
| CS | 72 | 74 | 227 | Case | XCS |
| KLE | 66 | – | 69 | Crate of bottles | XCR (to confirm) |
| KRT | 48 | 41 | 97 | Carton ("kartonki") | XCT |
| KAN | 13 | 14 | 14 | Canister ("kanisteri") | to confirm |
| PAL | 4 | 4 | 8,303 | Pallet | XPX |
| NIP / DSP / DZ | 3 / 3 / 2 | 3 / 3 / 2 | 5 / 11 / 2 | Bundle ("nippu") / display / dozen | to confirm / – / DZN |
| KRS | – | – | 5,288 | Pallet layer ("kerros") | – |
| DOL / KOR | – | – | 26 / 6 | Roll cage ("dolly") / crate ("kori") | – / XCR |
| ZML | – | – | 37 | Litres for 23 of 24 liquid milks, **but not** for 469209 (20 l novobox: ZML 0.1, API 19.9 L) or for cheese, quark and yoghurt (469338 Edam: ZML 1.33) | Do not use |
| PNT / MDO | – | – | 2 / 1 | Unknown | – |

Top `salesUnit`/`baseUnit` pairs: ST/ST 5,604, KI/ST 4,076, KI/KI 1,573, KG/KG 1,068, KI/PAK 863. Two "fractional cases"
(460857 KI = 18.5, 461268 KI = 2.5) are cases measured in kg (`baseUnit` KG).

### D-06 Pack content per unit (Observed)

Litres or kilograms per sales unit are needed to turn "1,000 L" into an order quantity. There are two sources.

**API-implied content (preferred)**: `catalogPrice.value / comparisonPrice.value`, per the **API unit** (F-01).
Available when `/price` returns a comparison price: 753 of 1,000 random products, 96.7 % of food.

**Static derivation (fallback)**, in priority order:

1. `salesUnit` KG means 1 kg per unit. `baseUnit` KG means `sizeInBaseUnits` kg.
2. `synkkaData.unitConversions[0]`: `netWeight` in GRM/KGM gives kg; `volume` in LTR/MLT/CLT gives litres (a `volume` in GRM/KGM
   is a mass). Map it to the unit it describes (D-07).
3. A `units[]` entry `KG` gives kg per base unit as 1 / `sizeInBaseUnits`. Avoid `ZML` (D-05).
4. Parse the name, for example "12 x 1 l", "4x120g", "2,5 dl", "200/150g" (net/drained), "M90" (90 eggs), and multiply by
   `units[salesUnit].sizeInBaseUnits`.

Coverage and accuracy: an estimate exists for 15,470 products (88.2 %, about 97 % of food). Out of sample it matches the
API-implied content within 2 % for about 94 % of comparable products (about 90 % if kg-vs-L dimension mismatches count as
failures). High-confidence estimates match 97.4 % of the time, medium-confidence 88.3 %.

Why they disagree (Observed):

| Class | Examples | Notes |
|---|---|---|
| API uses another unit (A-08) | 465244, 467042 (10 kg = KI), 460635 (4.5 kg = KI of 3), 465987, 474449, 462242 | The price is per the API unit, which is visible in `scheduleLines[].salesUnit` |
| Drained weight | 464940 Abba tuna 200/150g → 0.150 kg · 463519 "8,2/4,5kg" → 4.497 kg · 476425 Filos 3/1,5 kg → 1.501 kg · 469441 Mutti 2450 g → 1.501 kg · 461648 Del Monte 415 g → 0.23 kg | 49 of 51 names of the form "a/b kg" use the second (drained) figure. Some names show only the net weight |
| Wrong `comparisonPrice` | 476738 Arla Kalinka 150 g: 0.91 EUR at 0.30 EUR/kg implies 3.03 kg (about 20× off) · 469955 Flora 200 × 10 g: 112.10 EUR/kg implies 0.2 kg instead of 2 kg | Both have empty `scheduleLines`, so no API unit is visible |
| Wrong product data | 464076 Valio Eila voi 4x5 kg (ST): `unitConversions` says 20 kg, but the name, `units` (KI = 4 ST) and the price (37.33 / 7.47 = 4.997 kg) say 5 kg | The Synkka GTIN sits on the KI unit |
| Piece counts missing from the name | 463233 Valio voi 10 g (KI): 23.42 / 11.15 = 2.1 kg per KI · 461301 Cookie 96 kpl 80 g → 7.68 kg | Name-only conversion would under-order about 200× for 463233. 461301 has the 7,680 g in its CASE-level `netWeight` |
| Cent rounding | 464119: 13.32 / 1.33 = 10.015 L (really 10) · 469119: 2.08 / 1.19 = 1.748 L (really 1.75) | Snap to the static value when within about 1 % |

### D-07 `unitConversions` traps (Observed)

- Exactly one packaging level per full record (length 1 on 14,474, 0 on 4). It is `BASE_UNIT_OR_EACH` when sold per piece
  (8,163) and `CASE` when sold per case (6,052). It describes the **sales unit**, not a fixed GS1 level: across 2,000 API-checked
  ids, CASE records matched the sales unit 103 times and the base unit 0 times.
- Exceptions: 52 BASE records on case-sold products and 197 CASE records on piece-sold products. When `synkkaData.gtin` equals the
  GTIN of a non-base unit (32–33 products), the level describes that unit (464076 above).
- `volume` behaves like GS1 net content in any unit (GRM 5,498, H87 1,500 pieces, KGM 875, LTR 762, MLT 259, CLT 50 ...), not
  physical volume. Example 463989 buns: `{"volume":{"unit":"H87","value":2.0},"netWeight":{"unit":"GRM","value":214.0}}`.
- In 230 records `volume` (read as mass) and `netWeight` differ by more than 2 %. Against the API neither field wins reliably.
- For KG-sold goods the level is the physical piece: 460675 "Snellman Flank steak n2kg" has `netWeight` 2000 GRM while one
  sales unit is 1 kg.

### D-08 `temperatureCondition` codes (counts Observed, meanings Inferred)

| Code | Products | Temperature label | Typical min / max °C | Inferred meaning |
|---|---|---|---|---|
| 1 | 240 | cool (all) | 0 / 3 | Chilled 0–3 (fresh fish, meat) |
| 2 | 324 | cool | 2 / 4 | Chilled up to +4 (leafy vegetables) |
| 3 | 1,673 | cool | 2 / 6 | Chilled up to +6 (dairy) |
| 4 | 1,803 | cool (1,798) | 4 / 8 | Chilled up to +8 |
| 5 | 221 | none on 213 | 2 / 7 | Chilled produce (tomatoes, cucumbers) |
| 6 | 10 | none | max about 20 | Produce and other goods stored cool to ambient: bananas, citrus, peppers, eggs 472535, salami snacks, milks 463047 and 473142 |
| 7 | 3,152 | freeze (3,148) | −25 / −18 | Frozen. 460675 flank steak is code 7 and frozen |
| 8 | 10,053 | warm (10,048) | 10 / 22 | Ambient |
| 9 | 9 | mixed | – | Unclear (e.g. Barilla spaghetti next to frozen croissants) |
| missing | 61 | – | – | Unknown (e.g. 460658 early potatoes). Treat as unknown, not as a mismatch |

Contradiction example: 463989 bun has the text "Stored frozen" but code 3 and `coolTemperature`.

### D-09 Category, vendor, origin, GTIN and names (Observed; labels Inferred)

- **Category:** 349 five-digit codes without names. Sizes: 4 codes with 1 product, 54 with 2–9, 177 with 10–49, 107 with
  50–199, 7 with 200+. Families by the first two digits (labels inferred from product names): 10 dairy, 11 bread, 17 chilled
  food, 18 fresh meat and fish, 20 kitchenware, 21 dry groceries, 22 beverages and spices, 41 frozen, 52 confectionery,
  63 cleaning and hygiene, 64 disposables, 84/85 alcohol, 90 office. Useful codes: 10400 liquid milk (91 products, 35
  lactose-free), 10401 cream, 10402 plant drinks, 10405 milk powder, 10412 yoghurt, 10430 quark, 10590 eggs, 10600 cheese,
  10603 mozzarella crumbles and grated cheese, 18701 salmon **and** rainbow-trout fillets (same code), 18720 beef, 18750
  chicken, 41820 bulk ice cream. 98.4 % of substitution rules stay within the same 3-digit prefix.
- **Vendor:** 648 strings. About 30 base names are split by warehouse suffixes (TUORE, PAKASTE, KUIVA, VIILEÄ, VV), e.g.
  `RAVINTORAISIO OY KUIVA / VIILEÄ / PAKASTE`. The real manufacturer is in `synkkaData.producers[]` (GLN). Largest: DUNI OY,
  PROFESSIONAL 817; VALIO OY TUORE 788; ATRIA SUOMI OY TUORE 300.
- **Origin:** `countryOfOrigin` fi 7,849, de 1,029, it 977, se 874, cn 741. Only 2,051 of the 7,849 Finnish-origin products
  carry the Hyvää Suomesta label, so "Finnish" needs its own preference (origin or label).
- **GTIN:** `salesUnitGtin` lengths 13 (16,262), 14 (945), 12 (164), 8 (16); 1,160 are 2-prefixed variable-measure codes; no
  duplicates.
- **Names:** Finnish first. `en` equals `fi` on 783 products (e.g. 460465), `sv` is missing on 1,446. Some translations are
  wrong: 474864 fi "soijajuoma" is en "almond drink" (allergen `AY` soy); 466146 "Kalapihvi kirjolohesta" (rainbow trout) is en
  "Salmon steak". 469 fi names contain double spaces.

### D-10 `delivery_reliability.csv` (Observed)

- 4,425 rows, no duplicates, all ids in the catalog: 25.2 % coverage (26.5 % of food).
- Mean 0.972, median 1.0, p05 0.871, p10 0.936. Exactly 1.0: 2,490 (56.3 %). Exactly 0.0: 12 (e.g. 477051 Valio glögi drink,
  476973 Hartwall water).
- Low values cluster: fresh beef 18720 (n = 15, mean 0.509), temperature class 1 (n = 50, mean 0.809), vendor KALAVAPRIIKKI OY
  TUORE (mean 0.832). Beef fixture: 463059 has 0.354.
- Some values look like ratios of very few deliveries: 0.5 × 19, 0.0 × 12, 0.667 × 10 with no neighbouring values. About 279
  values match a small fraction p/q (q ≤ 20) within rounding, roughly half of them by chance (Inferred).
- Products without a value lean towards Terminal: 42 % of no-value products are Terminal, against 26 % of products with 1.0.
  The Stock/Terminal gap in mean value is small (0.983 vs 0.957).
- The file does not say what is measured (inbound or outbound, on time or in full), over which period, or on how many
  deliveries (Q-13).

### D-11 `carbon_footprint.csv` (Observed)

- 11,033 rows, no duplicates, all ids in the catalog: 62.9 % coverage; 76 % of products in categories 1x–4x, almost
  nothing for non-food (63xx 6 of 1,817; 64xx 8 of 1,039; 90xx 0 of 224).
- Unit: kg CO2e per kg, described as a **category average**. Range 0.13 (oyster mushrooms) to 30.46 (minced lamb), median 2.11,
  177 distinct values. 795 rows carry float artefacts such as `0.14500000000000002`; round to 2 decimals.
- Values are constant inside a group but do not follow our category codes exactly: 190 of 279 covered categories have a
  single value. 22630 spices are 4.975 for 376 items but 0.79 for 3 Meira spices. 0.79 appears on 232 products in 47
  categories, including all 109 ice creams with a value (41820). It may be a default (U-11).
- Inside one buyer need the value is usually identical (all lactose-free milks 1.1; zucchini NL/ES and FI both 0.825). It
  separates product groups (beef 26.2, chicken 5.1, plant drinks 0.43) rather than SKUs.
- Both files present: 3,123 products (17.8 %); neither: 5,211 (29.7 %).

### D-12 `substitutions[]` (Observed)

| Fact | Value |
|---|---|
| Products with the key / non-empty | 196 / 189 (7 empty arrays, e.g. 463381) |
| Rules | 250; `product` always equals the owning id; 218 distinct substitutes, all in the catalog |
| Fields | Only `{product, substituteProduct}`; no priority, ratio, reason or validity. List order may or may not mean priority (only 7 of 35 multi-substitute lists are in ascending id order) |
| Direction | 249 non-self edges: 31 reciprocal pairs (62 edges), 187 one-way. 1 self-loop: 471661 |
| Similarity | Same category 92.0 %, same 3-digit prefix 98.4 %, same vendor 61.6 %, same `salesUnit` 70.0 %, same `temperatureCondition` 76.8 % |
| Risk | 89 rules (35.7 %) drop a claim or label or add a CONTAINS allergen (38 of them partly because data is missing on one side). Dropped: VEGETARIAN 17, VEGAN 16, FREE_FROM_GLUTEN 13, EU_ORGANIC_FARMING 12, FREE_FROM_LACTOSE 12 |
| Price | 244 pairs comparable per kg or L: median ratio 1.02; 73 (30 %) substitutes are more than 20 % dearer; extremes 470961 → 460603 potatoes 5.57×, 460211 → 467549 cabbage 3.69× |
| Live rescue value | As of Sat 00:05, 67 originals could not make Monday; only 22 (33 %) had a substitute that could |

Seven edges are unsafe for a must-have diet claim (the substitute lacks the claim and is unsuitable):

- Gluten-free originals pointing to products that declare `AW` CONTAINS: 468465 → 470863 Oatly, 473609 → 464320 Oatly iKaffe,
  469288 → 470341 Oatly iMat Visp, 471376 → 476523 Findus.
- Lactose-free mozzarella 466375 → 466151, 468526, 475908, none of which carries `FREE_FROM_LACTOSE`. The fourth substitute,
  473986 (lactose-free), cannot be delivered.

No edge conflicts on allergen codes alone; the original 466375 itself declares `AM` CONTAINS. Safety checks must be claim-based (S-05).

### D-13 Other data-quality issues (Observed)

- 11 records have `netWeight` > `grossWeight` (unit mix-ups, e.g. 464834 net 5600 GRM vs gross 6.46 GRM).
- 222 products have more than one unit with `sizeInBaseUnits` 1.
- `fishingReports`: 13 empty Latin names; 5 production-method typos (`MARINE_FISHERY1`, `AQUACULTURE1`).
- `materialAdditionalDescriptions` has duplicate languages on 11 products.
- `nutritionalContent`: 16 products mix bases (e.g. 461219 has 9 × 100 MLT and 1 × 100 GRM).
- 465611 "NÄYTE" (sample) is a placeholder product priced 0.01 EUR. Filter it from cheapest-first searches.
- 17 products with "laktoositon" in the fi name lack the `FREE_FROM_LACTOSE` claim (e.g. 464095, 470934), while 462234
  "Frödinge vähälaktoosinen mansikkakakku" carries `FREE_FROM_LACTOSE`.

---

## 3. Mock API as observed

### A-00 Basics

| Item | Value |
|---|---|
| Base URL | `https://junction26.valioaimo.fi/api` |
| Auth | Header `X-API-Key`. In the cloud sandbox the network proxy injects the real key; send the placeholder `proxy-injected`. Locally, export `VALIO_AIMO_API_KEY` |
| Endpoints | `GET /ping` → `{"status":"ok"}` · `POST /availability` · `POST /price` · `GET /{products,delivery-reliability,carbon-footprint}/download` (redirect, use `curl -L`) |
| Request body | `{"customer":"123","requestedDate":"YYYY-MM-DD","products":["460013", ...]}` with 1–1,000 ids |
| Order endpoint | **None.** No quote, order or reservation endpoint exists |
| Usage observed | About 290 sequential calls by 13 agents; no HTTP 429 and no rate-limit headers |

### A-01 Frozen, deterministic snapshot (Observed)

- Product entries were identical across every requested date tried (2025-07-01, 2025-11-13, 2026-11-13 to 2026-11-23,
  2026-12-14, 2026-12-30, 2026-12-31, 2027-11-15), across midnight, across customers ("123", "999", "999999", "C-998877"),
  across batch composition and order, and over time from Fri 23:16:45 to Sat 01:16:57.
- Final re-check at Sat 01:16:57: 206 ids compared with 126 earlier availability captures (6,289 entries) and 35 price captures
  (2,008 entries): 0 differences.
- Only `timeNow` (live Helsinki clock, whole seconds, within about 1 s of the client clock) and the echoed
  `requestedDate` / `pricingDate` change.
- Not observable: whether the data rolls forward after Sun 15.11 17:00 or on Monday (U-01).

### A-02 `/availability` request and response (Observed)

The OpenAPI example body, re-run at Sat 01:16:43, shows four different states:

```json
{"timeNow":"2026-11-14T01:16:43+0200","requestedDate":"2026-11-16T00:00:00+0200","products":[
 {"productId":"460013","salesBlock":false,"scheduleLines":[]},
 {"productId":"460063","closingTime":"2026-11-12T15:00:00+0200","salesBlock":false,"logisticModel":"Terminal",
  "scheduleLines":[{"salesBlock":false,"availableAmount":999999.0,"availableDate":"2026-11-16","salesUnit":"KI"}]},
 {"productId":"463989","closingTime":"2026-11-13T12:30:00+0200","salesBlock":true,"logisticModel":"Terminal",
  "scheduleLines":[{"salesBlock":true,"availableAmount":999999.0,"availableDate":"2026-12-30","salesUnit":"ST"}]},
 {"productId":"460056","closingTime":"2026-11-15T17:00:00+0200","salesBlock":false,"logisticModel":"Stock",
  "scheduleLines":[{"salesBlock":false,"availableAmount":63.0,"availableDate":"2026-11-16","salesUnit":"PAK"}]}]}
```

(460013 tomato: cannot be delivered · 460063 oven rinse aid: Terminal, cut-off passed · 463989 seasonal bun: sales-blocked,
December · 460056 tumblers: Stock 63 PAK, open until Sun 17:00.)

| Field | Documented meaning | Real behaviour |
|---|---|---|
| `timeNow` | Server time (Helsinki) | Live clock, format `2026-11-14T01:16:57+0200` (no colon in the offset). Use it as "now" by default |
| `requestedDate` | Request date at midnight | Echo only; `+0300` for summer dates. Past dates accepted with HTTP 200 |
| `products[]` | One entry per requested id, in request order | Exactly that, duplicates included |
| `closingTime` | Order cut-off to receive goods on `availableDate` | Cut-off of the fixed Monday slot. **Never moves forward after it passes** (A-03) |
| `salesBlock` | Product cannot be ordered | Always equal to the line-level flag (0 disagreements in 3,412 lines). True on only 6 known products (X-08) |
| `logisticModel` | Stock (known quantities) or Terminal (supplier warehouse, quantity unknown) | Stock about 41 %, Terminal about 41 %. **Key absent** (not null) when `scheduleLines` is empty |
| `scheduleLines[]` | One entry if available; empty = cannot be delivered on any date | Never more than 1 entry. Empty on about 18–20 % of random products, and also for unknown ids (A-07) |
| `availableAmount` | Quantity in `salesUnit`; Terminal always 999999; 0 = not available | See A-05 for the placeholder values |
| `availableDate` | Earliest date the amount is available; may differ from the request | Always 2026-11-16, whatever was requested, except blocked items (2026-12-30, 2026-12-16). **Key absent** on zero-amount lines |
| `scheduleLines[].salesUnit` | Technical sales unit code | The unit of price and amount. Differs from the catalog `salesUnit` on about 1 % of lines (A-08) |

Entries have exactly two key sets: `{productId, closingTime, salesBlock, logisticModel, scheduleLines}` or
`{productId, salesBlock, scheduleLines}`. No explicit nulls were ever returned, although the OpenAPI allows them.

### A-03 Cut-off slots and the never-moving delivery date (Observed)

| Slot (`closingTime`) | Who | Lead time to Mon 16.11 | Share |
|---|---|---|---|
| Sun 15.11 17:00 | Stock | Order by 17:00 the day before | About 86 % of Stock lines |
| Fri 13.11 13:00 | Stock (98 % temperature class 8, e.g. 474284, 470434, 460465, 462242) | 3 days | About 14 % of Stock lines. Not predictable from class or vendor: 970 class-8 Stock items close on Sunday |
| Thu 12.11 10:30–16:00 | Terminal, one fixed hour per vendor (HKFOODS uses two) | 4 days | Almost all Terminal |
| Wed 11.11 13:00 | Terminal, RIITAN HERKKU OY TUORE (e.g. 474880, 465987) | 5 days | 8 products seen |
| Tue 10.11 14:00 | Terminal, NAAPURIN MAALAISKANA OY (466869, 464171) | 6 days | 2 products seen |
| Fri 13.11 12:30 / 15:00 | Terminal, sales-blocked seasonal items (December dates) | – | 6 products |

- All closing times are on :00 or :30, offset `+0200`.
- Every Terminal cut-off was already in the past when the challenge run started (Fri 23:05). The API still reports
  `availableDate` 2026-11-16 and amount 999999 for them.
- Orderable for Monday (Stock, amount > 0, not blocked, cut-off in the future), measured on four independent random samples:
  33–37 % at Sat 00:05–01:04. Simulated: about 80 % at Wed 11.11 12:00, 38.9 % at Fri 13.11 12:00, 32.7 % at Sun 16:59,
  **0 % at Sun 17:01** (the latest `closingTime` anywhere is 2026-11-15T17:00:00+0200).
- For a `requestedDate` after Monday the API still returns the Monday slot and its old cut-off, so a strict
  "cut-off passed" rule would wrongly block Terminal items for, say, Fri 20.11 (F-05).

### A-04 Availability shape by logistic model (Observed)

Uniform random sample of 3,000 products: Stock 41.4 %, Terminal 40.9 %, no `logisticModel` 17.7 %. The combination
"has `logisticModel`, has `closingTime`, has lines" is always all three or none. Not-deliverable products span every
temperature class and many vendors (WULFF OY AB 34, VALIO OY TUORE 18, DUNI 17 in one sample). Fresh salmon is a hot spot:
20 of 21 fresh Atlantic salmon fillets have empty lines (only 462150 is orderable).

### A-05 `availableAmount` values (Observed; "untracked" meaning Inferred)

| Case | Rule | Values seen | Share | Meaning |
|---|---|---|---|---|
| Terminal | `logisticModel` = Terminal | Always 999999.0, not scaled by unit (also on 467730 with KI = 400) | about 41 % of products | Quantity unknown (documented) |
| Stock placeholder | amount == floor(9,999,999,999 / `sizeInBaseUnits` of the **API** unit) | 9999999999 (size 1), 3999999999 (461268, KI = 2.5 KG), 1999999999 (460603, SK = 5), 666666666 (463779, KI = 15), 555555555 (461174, KI = 18), 540540540 (460857, KI = 18.5), **49999999 (461440, KI = 200), 39999999 (461294, KI = 250), 35714285 (465056, KI = 280)** | about 20 % of Stock lines | Untracked or unlimited. Smallest possible value is 24,999,999 (KI = 400) |
| Stock real | Any other positive amount | Integers only. Median 42, p10 4, p90 about 423, max seen 68,293 (465215) | about 74 % of Stock lines | Real stock in the API unit; 23 % are 10 or fewer |
| Stock zero | 0.0 | `{"availableAmount":0.0,"salesBlock":false,"salesUnit":"PAK"}`, no `availableDate` | about 6 % of Stock lines | Out of stock; `closingTime` still present |

All 398 placeholders observed matched the formula exactly. A threshold of 1e8 misreads the large-case placeholders above
as real stock; use the exact formula or a threshold of 1,000,000 (F-03).

### A-06 `salesBlock` (Observed)

Blocked products seen across about 4,000 queried ids: Fazer seasonal pastries 463989, 464035, 469355 (laskiaispulla),
470094, 477027 (Runebergintorttu), all Terminal with `availableDate` 2026-12-30 and closing Fri 13.11 12:30; and 467504 Tork
black dinner napkins (2026-12-16, closing Fri 13.11 15:00). About 1 in 2,000 random products is blocked. Top-level and
line-level flags always agree, so a "line blocked only" case cannot be shown with live data and must be simulated.

### A-07 Unknown and malformed ids (Observed)

| Input | `/price` | `/availability` |
|---|---|---|
| `999999`, `000000`, `477546`, `459999`, `abc`, `""`, `"460063 "`, `" 460063"`, `"0460063"`, `"460063.0"`, full-width digits, deposit codes `1`, `2`, `3`, `4`, `147`, `171`, `9708918` | HTTP 200, entry `{"productId":"999999","quantity":1.0,"netPriceFound":false,"error":true}` (id echoed verbatim) | HTTP 200, `{"productId":"999999","salesBlock":false,"scheduleLines":[]}`: the same shape as the real non-deliverable product 460013 |
| A real catalog id | `error: false` in every one of 3,848 distinct ids priced; real non-deliverable products are priced too | Real entry |

Ids are matched exactly, with no trimming or padding. The 17,546 catalog ids fill 460000–477545 with no gaps.

### A-08 API unit differs from the catalog unit (Observed)

About 1.0 % of lines (25 of 2,469 in a uniform sample; 34 of 3,412 overall) report `scheduleLines[].salesUnit` different from
the catalog `salesUnit`. The API unit is always present in `units[]` (34 of 34) and is the base unit in 24 of 34. In all 31
checkable cases, `catalogPrice / comparisonPrice` matches the content of the **API** unit, and the amount is in the API unit too.

| Id | Catalog `salesUnit` | API unit | Evidence (Sat 01:17) |
|---|---|---|---|
| 465244 Arla 5 dl kevytmaito | ST (0.5 L) | KI (6 × 0.5 L) | 6.22 / 2.07 per L = 3.005 L; Terminal 999999 KI |
| 477190 Happy Joe 0,275 l cider | BOT | KI (24 BOT) | 38.56 / 5.84 = 6.60 L; Stock 4 KI |
| 468022 4 × Familia riistakäristys 2,5 kg | KI (4 ST) | ST | 34.60 / 13.84 = 2.5 kg; Stock 109 ST = 27.25 KI |
| 460657 Marli tomaattimehu 1 L | KI | ST | 2.26 / 2.26 = 1.0 L; Stock 112 ST |
| 474747 15 × Marabou 180 g | KI | ST | 3.32 / 18.44 = 0.18 kg; Stock 0 |
| 467042, 460635, 465987, 474449, 468648, 462321, 462242 | ST, BAG or PAK | KI | Price fits the case: e.g. 467042 Seara 75.11 / 7.51 = 10.0 kg |

Direction varies (KI → ST 19, ST → KI 6, KI → BAG 4, BAG → KI 2, others 1 each). `/price` itself has no unit field, so the
availability line is the only place to see the unit.

### A-09 `/price` is a date-independent snapshot (Observed)

- Products arrays were identical for pricing dates from 1900-01-01 to 9999-12-31 and across customers.
- `validFrom` / `validTo` are returned but **not applied**. For 2027-01-01, 49 of 523 targeted entries (e.g. 464306, 464401,
  464119, 463335) still return net prices with `validTo` 2026-12-31. For 2026-01-15, 832 of 1,000 random entries return
  prices whose `validFrom` is later. For 2026-07-15, 464306 still returns 1.01 with `validFrom` 2026-09-01.
- No returned price starts after Sat 14.11 (latest `validFrom` 2026-10-01), so every delivery date from now to 2026-12-31 lies
  inside every returned window.
- Timestamps are Helsinki local midnight with a DST-specific offset: `"validFrom":"2026-09-01T00:00:00+0300"`,
  `"validTo":"2026-12-31T00:00:00+0200"`. Compare them as local dates, not UTC instants. Open-ended prices use `9999-12-31`;
  463658 alone uses `2109-07-31`.

### A-10 `/price` fields (Observed)

Excerpt (464306, Sat 01:16:59):

```json
{"productId":"464306","quantity":1.0,
 "catalogPrice":{"value":1.01,"valueWithTax":1.15,"validFrom":"2026-09-01T00:00:00+0300","validTo":"2026-12-31T00:00:00+0200","currency":"EUR"},
 "comparisonPrice":{"value":1.01,...},"comparisonUnit":"L","tax":{"taxRate":13.5,"taxValue":0.14},
 "listPrice":{"value":1.44,...},"netPriceFound":true,"error":false}
```

| Field | Real behaviour |
|---|---|
| `productId` | Echoed verbatim, padded ids included |
| `quantity` | Always 1.0. A `quantity` field in the request body is ignored; there is no volume pricing |
| `catalogPrice` | Net unit price excl. VAT (`value`) and gross (`valueWithTax`), per **API unit**. Present whenever `error` is false |
| `priceWithTax` | `value` equals `catalogPrice.valueWithTax`. Has no `valueWithTax` field. Same window as `catalogPrice` |
| `listPrice` | Price before customer discount. Its window differs only on net-price entries (the net window is time-boxed, the list window open-ended) |
| `comparisonPrice` + `comparisonUnit` | Price per KG or L only. Both keys absent together (never null) on about 22 % of products: families 63, 64, 20 and 90 mostly, only about 3 % of food |
| `tax` | `taxRate` 13.5, 25.5 or 10. `taxValue` = gross − net exactly |
| `netPriceFound` | True for about 1.1 % of random products (33 of 3,000) |
| `error` | True only for ids outside the catalog; then the entry has only 4 keys |
| Top level | `customerId` echoes the request (even ""), `currency` EUR, `pricingDate` = requested date at Helsinki midnight |

### A-11 Net prices, list prices and discount tiers (Observed)

- **Non-net prices** equal `round_half_up(list × (1 − t), 2)` within 1 cent for t in {20 %, 15 %, 18 %, 0 %}, for 3,768 of 3,768
  checked. Unambiguous counts: 20 % 1,846 · 15 % 1,202 · 18 % 640 · 0 % 6 (e.g. 462395 carbon dioxide 70.75, 465611 NÄYTE 0.01).
  The tier is usually constant per category (7 of 348 categories mix tiers) and tends to follow temperature: chilled about 15 %,
  frozen about 18 %, ambient about 20 %.
- **Customer net prices** (`netPriceFound` true): of the 81 distinct net prices seen, 80 have `validTo` 2026-12-31 (`validFrom`
  mostly 2026-09-01); the exception is 471480 Vaasan Tähtipulla (20.54 vs list 34.66, valid 2024-05-01 to 2032-12-31). In a
  random sample the vendors are mixed (Diversey 17 of 33, Valio 10 of 33). Milk-targeted samples are dominated by Valio
  fresh dairy, including the cheapest lactose-free milks (464306, 464401, 463335, 464073, 464119, 465039).
- Net discount ranges from −0.93 % to 83.8 %. 11 of 80 net prices are more than 50 % off, all Diversey cleaning items (e.g.
  464818 TASKI sponge 6.20 vs 38.22). This is a contract pattern, not an anomaly.
- **Net above list** happens: 462250 (64.99 vs 64.39), 461643 Comfort softener (18.06 vs 14.65), 476972 squeegee (19.41 vs
  13.90), 475702 dishwasher tablets (74.47 vs 59.22, +25.8 %). No non-net price is above list.

### A-12 Tax rates and rounding (Observed)

- Random 3,000: 13.5 % on 2,299 (76.6 %), 25.5 % on 700 (23.3 %), 10 % on 1. The 10 % rate appears only on newspapers
  (462629, 462762, 476525).
- `vatCode` is unreliable in both directions: MEDIUM gives 25.5 % for 3 products (467204, 467157 liqueur ice creams, 469402
  paper cups); STANDARD gives 13.5 % for 6 foods; LOW (1 product) gives 13.5 %, not 10 %; the field is absent on 17.5 %.
  The schema itself names `tax.taxRate` as the source of truth.
- Rounding: `valueWithTax = ROUND_HALF_UP(value × (1 + rate/100), 2)` held for 9,513 of 9,513 non-tie values and 64 of 64 exact
  ties (half-even would match only 33). Example: 476936 11.00 × 1.135 = 12.485 → 12.49.

### A-13 `comparisonPrice` semantics (Observed)

- Per KG (about 80 % of those present) or L. For products in brine or syrup it is per **drained** weight (D-06).
- Rounded to cents, so implied content carries up to about 0.3 % error (464119: 10.015 L).
- Occasionally wrong (476738 about 20× too low, 469955 10× too high), so a ranking by EUR/kg alone can mislead. Cross-check
  with static content (F-01).

### A-14 Request validation (Observed; identical on both endpoints)

| Input | HTTP | Error `type` |
|---|---|---|
| `products: []` | 422 | `too_short` |
| 1,001 ids | 422 | `too_long`; the error body echoes all ids (about 9 KB), so do not log it verbatim |
| `customer` missing, `requestedDate` missing | 422 | `missing` |
| `customer` as number, ids as numbers | 422 | `string_type` (all errors in one response) |
| `"16.11.2026"`, `"2026-13-01"`, `""` | 422 | `date_from_datetime_parsing` |
| `"2026-02-30"`, `"2026-11-31"` | 422 | day value outside expected range |
| `"2026-11-16T10:00:00"` (with or without offset) | 422 | `date_from_datetime_inexact` |
| `"2026-11-16T00:00:00"` | 200 | Accepted |
| Past or extreme dates (`2025-07-01`, `1900-01-01`, `9999-12-31`) | 200 | Accepted. 1900 returns the offset `+013949`, which Node's `Date` cannot parse |
| Truncated JSON | 422 | `json_invalid` |
| Extra fields (`quantity`, `quantities`, `unit`) | 200 | Ignored |
| Duplicate ids | 200 | One entry per occurrence, in request order |

### A-15 Latency, size and headers (Observed)

- Warm: 0.24–0.40 s for any batch size from 1 to 1,000 ids. Cold (first call after a few minutes idle): 0.8–1.2 s, whatever the
  size. Re-check: ping 0.64 s (cold), availability with 206 ids 0.25 s, price with 206 ids 0.35 s.
- Body size about 190 bytes per product for availability and about 650 bytes per product for price, gzip-compressed on request.
- Headers: `cache-control: no-store`, `cf-cache-status: DYNAMIC`, `cf-ray`, `x-robots-tag`, `server: cloudflare`. No
  `RateLimit` or `Retry-After` headers; no CDN caching, so any caching is ours.

### A-16 Timestamp formats (Observed)

`closingTime` and `timeNow` use `2026-11-15T17:00:00+0200` (no colon in the offset). `availableDate` is a plain date. Python
3.13 `datetime.fromisoformat` and `strptime("%Y-%m-%dT%H:%M:%S%z")` parse it; Node 22 and Bun 1.4 `new Date()` parse it too.
Only the pre-1921 offset `+013949` breaks Node.

### A-17 What the API does not give us (Observed)

No order, quote or reservation endpoint; no volume pricing; no unit in `/price`; no deposit prices; no next delivery date after
a missed cut-off; no lead-time or delivery calendar; no customer-specific behaviour; no product images (media ids only).

### A-18 Deposits (Observed)

506 products carry deposits with 7 material codes (1: 160 products, 4: 155, 3: 119, 171: 69, 147: 46, 2: 25, 9708918: 2).
None of the codes is a catalog id and `/price` returns `error: true` for all of them. Examples: 461051 Red Bull 250 ml × 24
(KI, 37.77 EUR, deposit `4` × 24 ST), 477103 Bonaqua 24-pack (deposit `147` × 24), 477039 Dr Pepper (deposits `3` × 24 and
`171` × 1), 462395 carbon dioxide 10 kg (deposit `9708918` × 1). Whether deposits are already included in `catalogPrice` is not
observable (Q-08).

### A-19 curl reproduction

Set the key first: locally `export VALIO_AIMO_API_KEY=<your challenge key>`; in the cloud sandbox
`export VALIO_AIMO_API_KEY=proxy-injected` (the proxy replaces it with the real key). Never commit a real key.

```bash
BASE=https://junction26.valioaimo.fi/api

# Health check: {"status":"ok"}
curl -sS -H "X-API-Key: $VALIO_AIMO_API_KEY" "$BASE/ping"

# Availability for the OpenAPI example ids (four different states, see A-02)
curl -sS -X POST "$BASE/availability" \
  -H "X-API-Key: $VALIO_AIMO_API_KEY" -H 'Content-Type: application/json' \
  -d '{"customer":"123","requestedDate":"2026-11-16","products":["460013","460063","463989","460056"]}' | jq .

# Availability as a table: id, model, cut-off, amount, date, API unit, state at the server's timeNow.
# (String comparison of closingTime and timeNow is only safe because both use +0200; parse them in real code.)
curl -sS -X POST "$BASE/availability" \
  -H "X-API-Key: $VALIO_AIMO_API_KEY" -H 'Content-Type: application/json' \
  -d '{"customer":"123","requestedDate":"2026-11-16","products":["464306","463779","463038","464440","465244","461294","999999"]}' \
| jq -r '.timeNow as $now | .products[] | [.productId, (.logisticModel // "-"), (.closingTime // "-"),
    ((.scheduleLines[0].availableAmount // "-") | tostring), (.scheduleLines[0].availableDate // "-"),
    (.scheduleLines[0].salesUnit // "-"),
    (if (.scheduleLines | length) == 0 then "NO_LINES" elif .closingTime < $now then "CUTOFF_PASSED" else "OPEN" end)] | @tsv'

# Price as a table: id, net, list, netPriceFound, comparison price and unit, VAT %, validTo, implied L or kg per API unit
curl -sS -X POST "$BASE/price" \
  -H "X-API-Key: $VALIO_AIMO_API_KEY" -H 'Content-Type: application/json' \
  -d '{"customer":"123","requestedDate":"2026-11-16","products":["464306","463038","465244","461643","999999"]}' \
| jq -r '.products[] | [.productId, (.catalogPrice.value // "ERROR"), (.listPrice.value // "-"), .netPriceFound,
    (.comparisonPrice.value // "-"), (.comparisonUnit // "-"), (.tax.taxRate // "-"), ((.catalogPrice.validTo // "-")[0:10]),
    (if .comparisonPrice then ((.catalogPrice.value / .comparisonPrice.value * 1000 | round) / 1000) else "-" end)] | @tsv'

# Validation error (HTTP 422, too_short)
curl -sS -X POST "$BASE/price" -H "X-API-Key: $VALIO_AIMO_API_KEY" -H 'Content-Type: application/json' \
  -d '{"customer":"123","requestedDate":"2026-11-16","products":[]}'
```

Expected output at Sat 01:17 for the two tables:

```text
464306  Stock     2026-11-15T17:00:00+0200  9999999999.0  2026-11-16  ST   OPEN
463779  Stock     2026-11-15T17:00:00+0200  666666666.0   2026-11-16  KI   OPEN
463038  Terminal  2026-11-12T15:00:00+0200  999999.0      2026-11-16  KI   CUTOFF_PASSED
464440  -         -                         -             -           -    NO_LINES
465244  Terminal  2026-11-12T15:00:00+0200  999999.0      2026-11-16  KI   CUTOFF_PASSED
461294  Stock     2026-11-15T17:00:00+0200  39999999.0    2026-11-16  KI   OPEN
999999  -         -                         -             -           -    NO_LINES

464306  1.01   1.44   true   1.01  L  13.5  2026-12-31  1
463038  31.31  36.83  false  1.57  L  13.5  9999-12-31  19.943
465244  6.22   7.32   false  2.07  L  13.5  9999-12-31  3.005
461643  18.06  14.65  true   3.61  L  25.5  2026-12-31  5.003
999999  ERROR  -      false  -     -  -     -           -
```

---

## 4. Derived facts and formulas

### F-01 Content per order unit (Recommendation)

```text
api_unit     = availability.scheduleLines[0].salesUnit              (fallback: catalog salesUnit, flagged)
api_content  = catalogPrice.value / comparisonPrice.value            (L or KG per api_unit; None without comparison price)
static       = content_per_base_unit (D-06 steps 1-4) * units[api_unit].sizeInBaseUnits
name_content = parsed from the name ("12 x 1 l", "4x5 kg", "200/150g" -> drained 0.150 kg, "M90" -> 90 eggs)

content = value agreed by at least 2 of {api_content, static, name_content} within 5 %
          if api_content and static agree within 1 %: use static (removes cent rounding: 469119 -> 1.75 L, not 1.748)
          if no two agree, or only one source exists: use the best source, set needsHumanReview = true
```

Examples: 464306 1.0 L/ST · 463038 19.943 L/KI (2 × 10 L) · 469287 21.069 L/KI (12 × 1.75 L) · 463779 3.745 L/KI (15 × 2.5 dl) ·
463233 2.1 kg/KI (portion butter) · 464076 5.0 kg/ST (data says 20 kg; the vote fixes it) · 465244 3.0 L/KI.

### F-02 Units needed and `allowedLotSize` (Observed facts, Recommendation)

- 0.01 on 16,872 products (96.2 %), including every ST, BAG and PAK product and 8,003 of 8,005 KI products. "Multiple of 0.01"
  would accept 571.43 ST of a 1.75 l bottle, so **count units must be whole numbers**.
- Steps above 0.01 exist on 672 KG-sold products and 2 KI products (462952 lot 1.0, 464997 lot 2.0). For KG products the step
  equals the case size for 190 (28 %), one pack for 39 (6 %), and is a plain kg step for 439 (65 %), e.g. 460675 lot 10 =
  KI 10 kg, 463127 HK jauheliha lot 3 = one 3 kg pack, 475594 kirnuvoi lot 0.7 = one 700 g piece. 396 KG products have 0.01.

```text
if api_unit == "KG":
    step = allowedLotSize if allowedLotSize > 0.01 else 0.01
    qty  = ceil(need_kg / step) * step                 # 20 kg of 475594 -> 29 x 0.7 = 20.3 kg
else:
    qty  = ceil(need_amount / content)                  # 1,000 L of 469119 (1.75 L) -> 572 ST
    if allowedLotSize > 1: qty = ceil(qty / allowedLotSize) * allowedLotSize
max_orderable = floor(amount / step) * step             # only when the amount is exact (F-03)
                                                        # 462150: 43 KG, lot 10 -> 40 KG; 462646: 276 KG, lot 5 -> 275 KG
overshoot_pct = (qty * content - need) / need           # report it; offer full-case alternatives (464306: 1,000 ST = 50 KI of 20)
```

Some real Stock amounts are not multiples of their lot (462646, 475592, 475724, 474509, 462682, 462414, 475867), so always round
down. Catch-weight goods (`variableUnit` true, e.g. 460675, 462150) are invoiced by actual weight (Inferred, Q-23).

### F-03 Normalising an availability amount (Recommendation)

```text
TERMINAL     logisticModel == "Terminal"                                   -> qty unknown ("supplier, quantity not confirmed")
ZERO         amount == 0                                                    -> out of stock (no availableDate)
UNTRACKED    amount == floor(9_999_999_999 / sizeInBaseUnits(api_unit))    -> "stock not tracked", never shown as a number
             or amount >= 1_000_000 (safety net; largest real amount seen is 68,293; smallest placeholder 24,999,999)
EXACT        anything else                                                  -> real quantity in api_unit
```

### F-04 Feasibility for a need date (Recommendation)

```text
orderable(entry, line, need_date, now, buffer) =
      entry.scheduleLines non-empty                 else NOT_DELIVERABLE (or UNKNOWN_ID if not in the catalog)
  and not (entry.salesBlock or line.salesBlock)     else SALES_BLOCKED
  and line.availableAmount > 0                      else OUT_OF_STOCK
  and line.availableDate <= need_date               else LATE (days = availableDate - need_date)
  and now < closingTime - buffer                    else CUTOFF_PASSED (or CUTOFF_TOO_CLOSE inside the buffer)
  and (kind != EXACT or qty <= amount)              else PARTIAL
```

`now` defaults to the server `timeNow` and must be injectable (as-of clock) for demos and tests. `buffer` = time a human needs
to approve plus submit time (we suggest 1 h). Approval deadline = `closingTime − buffer`, shown on every approval card.

### F-05 Lead times and estimated next slot (Observed, then Inferred)

Observed lead times to the Monday slot: Stock order by 17:00 the day before (or Fri 13:00 for the Friday group), Terminal
4 days at a vendor-specific hour (5 days Riitan Herkku, 6 days Naapurin Maalaiskana).

- **Need date later than the snapshot's `availableDate`:** the API repeats the Monday answer. Estimate the cut-off as
  `closingTime + (need_date − availableDate)` (constant lead time), label it **estimated**, and require confirmation before
  committing. For Fri 20.11 that gives Terminal Mon 16.11 15:00 and Stock Thu 19.11 17:00.
- **Cut-off missed:** the real next date is not exposed. If we show one, use the same slot one week later (vendor slot + 7
  days), labelled as an estimate. Weekend deliveries are unknown (Q-02).

### F-06 Quote totals and VAT (Observed facts, Recommendation)

```text
line_net   = qty * catalogPrice.value                         (exact cents)
line_vat   = round_half_up(line_net * tax.taxRate / 100, 2)
line_gross = line_net + line_vat
```

Show the API's per-unit gross (`valueWithTax`) for reference. Our convention is VAT per line on the net total until the mentors
answer Q-07, because the two methods differ: 1,000 × 464306 gives 1,010.00 net, 1,146.35 gross with VAT on the line, but
1,150.00 when per-unit gross prices are summed. Deposits go on a separate "not priced, to be confirmed" line (A-18).

### F-07 Price validity (Recommendation)

```text
valid_for_delivery = local_date(validFrom) <= delivery_date <= local_date(validTo)    # Europe/Helsinki dates
                     # treat validTo as inclusive until confirmed (Q-06); validTo 2026-12-31T00:00:00+0200 is local 2026-12-31
quote.expiresAt    = min(closingTime - buffer, end of the validTo day, issuedAt + TTL)
```

If not valid: flag `PRICE_NOT_VALID_FOR_DELIVERY_DATE` and re-quote or escalate. Demo: the same basket for 2027-01-01 (X-16).

### F-08 Discount and price flags (Recommendation)

- `discount = 1 − catalogPrice.value / listPrice.value`. Only `netPriceFound` marks a customer contract price; list is always
  higher for non-net prices, so "list minus x %" is not a signal on its own.
- `NET_ABOVE_LIST` when the net price exceeds list (X-17): show it, require approval, never display a negative discount.
- Deep discounts above 50 % are informational only (systematic for Diversey).

### F-09 Unit price and carbon per order (Recommendation)

- Compare offers per L or kg (`comparisonPrice` or `price / content`), never per sales unit. Mark products without a reliable
  content as "not comparable".
- `co2e_kg = carbon_factor × net_kg`. For liquids use the Synkka net weight per litre when present (464306: 1,025 g per L,
  so 1,000 L ≈ 1,128 kg CO2e) or state the density assumption. Always label the value "category average, not product-specific".

---

## 5. Search

### S-01 Recommended approach (Recommendation, prototype measured)

1. **LLM plans, gateway executes.** The LLM converts the request into structured arguments: Finnish base-form product-type
   heads, exclusions, must-have claims and labels, allergens to exclude, temperature, quantity and need date. The gateway never
   relies on free text alone.
2. **Match the head on the end of Finnish compound words in the `fi` name only.** Index reversed `fi` tokens in a SQLite FTS5
   column; a prefix query on the reversed token is a suffix match (`rev_fi:"otiam"*` finds every name token ending in "maito").
   Use sv and en names only for recall and ranking.
3. **Hard filters in code:** claims, labels, allergens (CONTAINS, optionally MAY_CONTAIN), temperature class, category prefix,
   junk filter (465611 NÄYTE, price 0.01).
4. **Category votes:** count category codes among the filtered hits; offer the dominant codes to narrow a follow-up search
   (codes have no names).
5. **Live data for the shortlist only:** one batched `/price` and one `/availability` call for the top candidates (1–40 ids
   per need is enough), cached per (customer, product, date). This is also what the OpenAPI asks for.

### S-02 Evidence (Observed)

| Query | Naive keyword P@10 | Head match + filters (prototype, in-sample) | Head + claim / temperature filters only (independent re-implementation, precision over all hits) |
|---|---|---|---|
| Lactose-free milk | 0.0 | 1.0 | 26 / 31 |
| Butter | 0.2 | 1.0 | 22 / 37 (peanut butter, cocoa butter, ice cream) |
| Fresh salmon fillet | 0.8 | 1.0 | 21 / 60 (36 rainbow-trout fillets) |
| Gluten-free pasta | 0.7 | 1.0 | 14 / 20 |
| Vegan mince | 0.0 | 1.0 | about 30 / 41 (13 tomato "murska") |
| Lactose-free cream | 0.7 | 1.0 | 12 / 12 |
| Organic eggs | 0.0 | 1.0 | 2 / 2 |

The prototype's P@10 = 1.00 used hand-tuned exclusion lists and self-written relevance judges, so it is an upper bound. Expect
lower precision unless the LLM reliably produces equivalent exclusions; test with LLM-generated arguments. Part of the gap comes
from the claim filters: prefix `maito*` plus `FREE_FROM_LACTOSE` gives 45 hits with only about 10 real milks.

### S-03 Product-type heads and synonyms (Recommendation, from observed names)

| Need | `fi` heads (base form) | sv / en (recall only) | Exclude or flag |
|---|---|---|---|
| Milk | `maito`, `maitojuoma` (Finnish lactose-free milks are mostly "maitojuoma"; the head `maito` alone matches 0 of 15 "kevytmaitojuoma" names) | mjölk, mjölkdryck / milk, milk drink | `kahvimaito` (coffee milk, a variant), `piimä` (buttermilk), `kaakao`, `suklaa`, `latte`, `maitojauhe` (powder), modifier `kookos` |
| Lactose-free | claim `FREE_FROM_LACTOSE` ("laktoositon") | laktosfri / lactose free | Not `LOW_LACTOSE`: "vähälaktoosinen", "HYLA", ERP "VL" |
| Gluten-free | claim `FREE_FROM_GLUTEN` ("gluteeniton", ERP "GTON") | glutenfri / gluten free | Decide policy for oats (`GO`) |
| Cream | `kerma`, `kuohukerma` (whipping), `vispikerma` (whipping, UHT), `ruokakerma` (cooking) | grädde / cream | `jäätelö` |
| Butter | `voi` | smör / butter | Modifiers `maapähkinä`, `kaakao`; terms `voisilmä`, `voitaikina` |
| Eggs | `kananmuna`, `muna`; size code "M90" = 90 eggs | ägg / eggs | `suklaamuna`, `yllätyssuklaamuna`, `munanuudeli`; 475357 is liquid egg (category 10592) |
| Salmon | `lohi`, `lohifilee` | lax / salmon | Modifier `kirjo` (kirjolohi = rainbow trout, same category 18701), `savu`, `graavi` if fresh is wanted |
| Potatoes | `peruna`, `annosperuna`, `yleisperuna` | potatis / potato | Ask for the portion size (portion → kg) |
| Plant-based mince | `jauhis`, `muru`, `murska` + claim `VEGAN` | – | `tomaattimurska`; 466745 MiFU is vegetarian, not vegan |
| Organic | label `EU_ORGANIC_FARMING` (also KRAV, Sun, Soil Association) **or** "luomu" in the name | ekologisk / organic | 49 "luomu" names have no label |
| Finnish | label `GOODS_FROM_FINLAND_BLUE_SWAN` / `MADE_IN_FINLAND_FLAG_WITH_KEY` **or** `countryOfOrigin` fi | – | Treat label and origin as separate preferences |

ERP abbreviations in minimal-record names: GTON gluten-free (10 names), VL low-lactose (8), LAKTON lactose-free (5), **LTN =
luuton, boneless** (3, e.g. 462839 "PORSAAN KYLKI LTN"), n./N. = approximate weight.

### S-04 Pitfalls (Observed)

| Pitfall | Evidence |
|---|---|
| Substring and prefix matches hit other products | Substring "maito" is in 233 fi names, 63 of them "maitosuklaa" (milk chocolate). "laktoositon maito" as keywords matches 914–3,882 products depending on fields; the top 10 were ice creams, 466215 "Brunberg laktoositon maitosuklaa" and cakes |
| Modifiers inside compounds change the product | Of fi tokens ending in "lohifilee" (76), 36 are kirjolohifilee; "voi" (38) includes maapähkinävoi × 7 and kaakaovoi; "murska" (26) includes tomaattimurska × 13; "muna" (26) includes suklaamuna × 4 |
| Other languages give wrong endings | en "buttermilk" ends in "milk"; sv "pasta" means paste (460923 KNORR kryddpasta); en "Salmon steak" for rainbow trout (466146); "lax" hits "relaxing" (461372); sv "färs" vs "färsk" |
| Inflected words find nothing | fi names: "maitoa" 0, "maidon" 0, "kananmunia" 0, "perunoita" 0. The LLM must send base forms |
| Short prefixes explode | Prefix "voi" matches about 3,120 products (Viher Voima, voisilmäpulla, voitaikina). Require whole-word matches for terms under 5 characters |
| Brand is not a claim | Eila is Valio's lactose-free brand, but 460032 "Valio Eila vähälaktoosinen maitojauhe" is `LOW_LACTOSE` |
| Name and claim disagree | 17 "laktoositon" names lack the claim; 462234 "vähälaktoosinen" carries `FREE_FROM_LACTOSE`. Claims win; flag the disagreement |
| Lookalikes for "milk" | Coffee milk 464237 and 462626, vanilla coffee-milk drink 473142, latte 469266, piimä 477050 and 476957, portion cups 463203, plant-fat blend 462703 "Arla Ruoka ... maitopohjainen kasvirasvasekoite" |

### S-05 Diet and label semantics, implemented in code (Recommendation)

Three-valued logic: **yes / no / unknown**. A constraint is satisfied only by an explicit code; unknown goes to a human.

| Requirement | Satisfied when | Hard block when | Otherwise |
|---|---|---|---|
| Lactose-free | Claim `FREE_FROM_LACTOSE` | Only `LOW_LACTOSE` and no `FREE_FROM_LACTOSE` | Unknown → approval. Claim plus `LACS` > 0.01 g/100 g (23 products) → flag. Never use `AM` CONTAINS as a conflict |
| Milk-free (milk allergy) | nonAllergen `AM` FREE_FROM, or `VEGAN` with neither `AM` nor `ML` declared | `AM` or `ML` CONTAINS (all lactose-free milks have `AM`) | Unknown → approval |
| Gluten-free | Claim `FREE_FROM_GLUTEN` | `UW`/`AW`/`GB`/`NR` CONTAINS on a substitute; warn on MAY_CONTAIN | Oats (`GO`) by explicit policy |
| Vegan / plant-based | Claim `VEGAN` | – | `VEGETARIAN` only is not enough (466745) |
| Organic | Organic label or "luomu"/"organic" in the name | – | – |
| Allergen X excluded | X not in CONTAINS (and not MAY_CONTAIN if strict) and data declared | X CONTAINS | No allergen data (all minimal records) → unknown. Treat `UW`/`GB`/`NR` CONTAINS as implying `AW` |

### S-06 Proposed tool signature (Recommendation)

```ts
search_products(args: {
  product_types: string[];          // Finnish base-form compound heads, e.g. ["maito", "maitojuoma"]
  query?: string;                   // optional free text (fi/sv/en) for recall and ranking, e.g. "barista"
  exclude_terms?: string[];         // whole words or prefixes (>= 5 chars), e.g. ["kahvimaito", "piimä", "kaakao", "latte"]
  exclude_modifiers?: string[];     // compound modifiers that change the product, e.g. ["kirjo", "maapähkinä", "tomaatti"]
  must_claims?: ClaimCode[];        // e.g. ["FREE_FROM_LACTOSE"]; LOW_LACTOSE never satisfies FREE_FROM_LACTOSE
  must_not_claims?: ClaimCode[];
  labels_any?: LabelCode[];         // exact GS1 ids, e.g. ["EU_ORGANIC_FARMING"]
  organic?: boolean;                // label OR "luomu" in the name
  origin_country?: string;          // ISO alpha-2, e.g. "fi"
  exclude_allergens?: AllergenCode[]; // GS1 codes, e.g. ["AM", "AW"]
  strict_may_contain?: boolean;     // also exclude MAY_CONTAIN
  temperature?: "chilled" | "frozen" | "ambient";   // inferred from temperatureCondition; null code = unknown, kept
  category_prefix?: string[];       // e.g. ["104"]; from category_votes of an earlier call
  quantity?: { amount: number; unit: "L" | "KG" | "PCS" };
  delivery_date?: string;           // YYYY-MM-DD; adds live price + availability for the top results
  limit?: number;                   // default 10, max 50
}): {
  interpretation: { fts_match: string; filters: object; dropped: Record<string, number>; category_votes: [string, number][] };
  results: Array<{
    id: string; name: { fi: string; en?: string }; brand?: string; vendor: string; category: string;
    sales_unit: string; content_per_unit?: { value: number; unit: "L" | "KG" | "PCS"; source: string; confidence: string };
    claims: string[]; labels: string[];
    allergens: { contains: string[]; may_contain: string[]; free_from: string[]; declared: boolean };
    offer?: Offer;                  // normalised price + availability (F-01..F-04), only with delivery_date
    why: string[]; warnings: string[];  // e.g. "minimal record: allergens unknown", "unit mismatch"
  }>;
}
```

### S-07 Performance (Observed)

SQLite 3.53.1 with FTS5 is built into the Python standard library here; no extra dependencies. A minimal index (fi/sv/en names
plus reversed fi tokens) over all 17,546 products builds in 0.3 s (6.3 MB) with suffix queries at 0.06–0.16 ms (p50). The
fuller prototype with pack-size derivation built in about 6–7 s into 52.7 MB, with filtered searches at 1.3–21 ms p50 (not
re-measured, U-15). A Node gateway can use `better-sqlite3` with the same schema. Embeddings are not needed for the MVP (U-04).

---

## 6. Ranking signals and good-better-best

The ranking was prototyped on 10 scenarios against live data. Verifier corrections are already applied below.

### R-01 Hard gates (never traded off)

1. The product matches the need: product type plus must-have claims and labels, evaluated with S-05. "Unknown" can only pass
   with human approval.
2. An explicit contradiction is a hard block that the agent cannot approve (for example a gluten-free need and `AW` CONTAINS).
3. Priced: `error` false and `catalogPrice` present.
4. Feasible for the need date (F-04), or explicitly marked LATE or CUTOFF_PASSED for escalation.
5. The need quantity converts to the API unit (F-01, F-02).

### R-02 Signals (each scaled 0..1)

| Signal | Formula | Missing data |
|---|---|---|
| price | min(EUR per L or kg over valid offers) / own EUR per L or kg | Per sales unit only when every offer shares the unit; otherwise "not comparable" |
| delivery | 1.0 on time with cut-off ≥ 6 h away · 0.8 on time but < 6 h · 0.5^days_late · 0.15 if the cut-off has passed | – |
| availability | 1.0 exact Stock covering the need · 0.95 untracked Stock · 0.75 Terminal · 0.9 × coverage for partial Stock | – |
| reliability | `deliveryReliability` | Do **not** impute the category median: it gives exactly 1.0 to 63.6 % of products without data. Shrink towards the global mean 0.972, cap estimates at 0.97 and label them "estimated" |
| preference | Share of soft preferences met (labels, claims, origin, brand) | Unknown counts as not met |
| carbon | min(carbon factor) / own carbon factor | 0.5 if unknown while others are known; 1.0 for all if nobody has a value |

### R-03 On-time-in-full confidence and bands

`OTIF = delivery × availability × reliability`. Band **A** ≥ 0.85, **B** 0.60–0.85, **C** < 0.60. For needs with a date the rank
key starts with the band, so an on-time option always beats a cheaper risky one, and anything below band A needs approval.

### R-04 Weights and rank key

`score = 0.35·price + 0.20·delivery + 0.15·availability + 0.15·reliability + 0.10·preference + 0.05·carbon` (balanced default).
Profiles: cost_saver (0.55 / 0.15 / 0.10 / 0.10 / 0.05 / 0.05), safe_delivery (0.20 / 0.30 / 0.25 / 0.20 / 0.05 / 0),
green (0.25 / 0.15 / 0.10 / 0.10 / 0.15 / 0.25).
Rank key: band → score (desc) → OTIF (desc) → order total (asc) → reliability from history before estimated → carbon (asc) →
Stock before Terminal → fewer handling units → product id (determinism).

### R-05 Good-better-best selection

- **BEST** = rank 1.
- **BETTER** and **GOOD** = the next ranked offers that are a real alternative to every pick so far: another vendor, another
  logistic model, pack content differing by more than 10 %, or unit price differing by more than 5 %.
- Role tags: "lowest price", "safest delivery", "lowest carbon" (only when values differ), "meets all preferences".
- Add a note when a preferred option exists but ranked low, e.g. "EU organic 462921 is not offered: supplier cut-off Thu 12.11
  15:00 has passed".
- Split plan: when rank 1 is exact Stock that does not cover the need, fill greedily down the ranking. Exact Stock lines are
  firm, Terminal lines unconfirmed; report any uncovered rest.

### R-06 Explanation strings

Emit two forms per offer: structured JSON (scores, weighted contributions, OTIF, band, flags, approval reasons, deadline) for
other agents, and a sentence for humans. Template:

```text
{TIER} ({tags}): {name} [{id}], {vendor}. {n} × {unit} = {qty} {L|kg}, EUR {net} excl. VAT (EUR {gross} incl. {vat} % VAT),
{eur_per_unit} EUR/{L|kg}{, customer price valid to {validTo}}. Delivery {date}: {from stock, n available | from stock, quantity
not tracked | direct from supplier, quantity not confirmed}; order by {cut-off} ({h} h left). Delivery reliability {dr}
({product history | estimated}). Carbon about {cf} kg CO2e/kg (category average), about {co2} kg CO2e. {Why first | Trade-off vs
BEST}. {Warnings}. {Needs approval: reasons. Approve before {deadline} | Within the auto-approval policy}.
```

Examples with live numbers are in W-05.

### R-07 Approval triggers (per-buyer policy, Recommendation)

| Trigger | Action |
|---|---|
| Order total above the buyer's limit (example: EUR 500, an assumption, not from the brief) | Approval |
| Any substitution, split or partial delivery | Approval |
| LATE, CUTOFF_PASSED or CUTOFF_TOO_CLOSE | Approval with a deadline, or escalate |
| Band B or C, or `deliveryReliability` < 0.80 | Approval |
| Terminal quantity (unconfirmed) above a configurable value | Approval or supplier confirmation |
| Unit mismatch without an agreed conversion, or content conflict (F-01) | Approval |
| `NET_ABOVE_LIST`, price `validTo` before delivery, `error: true`, unpriced deposits | Approval |
| Substitute more than 10–20 % dearer per kg or L, or drops a preferred label | Approval |
| Diet or allergen constraint unknown (no data, minimal record) | Approval |
| Explicit allergen or claim contradiction | Hard block (not approvable by the agent) |

Evaluate the policy per requisition, not per order line, so a 1,000 L need cannot be split into orders below the limit.

---

## 7. Worked example: 1,000 L lactose-free milk by Monday

### W-01 Interpretation

- Need: 1,000 L, claim `FREE_FROM_LACTOSE`, product type `maito` or `maitojuoma`, need date Mon 2026-11-16.
- Exclusions: piimä (469331, 472492, 476957, 477050), latte (469266), vanilla coffee-milk drink (473142), low-lactose items
  (463047, 469541, 475534, 469457), powders (460032). Coffee milk (464237, 462626), Cafè milk (463380) and portion cups (463203)
  are kept as **variants** that need the buyer's consent.
- Category 10400 has 35 `FREE_FROM_LACTOSE` products; after exclusions 29 genuine options remain (25 plain, 4 variants).
- Ambiguity worth one clarifying question (or a stated assumption on the approval card): "maitojuoma" (milk drink, e.g. Eila)
  versus "maito"; fat level (skimmed, semi-skimmed, whole).

### W-02 API calls

Two calls: one `/availability` and one `/price` with the candidate ids (well within the 1,000-id limit). Re-checked at Sat 01:17.

### W-03 Options table (live, Sat 01:17; EUR excl. VAT)

| # | Id | Product (fi, shortened) | Unit | L / unit | EUR / unit | EUR / L | Units for 1,000 L | Total EUR | Monday status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 464306 | Valio Arki Eila kevytmaitojuoma 1 l | ST | 1 | 1.01 net | 1.01 | 1,000 | 1,010.00 | Open, full (Stock, untracked) |
| 2 | 464401 | Valio Arki Eila rasvaton maitojuoma 1 l | ST | 1 | 1.10 net | 1.10 | 1,000 | 1,100.00 | Open, full (Stock, untracked) |
| 3 | 464237 | Valio kahvimaito 1 l UHT *(variant: coffee milk)* | ST | 1 | 1.30 net | 1.30 | 1,000 | 1,300.00 | Open, full (Stock, untracked) |
| 4 | 463335 | Valio Eila 3 % maitojuoma 1 l | ST | 1 | 1.40 net | 1.40 | 1,000 | 1,400.00 | Open, full (Stock, untracked) |
| 5 | 464201 | Valio kevytmaito 1 l UHT | ST | 1 | 1.56 | 1.56 | 1,000 | 1,560.00 | Open, full (Stock, untracked) |
| 6 | 464073 | Valio täysmaito 1 l UHT | ST | 1 | 1.64 net | 1.64 | 1,000 | 1,640.00 | Open, full (Stock, untracked) |
| 7 | 464398 | Valio Eila kevytmaitojuoma 1 l UHT | ST | 1 | 1.65 net | 1.65 | 1,000 | 1,650.00 | Open, full (Stock, untracked) |
| 8 | 463779 | Valio Eila kevytmaitojuoma 2,5 dl UHT | KI | 3.75 | 10.71 | 2.86 | 267 | 2,859.57 | Open, full (Stock 666666666 KI = untracked) |
| 9 | 469363 | Arla Kevytmaitojuoma 1 L UHT | ST | 1 | 2.48 | 2.48 | 1,000 | 2,480.00 | Open, **partial: 384 ST** |
| 10 | 462775 | Arla Maitojuoma 1 L rasvaton UHT | ST | 1 | 2.57 | 2.57 | 1,000 | 2,570.00 | Open, **partial: 51 ST** |
| 11 | 463380 | Arla Cafè maito 1 L UHT *(variant)* | ST | 1 | 2.65 | 2.65 | 1,000 | 2,650.00 | Open, **partial: 698 ST** |
| 12 | 463203 | Arla Annosmaito 100 × 2 cl *(variant: portion cups)* | KI | 2 | 15.09 | 7.55 | 500 | 7,545.00 | Open, **partial: 192 KI = 384 L** |
| 13 | 469119 | Valio Eila rasvaton maitojuoma 1,75 l | ST | 1.75 | 2.08 | 1.19 | 572 | 1,189.76 | Cut-off passed (Thu 12.11 15:00) |
| 14 | 469287 | Valio Eila kevytmaitojuoma 1,75 l | KI | 21 | 27.39 | 1.30 | 48 | 1,314.72 | Cut-off passed |
| 15 | 464119 | Valio rasvaton maito 1 l UHT | KI | 10 | 13.32 net | 1.33 | 100 | 1,332.00 | Cut-off passed |
| 16 | 465039 | Valio Eila kevytmaitojuoma 1 l | KI | 5 | 6.86 net | 1.37 | 200 | 1,372.00 | Cut-off passed |
| 17 | 476240 | Valio Eila rasvaton maitojuoma 1 l | KI | 5 | 7.62 | 1.52 | 200 | 1,524.00 | Cut-off passed |
| 18 | 463038 | Valio Eila kevytmaitojuoma 10 l novobox | KI | 20 | 31.31 | 1.57 | 50 | 1,565.50 | Cut-off passed |
| 19 | 469330 | 5 × Arla 1 L kevytmaitojuoma | KI | 5 | 8.54 | 1.71 | 200 | 1,708.00 | Cut-off passed |
| 20 | 469386 | 5 × Arla rasvaton maitojuoma 1 L | KI | 5 | 8.64 | 1.73 | 200 | 1,728.00 | Cut-off passed |
| 21 | 466288 | Valio kevytmaito 2,5 dl UHT | KI | 3.75 | 7.65 net | 2.04 | 267 | 2,042.55 | Cut-off passed |
| 22 | 462921 | Valio Eila Luomu kevytmaitojuoma 1 l *(organic)* | KI | 5 | 10.97 | 2.19 | 200 | 2,194.00 | Cut-off passed |
| 23 | 464198 | Valio Eila kevytmaitojuoma 5 dl | KI | 2.5 | 5.51 | 2.20 | 400 | 2,204.00 | Cut-off passed |
| 24 | 464768 | 12 × Arla Täysmaitojuoma 1 L UHT | KI | 12 | 30.42 | 2.54 | 84 | 2,555.28 | Cut-off passed |
| 25 | 465149 | 6 × Arla 5 dl kevytmaitojuoma | KI | 3 | 7.74 | 2.58 | 334 | 2,585.16 | Cut-off passed |
| 26 | 462626 | Valio kahvimaito 5 dl *(variant)* | KI | 5 | 13.00 | 2.60 | 200 | 2,600.00 | Cut-off passed |
| 27 | 464179 | Arla 10 L Novobox kevytmaitojuoma | ST | 10 | 27.22 | 2.72 | 100 | 2,722.00 | Cut-off passed |
| 28 | 464399 | 14 × Arla Kevytmaitojuoma 2 dl UHT | KI | 2.8 | 10.44 | 3.73 | 358 | 3,737.52 | Cut-off passed |
| 29 | 464440 | Valio kevytmaito 0,5 l UHT | ST | 0.5 | 0.88 | 1.76 | 2,000 | 1,760.00 | Not deliverable (empty `scheduleLines`) |

Notes: all Stock rows close Sun 15.11 17:00 (39.7 h after 01:17); every Terminal row closed Thu 12.11 15:00 and still shows
`availableDate` 2026-11-16 with 999999. Litres per unit match `catalogPrice / comparisonPrice` within 0.4 % for all 29. All have
`allowedLotSize` 0.01, so quantities are rounded up to whole units. Every option is VAT 13.5 % and carbon factor 1.1.
14 of the 29 have no delivery-reliability value; 464306 has 1.0. The cheapest Terminal options (469119 at 1.19, 469287 at 1.30,
464119 at 1.33 EUR/L) would rank 3rd to 6th by price, but all are past their cut-off: an agent that reads only `availableDate`
would offer undeliverable options.

### W-04 Plans, including a split proposal

| Plan | Lines | Litres | Net EUR | Gross EUR (VAT per line) | Approval triggers (example policy) |
|---|---|---|---|---|---|
| **A, recommended** | 1,000 × 464306 (= 50 KI of 20) | 1,000 | **1,010.00** | 1,146.35 (1,150.00 if per-unit gross is summed) | Order value > EUR 500; stock untracked (shown, not blocking); approve before Sun 15.11 16:00 |
| A2, plain "maito" only | 1,000 × 464201 | 1,000 | 1,560.00 | 1,770.60 | Order value |
| B, known stock only (or Arla only) | 384 × 469363 + 51 × 462775 | 435 | 1,083.39 | 1,229.64 | Order value, **partial: 565 L short**, split → escalate |
| C, split to full quantity | B + 565 × 463380 (Cafè milk, variant) | 1,000 | 2,580.64 | 2,929.02 | Order value, split, variant outside stated preference |

Fallback chain if 464306 fails at submit time (its own substitution rules): 465039 (Terminal, cut-off passed, not usable),
464398 (Stock, untracked, 1.65), 469363 (Stock 384, real), 464201 (Stock, untracked, 1.56).

### W-05 Explanation strings with live numbers

```text
BEST (lowest price, meets all must-haves): Valio Hyvä suomalainen Arki Eila kevytmaitojuoma 1 l laktoositon [464306],
VALIO OY TUORE. 1,000 × ST = 1,000 L, EUR 1,010.00 excl. VAT (EUR 1,146.35 incl. 13.5 % VAT), 1.01 EUR/L, customer price
valid to 31.12.2026. Delivery Mon 16.11 from Valio Aimo stock, quantity not tracked; order by Sun 15.11 17:00 (39.7 h left).
Delivery reliability 1.00 (product history). Carbon about 1.1 kg CO2e/kg (category average), about 1,130 kg CO2e.
Why first: cheapest of the 8 options that can deliver the full 1,000 L on Monday. Needs approval: order value EUR 1,010.00
is above the EUR 500 auto-approval limit. Approve before Sun 15.11 16:00.

BETTER (skimmed alternative): Valio Hyvä suomalainen Arki Eila rasvaton maitojuoma 1 l laktoositon [464401]. EUR 1,100.00
excl. VAT, 1.10 EUR/L (+EUR 90.00 vs BEST). Same stock status, cut-off and reliability.

GOOD (whole-milk alternative): Valio Eila 3 % maitojuoma 1 l laktoositon [463335]. EUR 1,400.00 excl. VAT, 1.40 EUR/L
(+EUR 390.00 vs BEST). If coffee milk is acceptable, 464237 Valio kahvimaito 1 l laktoositon (1.30 EUR/L) ranks here instead.

Not offered: Valio Eila 10 l novobox [463038] 1.57 EUR/L and EU-organic Valio Eila Luomu [462921] 2.19 EUR/L. Their supplier
cut-off (Thu 12.11 15:00) has passed, even though the system still shows Monday.
```

### W-06 Timing sensitivity (Observed data, derived classification)

- **Before Sun 15.11 16:00** (with a 1 h buffer): plan A is feasible.
- **Sun 15.11 17:01 and later:** every option is past its cut-off while the API still says Monday. With a strict rule the agent
  must escalate ("Monday no longer possible; earliest estimated date ..."). Demo with an injectable clock (G-12).
- **Need date "by Sunday" (2026-11-15):** every option is one day LATE (same API answer), so the agent escalates.
- **Need date after Monday:** the API repeats the Monday answer; use the estimated cut-off rule (F-05).

### W-07 Variants of the same request

- **Milk allergy instead of lactose intolerance:** all 29 options declare `AM` (milk). Switch to plant drinks: 468465 Oddlygood
  kaurajuoma 1 l gluten-free (1.17 EUR/L net, Stock untracked; contains oats `GO`), 474864 Oddlygood soijajuoma (1.44 EUR/L,
  Stock untracked; soy `AY`), 464013 Alpro No Sugars (2.01 EUR/L, Stock 478 ST). Carbon factor 0.435 (468465, 464013) against
  1.1 for milk.
- **"Prefer organic":** the only organic option, 462921, is past its cut-off, so say so and ask whether non-organic is acceptable.

---

## 8. Exception catalogue and demo fixtures

All rows were observed live (the final re-check was at Sat 01:17) unless marked as simulated or inferred. Requested date is
2026-11-16 unless stated. Behaviour is identical for any requested date (A-01).

| Id | Scenario | Product ids | Req. date | Observed behaviour | Expected agent behaviour |
|---|---|---|---|---|---|
| X-01 | Terminal cut-off passed, API still promises Monday | 463038, 469119, 464119, 465039 | 11-16 | Terminal, 999999, `availableDate` 2026-11-16, `closingTime` 2026-11-12T15:00 (passed) | CUTOFF_PASSED; offer an open Stock option (464306); next date unknown → human |
| X-02 | Stock with the Friday cut-off already passed | 474284 (83 KI), 468693 (1 KI), 466392 (3 KI), 462242 | 11-16 | Stock, `closingTime` 2026-11-13T13:00 | Treat like X-01; 466392 has an open substitute 476848 (Stock untracked, Sun cut-off, 55.25 vs 192.05 EUR/kg, but drops VEGAN) |
| X-03 | Early supplier cut-off (6 days) | 466869, 464171 | 11-16 | Terminal, `closingTime` 2026-11-10T14:00 | Read cut-offs per product; never assume one lead time |
| X-04 | Need date before Monday ("by Sunday") | 464306, 464401, 463335 | 11-15 | Same answer: `availableDate` 2026-11-16 | LATE by 1 day → escalate |
| X-05 | Need date after Monday | 463038 (Terminal), 464306 (Stock) | 11-20 | Same answer, including the Thu 12.11 cut-off | Do not block on the stale cut-off; estimate (F-05), confirm with a human |
| X-06 | Clock passes Sun 15.11 17:00 (Inferred) | 464306 | 11-16 | Every `closingTime` ≤ 2026-11-15T17:00, so all are past | Demo with an as-of clock; record fixtures before Sunday 17:00 |
| X-07 | Cannot be delivered on any date, yet priced | 464440, 460013, 461903, 470789 | 11-16 | `{"productId":"464440","salesBlock":false,"scheduleLines":[]}`; price 0.88 | NOT_DELIVERABLE → substitute or similar search |
| X-08 | Sales block with a far-future date | 463989, 464035, 469355, 470094, 477027 (2026-12-30); 467504 (2026-12-16) | 11-16 | `salesBlock` true at both levels, Terminal 999999, closing Fri 13.11 | SALES_BLOCKED; offer pre-order only if mentors confirm (Q-22) |
| X-09 | Out of stock | 461098, 473463, 469290, 474747 | 11-16 | Stock 0.0, no `availableDate` | OUT_OF_STOCK → substitute |
| X-10 | Partial stock → split | 469363 (384 ST), 462775 (51), 463380 (698), 469346 (48 ST vs 50 L cream) | 11-16 | Real Stock below the need | Split or substitute, with approval (W-04 plan B/C) |
| X-11 | Almost no stock | 460509 Alpro (1 ST), 470699 (1 ST), 468693 (1 KI) | 11-16 | Real Stock 1 | Partial; do not round up beyond stock |
| X-12 | Untracked placeholder amounts | 464306 (9999999999 ST), 463779 (666666666 KI), 461294 (39999999 KI) | 11-16 | Placeholder values (A-05) | Show "stock not tracked"; never as a number. Do not use a 1e8 threshold |
| X-13 | Lot size caps the orderable amount | 462150 (43 KG, lot 10), 462646 (276 KG, lot 5) | 11-16 | Exact Stock not a multiple of the lot | Max 40 kg and 275 kg; rest needs another product |
| X-14 | API unit differs from the catalog unit | 465244 (ST → KI), 477190 (BOT → KI, Stock 4 KI), 468022 (KI → ST, 109 ST), 460657 (KI → ST, 112 ST) | 11-16 | Price and amount per API unit | Convert via `units[]`; flag UNIT_MISMATCH |
| X-15 | Catch weight, frozen, past cut-off | 460675 Snellman flank steak (KG, lot 10, code 7) | 11-16 | 29.17 EUR/KG, Terminal, closing Thu 12.11 13:00 | Weight-based invoice warning; cut-off passed |
| X-16 | Contract price expired for the delivery date | 464306, 463335, 464119 | 2027-01-04 | Same 1.01 / 1.40 / 13.32 returned with `validTo` 2026-12-31 | PRICE_NOT_VALID_FOR_DELIVERY_DATE → re-quote or escalate |
| X-17 | Net price above list | 461643 (18.06 vs 14.65, Stock 15), 476972 (19.41 vs 13.90), 462250, 475702 | 11-16 | `netPriceFound` true, catalog > list | NET_ABOVE_LIST → approval |
| X-18 | Very deep contract discount | 464818 TASKI (6.20 vs 38.22, −83.8 %) | 11-16 | Systematic for Diversey | Informational only |
| X-19 | Deposit cannot be priced | 461051 Red Bull (deposit `4` × 24); ids `4`, `147` | 11-16 | `error: true` for the material ids | Show "deposit not included, to be confirmed" |
| X-20 | Unknown or malformed id | `999999`, `"460063 "`, `477546`, `abc` | 11-16 | Price `error: true`; availability looks like X-07 | Validate before calling; UNKNOWN_ID |
| X-21 | Pack size missing from the name | 463233 Valio voi 10 g (KI), 463197 voi 6 g | 11-16 | 2.1 kg and 1.68 kg per KI | Use API content; name-only would under-order about 200× |
| X-22 | Drained weight | 464940 Abba tonnikala 200/150g, 463519 Viipalekurkku 8,2/4,5kg | 11-16 | 0.150 kg and 4.497 kg per unit | Compare per drained kg; say so |
| X-23 | Sources disagree on content | 476738 (comparison price × 20 off), 469955 (× 10), 464076 (data 20 kg, price 5 kg per ST) | 11-16 | See D-06 | 2-of-3 vote; otherwise human |
| X-24 | Low-lactose is not lactose-free | 463047 (Stock 132 ST, `LOW_LACTOSE`), 469541, 460032 | 11-16 | `LOW_LACTOSE`, `LACS` 1.0 | Exclude for a lactose-free need |
| X-25 | Lactose-free is not milk-free | 464306 (`AM` CONTAINS) vs 468465 (oats), 474864 (soy) | 11-16 | – | For milk allergy offer plant drinks (W-07) |
| X-26 | Listed substitutes break lactose-free | 466375 → 466151 (3,710 BAG), 468526, 475908 (no claim); 473986 (lactose-free, not deliverable) | 11-16 | 466375 itself is Stock 11,603 BAG | Block the three; search sibling category 10603: 465174, 465256 (Stock untracked), 463383 (4,318 BAG) |
| X-27 | Listed substitute breaks gluten-free | 468465 → 470863 (`AW`, `GO`); 469288 → 470341; 473609 → 464320 | 11-16 | Substitutes in Stock but contain gluten cereals | Hard block |
| X-28 | Safe rescue by a substitute | 460025 (no lines, 1.73 EUR/kg) → 460150 (Stock 1,976 KG, 1.12); 471205 → 473629 | 11-16 | Same category, no allergen change | Propose with approval (any substitution) |
| X-29 | Substitute is unavailable too | 469556 → 469401 (cut-off passed); 464201 → 464440 (no lines); 469290 → 465233 (no lines) | 11-16 | Dead ends | Similarity search, then human |
| X-30 | Substitute much dearer | 470961 → 460603 potatoes (0.65 → 3.62 EUR/kg, +457 %); 460211 → 467530 / 467549 (+269 %) | 11-16 | Both in Stock | Price guardrail → approval |
| X-31 | Substitute drops labels | 464322 (EU organic + Fairtrade, Stock 585 KI) → 470153 (Rainforest Alliance only, Stock 40 KI) | 11-16 | 104.52 vs 98.27 per KI | Approval: preference lost |
| X-32 | Every option unreliable | 463059 (DR 0.354, Stock 129 KG), 463053 (0.524, 36 KG, lot 1.5), 466152 (0.611, Terminal past cut-off), 473463 (0.332, Stock 0) | 11-16 | 463451 has DR 1.0 but its Terminal cut-off passed | Band C → escalate; 300 kg needs a split |
| X-33 | Self-substitution | 471661 | 11-16 | Rule points to itself | Ignore the rule |

Not observable live, so simulate in the demo harness: a line-level-only `salesBlock`, a price `error` on a real catalog product,
an API timeout or 5xx, and a price change between quote and order.

---

## 9. Design implications for the agent gateway

What the mock does not provide and we must build. The judging criteria this serves are in brackets.

| Id | Build | Why (evidence) | Minimum for the demo |
|---|---|---|---|
| G-01 | Catalog ETL and normalised product model | D-02..D-13: raw Synkka is large, coded and inconsistent | One Python pass over `products.json` into SQLite; compact records (names, unit, content + source + confidence, claims, labels, allergens with `declared`, temperature class, origin, signals, substitutes, data-quality warnings). Never put raw `synkkaData` into the LLM context [need matching] |
| G-02 | Catalog search tool | S-01..S-06 | FTS5 reversed-token index + hard filters + category votes [need matching] |
| G-03 | Quantity planner and unit converter | A-08, F-01, F-02 | A deterministic tool returns units, rounding, overshoot and warnings; the LLM never does the arithmetic [need matching, robustness] |
| G-04 | Offer normaliser and feasibility engine | A-01..A-06, F-03..F-05 | One typed offer per line: `{unit, qtyKind, qty, availableDate, orderBy, cutoffPassed, blocked, price, validity, flags}`; `asOf` clock parameter [robustness] |
| G-05 | Quote service with fixed prices and validity | A-09..A-12, F-06, F-07 | Quote id, lines, totals, rounding rule, `expiresAt = min(cut-off − buffer, validTo day end, issuedAt + TTL)`, SHA-256 of the raw API responses, signed (JWS over canonical JSON) [inquiry → order with fixed prices] |
| G-06 | Order placement mock | A-17 (no order endpoint) | Order document aligned with an open order format (e.g. UBL / PEPPOL BIS Order fields); re-check price and availability just before submit; idempotency key; order status [E2E demo, openness] |
| G-07 | Policy engine (buyer mandate) and approvals | R-07 | Per-buyer limits and rules; approval cards with reasons and a decide-by time (`closingTime − buffer`); auto-expiry; requisition-level aggregation [autonomy and controls] |
| G-08 | Substitution engine | D-12, X-26..X-33 | Rules from `substitutions[]` as candidates, plus similarity search (same 3-digit category, same claims, comparable content); every candidate re-checked with S-05, F-01..F-04 and the price guardrail [exceptions] |
| G-09 | Audit trail | All | Append-only log: request, interpretation, tool calls, raw response hashes, `timeNow`, decisions, approver and time [trust, openness] |
| G-10 | API client hygiene | A-07, A-14, A-15 | Validate and normalise ids (6 digits, in catalog, trimmed, deduplicated); ≤ 1,000 ids per call; sequential calls; TTL cache keyed by (customer, product, date); 5 s timeout and backoff on 429/5xx; `GET /ping` warm-up before a live demo |
| G-11 | Agent-facing interface on open standards | Challenge brief | MCP server and OpenAPI with tools such as `search_products`, `get_product` (JSON-LD), `plan_quantity`, `quote`, `propose_order`, `request_approval`, `approve`/`reject`, `place_order`, `get_order`. Products as schema.org `Product` plus GS1 Web Vocabulary terms for allergens and labels; units as UN/ECE codes (D-05) with the raw code kept; ISO 8601 times with explicit Europe/Helsinki handling [openness] |
| G-12 | Demo harness | A-01, X-06 | Recorded fixtures of the snapshot, an as-of clock (show the time in the UI), simulated exceptions that live data cannot show (section 8 end) |

Design rules that follow from the data:

- Decide feasibility, validity, quantities and diet safety in code, not in the prompt. The LLM plans and explains.
- Read the unit from availability, convert through `units[]`, and quote and order in that unit.
- Show unknowns as unknown (untracked stock, Terminal quantity, missing reliability, missing allergen data), never as a number or
  as "safe".
- Every tool response carries `warnings[]` and machine-readable flags so the agent can explain uncertainty.

---

## 10. Open questions for the Valio Aimo mentors

| Id | Question | Why it matters |
|---|---|---|
| Q-01 | Is the frozen snapshot for 2026-11-16 intended? Will it roll forward after Sun 15.11 17:00 or during judging? What "now" should demos assume? | After Sun 17:00 nothing in the data can make Monday (A-03) |
| Q-02 | When `closingTime` has passed, what is the real next delivery date? Is there a delivery calendar (Stock: 17:00 the day before, some ambient goods Fri 13:00; Terminal: vendor slot 4–6 days ahead)? Are weekend deliveries possible? | F-05 estimates are guesses |
| Q-03 | Do Stock amounts 9,999,999,999 and their unit-scaled forms (666666666, 39999999 ...) mean "not tracked / unlimited"? Is there a practical maximum per order? | A-05 |
| Q-04 | Which unit is authoritative when the catalog `salesUnit` and `scheduleLines[].salesUnit` differ (about 1 %, e.g. 465244 ST vs KI)? Should orders always use the API unit? | A-08 |
| Q-05 | Does `allowedLotSize` 0.01 really allow fractional ST or KI, or must orders be whole units? For KG steps, should amounts be rounded down to the step? | F-02 |
| Q-06 | Should `/price` honour `requestedDate` and `validFrom`/`validTo`? Is `validTo` inclusive? How long is a quoted price binding: until the cut-off, until `validTo`, or something else? Is `catalogPrice.value` what the customer is invoiced? | A-09, F-07 |
| Q-07 | Is VAT rounded per unit (`valueWithTax`), per line or per invoice? (1,150.00 vs 1,146.35 for 1,000 × 464306) | F-06 |
| Q-08 | How are deposits (materials 1, 2, 3, 4, 147, 171, 9708918) priced, and are they included in `catalogPrice`? | A-18 |
| Q-09 | Are there volume discounts? `quantity` is always 1.0 and a body quantity is ignored | A-10 |
| Q-10 | Can we get the meanings of unit codes (KI, KRS, ZML, KLE, DOL, MDO, PNT, NIP, DSP, KOR, SK, RAS, PRK), `temperatureCondition` 1–9, category names, and `countryOfOrigin` zy / xs / zz? | D-05, D-08, D-09 |
| Q-11 | Should missing allergen data be treated as "unknown, needs a human"? Is `X99` with CONTAINS meant as "no declarable allergens"? What are `BP`, `SO`, `ABD`, `ADQ`, `UN`? Does "gluten-free" allow oats (`GO`)? | D-04, S-05 |
| Q-12 | Are `substitutions[]` pre-approved by Valio Aimo or only suggestions needing customer consent? Are they directional, is list order a priority, and should they respect claims and allergens (36 % do not)? Is the self-loop on 471661 intended? | D-12 |
| Q-13 | What does `deliveryReliability` measure (inbound or outbound, on time and/or in full), over which period and how many deliveries? Does 0.0 mean "never" or "no data"? | D-10 |
| Q-14 | Which classification is the carbon average computed over? Is 0.79 a default? Are liquids per kg or per litre? | D-11 |
| Q-15 | Are these intended test cases or data errors: net above list (461643, 462250, 475702, 476972), 83.8 % discount (464818), comparison prices of 476738 and 469955, 20 kg vs 5 kg on 464076? | A-11, D-06 |
| Q-16 | With no order endpoint, which order or inquiry format and open standard do the judges expect? Is a simulated order with fixed `/price` prices acceptable? Is a mock order endpoint planned? | G-06 |
| Q-17 | What approval policies are realistic for Valio Aimo customers (value limits, roles, substitution consent, budgets)? | R-07 |
| Q-18 | Are all 17,546 products orderable by any customer, or should we simulate a customer assortment? What are the rate limits? | A-00 |
| Q-19 | For Terminal products (999999), is there a supplier confirmation step or a maximum order quantity we should model? | A-05 |
| Q-20 | Are products with empty `scheduleLines` (about 19 %) delisted or temporarily unavailable? | A-04 |
| Q-21 | In food service, does "lactose-free milk" include Eila "maitojuoma" (milk drink), coffee milk or portion cups? | W-01 |
| Q-22 | Can sales-blocked seasonal items with a future `availableDate` (e.g. 463989 on 2026-12-30) be pre-ordered? | X-08 |
| Q-23 | For catch-weight products (e.g. 461903 "lohifilee n. 10 kg", lot 10), is the invoice based on actual weight, and what tolerance should the agent communicate? | F-02 |
| Q-24 | Can media ids be resolved to image URLs? | D-03 |

---

## 11. Unverified / open claims

These were reported by an explorer but not confirmed by a verifier (or cannot be observed). Do not build on them without a check.

| Id | Claim | Status |
|---|---|---|
| U-01 | The snapshot stays frozen after Sat 01:17, in particular after Sun 15.11 17:00 and after Mon 00:00 | Not observable yet. Make one `/availability` call after Sun 17:00 and one after Mon 00:05 to check |
| U-02 | Meanings of unit codes, `temperatureCondition` codes and category families (D-05, D-08, D-09) | Inferred from cross-tabs and names; ask the mentors (Q-10) |
| U-03 | `validTo` is an inclusive date (SAP convention) | Not observable |
| U-04 | Embeddings are not worth it for the MVP | Not measured (no embedding model available). Supported indirectly: observed failures are about word structure and attributes |
| U-05 | Static pack content exists for all but 24 of 10,726 food-like products | Not reproduced (an independent, cruder parser left 181 of 11,878 MEDIUM-VAT products without a value). Use the 88–93 % coverage figure |
| U-06 | Head-match search reaches P@10 = 1.00 | In-sample on hand-tuned queries with self-written judges; real LLM-generated arguments not tested |
| U-07 | Derived human-readable category labels | Not checked by a verifier |
| U-08 | Classification of substitution edges (113 other brand, 66 other pack size, 37 other variant, 19 other origin, 14 adjacent category) | Not re-tested |
| U-09 | `countryOfOrigin` disagrees with `synkkaData.countriesOfOrigin` for at least 649 products | Not re-tested (the mapping table used was partial) |
| U-10 | Many delivery-reliability values are ratios of very few deliveries | Partly supported (spikes at 0.5, 0.0, 0.667); sample sizes are not in the data |
| U-11 | Carbon factor 0.79 is a default value | Inference from its spread across 47 categories |
| U-12 | Terminal lead time is a fixed weekly vendor slot, so "same slot + 7 days" is the next date | Inference; the API never shows a next date |
| U-13 | The Fri 13:00 Stock group is "ambient dry goods" | 98 % have code 8, whose meaning is itself inferred |
| U-14 | Discount tiers follow temperature class (chilled 15 %, frozen 18 %, ambient 20 %) | Observed tendency in a random sample; the underlying rule is unknown and 7 categories mix tiers |
| U-15 | The full search prototype builds in about 6 s and answers in 1.3–21 ms | Not re-measured by the verifier (a minimal index was: 0.3 s build, under 0.2 ms per query) |
| U-16 | 20–90 catalog products have a packaging-level price mismatch | Rough extrapolation from 8 cases in 3,000 random products; most turned out to be API-unit mismatches (A-08) |

---

## 12. How to reproduce

### Get the data

```bash
# Downloads products.json, delivery_reliability.csv and carbon_footprint.csv into data/raw/ (git-ignored).
# Needs the challenge key in X-API-Key: in the cloud sandbox the proxy injects it, locally export VALIO_AIMO_API_KEY first.
scripts/fetch_data.sh
```

The OpenAPI spec and the product JSON Schema need the portal login and are kept in `docs/reference/`. Treat downloaded files as
untrusted data: run Python with `python3 -I` from a separate scripts directory and pass data paths as arguments.

### Python snippets

Read diet facts from a product (three-valued: check `declared` before trusting an absence):

```python
import json

P = {p["id"]: p for p in json.load(open("data/raw/products.json"))}

def group(p, name):
    for c in (p.get("synkkaData") or {}).get("classifications", []):
        if c["name"] == name:
            return c.get("values", [])
    return []

def diet(p):
    claims = {v["id"] for v in group(p, "nutritionalClaim")}
    contains = {v["id"] for v in group(p, "allergen") if v.get("unit") == "CONTAINS"}
    may = {v["id"] for v in group(p, "allergen") if v.get("unit") == "MAY_CONTAIN"}
    free = {v["id"] for v in group(p, "nonAllergen")}
    declared = bool(contains or may or free)
    return claims, contains, may, free, declared

print(diet(P["464306"]))   # FREE_FROM_LACTOSE among the claims, contains {'AM'}, declared True
```

Call the API in batches (sequential, at most 1,000 ids per call):

```python
import os, requests

BASE = "https://junction26.valioaimo.fi/api"
HEADERS = {"X-API-Key": os.environ["VALIO_AIMO_API_KEY"]}

def post(endpoint, ids, date="2026-11-16"):
    """One entry per id, in request order. Validate ids against the catalog first (A-07)."""
    entries = []
    for i in range(0, len(ids), 1000):
        body = {"customer": "123", "requestedDate": date, "products": ids[i:i + 1000]}
        r = requests.post(f"{BASE}/{endpoint}", json=body, headers=HEADERS, timeout=15)
        r.raise_for_status()
        entries += r.json()["products"]
    return entries
```

Normalise an availability entry (F-03, F-04) and derive content from a price entry (F-01):

```python
import math
from datetime import datetime

def size_of(p, unit):
    return next((u["sizeInBaseUnits"] for u in p["units"] if u["unitId"] == unit), None)

def normalise(entry, p, now, need_date):
    """entry = /availability entry, p = catalog record, now = aware datetime, need_date = 'YYYY-MM-DD'."""
    if not entry["scheduleLines"]:
        return {"state": "NOT_DELIVERABLE"}          # also what an unknown id looks like
    line = entry["scheduleLines"][0]
    unit, amount = line["salesUnit"], line["availableAmount"]
    size = size_of(p, unit) or 1
    if entry.get("logisticModel") == "Terminal":
        kind, qty = "supplier_unconfirmed", None    # always 999999
    elif amount == 0:
        kind, qty = "zero", 0                       # no availableDate key
    elif amount == math.floor(9_999_999_999 / size) or amount >= 1_000_000:
        kind, qty = "untracked", None               # placeholder, not a stock figure
    else:
        kind, qty = "exact", amount
    order_by = datetime.strptime(entry["closingTime"], "%Y-%m-%dT%H:%M:%S%z")
    return {"unit": unit, "unitMismatch": unit != p["salesUnit"], "qtyKind": kind, "qty": qty,
            "availableDate": line.get("availableDate"), "orderBy": order_by,
            "cutoffPassed": order_by <= now,
            "blocked": entry["salesBlock"] or line["salesBlock"],
            "late": line.get("availableDate") is None or line["availableDate"] > need_date}

def api_content(price_entry):
    """(L or kg per API unit, 'L' or 'KG'), or None without a comparison price."""
    cp, cmp = price_entry.get("catalogPrice"), price_entry.get("comparisonPrice")
    if not cp or not cmp or not cmp["value"]:
        return None
    return round(cp["value"] / cmp["value"], 3), price_entry["comparisonUnit"]
```

Expected at Sat 01:17 with the server `timeNow`: 464306 → untracked, open, 1.0 L; 463038 → supplier_unconfirmed, cutoffPassed,
19.943 L; 465244 → unitMismatch (KI), 3.005 L; 474747 → zero, late, unitMismatch (ST); 463989 → blocked, late; 461294 →
untracked (39999999).

### Re-checking the snapshot

To see whether the mock has rolled forward (U-01), re-run the curl table in A-19 and compare it with the expected output there.
Any change in `closingTime`, `availableDate` or amounts means the snapshot moved and sections 3, 7 and 8 need a refresh.

### Provenance

About 290 API calls were made in total during exploration and verification, all sequential and without a 429. The final
re-check for this document used 6 calls (ping, the two OpenAPI-example calls, one 422 probe, one `/availability` and one
`/price` with 206 ids). The exploration scripts lived in a temporary session scratchpad and are not part of the repository;
everything needed to reproduce the findings is in the snippets above.
