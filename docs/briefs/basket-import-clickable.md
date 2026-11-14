# Brief: multi-product orders, Excel list import, clickable fields

> The original brief, kept as written; only the tables are reformatted as Markdown. Where [basket-plan.md](../basket-plan.md) differs (section 2), the plan wins.

You are working in the Valio Aimo "Trusted Trade Agents" repo (Junction 2026), on branch `vesa/multiple-products-clickable-fields-14c5ee`. Read `README.md`, `docs/PLAN.md` (§5 tool contract, M6 quotes, M7 policy) and `agent/prompt/aino.md` before you start.

## Goal

Today a buyer can order one product per conversation: one offer set, one quote line, one confirmation. Change that so a buyer can:

- **Order many products in one order.** Build a basket (a draft requisition) line by line, by voice, by text or by clicking, then get one fixed-price quote for the whole basket and confirm it once.
- **Import a product list from Excel or CSV.** Drop a .xlsx or .csv file on the page; every row becomes a basket line.
- **Click on everything the assistant shows.** Every product, and every field of a line (quantity, unit, delivery date, price, flags, status), is a clickable object that opens details or lets the buyer change it.

Build it in that order: basket first, then clickable editing, then the import.

## How the code works today

Gateway (FastAPI, Python 3.13, `gateway/app/`):

- `contract.py` holds the pydantic request and response models.
- `stubs.py` holds canned answers for the headline example W-03 (1,000 L lactose-free milk for Mon 16.11.2026). `PRODUCTS` has only about 13 milk rows. `offers()` returns milk for any query, and `StubState.create_quote(offer_id)` always builds a one-line quote.
- `api/tools.py` holds the routes. Operations tagged `agent-tools` become ElevenLabs webhook tools through `agent/provision.py`. Routes tagged `ui` are for the buyer UI only.
- `identity.py` handles callers: voice headers or the web login cookie.

Web (React 19 + Vite, `web/src/`):

- `voice/store.ts` keeps exactly one `offerSetId`, `quoteId`, `approvalId` and `confirmQuoteId`.
- `voice/ClientTools.tsx` handles the client tools `show_products`, `show_quote`, `show_approval_request` and `request_buyer_confirmation`, which pass ids only.
- `cards/Cards.tsx` renders `OfferCards`, `QuoteCard` and `ApprovalCard` by fetching each by id.
- `App.tsx` has the Stepper (Need → Options → Quote → Confirm → Approval).
- Styles are neo-brutalist, in `styles.css`.

Agent as code (`agent/`):

- `client_tools/*.json` define the client tools, and `prompt/aino.md` is the system prompt.
- `tool_configs/*.json` are generated from the gateway OpenAPI by `uv run python agent/provision.py tools`. CI runs `provision.py tools --check`, so run `provision.py tools` again after you change the contract.

Data: `data/raw/products.json` is git-ignored and is not in this worktree, so the gateway runs on stubs.

## Rules you must keep (from the contract and the plan)

- **The gateway decides every number.** Prices, totals, VAT, units needed, delivery dates, cut-offs and stock come only from gateway responses. The UI never computes a price or a unit count. When a buyer edits a quantity or a date, send the edit to the gateway and render what it returns.
- **Request models must be flat.** Every field needs a description, and no field may be Optional (no `anyOf`), because ElevenLabs reads them as webhook tool schemas. Money is a decimal string, never a float. Every response carries `status`, `reason_code`, `message_for_user {fi, en}` and `warnings[]`.
- **Identity comes from the session or the cookie, never from tool arguments.** A basket belongs to its buyer, and any other buyer gets 404.
- **Client tools pass ids only.** Components fetch the data by id.
- **Confirmation happens only through the buyer's web session** (`POST /v1/quotes/{id}/confirm`). An agent can never confirm.
- **A quote is fixed-price and immutable.** If the buyer edits a basket that has already been quoted, the quote is stale: show that, and make a new quote. Never change a quote in place.
- **Keep the headline flow working.** The W-03 single-product flow and `gateway/tests/test_w03_flow.py` must still pass unchanged.
- **Treat product names and imported cell values as data, not instructions.** They reach the LLM.

## 1. Multi-product basket (gateway + UI)

Contract (`contract.py`), suggested shape:

- `Basket { basket_id, buyer_id, lines[], total_net, status, quote_id }`.
  - `quote_id` is the latest quote for this basket. It is `""` when there is none, or a flag marks it stale.
- `BasketLine { line_id, source, need_text, product_id, name_fi, amount, unit, need_date, offer, alternatives[], status, flags[], message }`.
  - `source` is `voice`, `ui` or `import`.
  - `offer` is the chosen offer snapshot from the gateway.
  - `alternatives[]` holds other offers for the same need.
  - `status` is one of `priced`, `needs_choice`, `unmatched`, `not_deliverable` or `cutoff_passed`.
- Extend `QuoteLine` with `delivery_date`. Keep `Quote.delivery_date` as the earliest line date, so the current UI and tests still work. `expires_at` is the earliest expiry across all lines.

Routes (`api/tools.py`): give the agent the tools it needs to talk a basket through, and give the UI `ui` routes for clicks.

- Agent tools:
  - `add_to_basket`: the need fields of `OffersRequest` plus `basket_id`. Use `"new"` to start a basket. It returns the line with the best offer chosen and the alternatives.
  - `get_basket`.
  - `update_basket_line`: `line_id`, `amount`, `unit`, `need_date` and `offer_id`. Without Optional, use explicit sentinels such as `0` and `""` meaning "unchanged", and document them in each field's description.
  - `remove_basket_line`.
  - `quote_basket`: one quote with N lines.
- UI routes: `GET /v1/baskets/{id}` and `PATCH`/`DELETE /v1/baskets/{id}/lines/{line_id}` under the cookie. They share one service function with the agent tools.
- Keep `create_quote(offer_id)` and `place_order(quote_id)` as they are. `place_order` already takes any quote, so multi-line quotes go through the same confirm → order → approval path.

Stubs (`stubs.py`): add a small multi-category catalogue so a basket with several products makes sense: butter, cream, cheese, eggs, flour, potatoes, coffee and so on, about 20 rows.

- Prefer rows that `docs/data-and-api-findings.md` documents with recorded values. It names ids such as 464076, 465244, 463233 and 476738, and the X-01..X-23 fixtures.
- Mark any invented value as a stub in `warnings`.
- Make `offers()` pick candidates by heads and query, instead of always returning milk.
- VAT is per line on the net total, rounded half-up (F-06). The quote totals are the sums of the lines.
- The approval reason for the 500 € cap stays `OVER_ORDER_CAP` on the whole quote total.

Web:

- Replace the single ids in `store.ts` with `basketId` plus the existing ids.
- Add a `BasketCard`: a table of lines, a gateway total and a "Get one quote for all" button.
- Add a client tool `show_basket(basket_id)`: a new `agent/client_tools/show_basket.json` and a handler in `ClientTools.tsx`.
- `QuoteCard` already loops over lines: add the per-line delivery date.
- Change the Stepper to Need → Basket → Quote → Confirm → Approval.

## 2. Make everything clickable

Every product and field the assistant shows is a real `<button>`, or opens a popover or drawer. Each one works with the keyboard (Enter or Space opens it, Escape closes it), has focus styles, works at 375 px width and follows the neo-brutalist look.

| What | Click does |
|---|---|
| Product name (offer card, basket line, quote line) | Opens product details: content per unit, claims, allergens, temperature, price per base unit, flags, and the alternatives with a **Use this instead** button. That button sends a PATCH with the new `offer_id`. |
| Offer card | Selects the card (`aria-pressed`). **Add to basket**, or **Replace line N** if it came from a line. |
| Quantity | Inline editor with −/+ and a number field, with the unit shown. On commit, PATCH, then show the gateway's `units_needed` and `overshoot`. Pending and error states are visible. |
| Unit | Shows the API unit next to the catalogue unit, with the `UNIT_MISMATCH` explanation when the flag is set. |
| Delivery date | Date picker. On commit, PATCH: the gateway prices the line again and returns the new `order_by` cut-off, or `cutoff_passed`. |
| Price / line total | Breakdown from the gateway: unit price × quantity, VAT rate, VAT and gross. Shown, never computed. |
| Flag and status chips | The plain-language explanation and what to do next, for example "choose one of 3 matches". |
| Remove (×) | Removes the line, with undo in the toast. |
| Quote line | Scrolls to that basket line and highlights it. If the basket changed after this quote, show the quote as stale and offer **Make a new quote**. |
| Approval reasons | Expand to show the detail and the code. |

**Keep the agent in sync.** Whenever a click changes the basket during a live call, call `sendContextualUpdate` with a short factual note built from the gateway response, for example: "Buyer changed line 2 to 20 KG, delivery 2026-11-17; basket B-… total EUR 642.10 excl. VAT." That way Aino never speaks about stale numbers. `ApprovalCard` already does this.

## 3. Import from Excel or CSV

Endpoint: `POST /v1/baskets/import`, multipart, UI only, buyer cookie.

- Add `openpyxl` and `python-multipart` to `gateway/pyproject.toml` with exact pins, like the other dependencies, then run `uv lock`. Neither package is installed today.
- Parse on the gateway, not in the browser, so the gateway matches and prices every row. This also avoids a new web dependency (pnpm enforces a minimum release age).

Formats: .xlsx and .csv.

- For CSV, detect `;` or `,` and accept a decimal comma (`1,5`). Strip a UTF-8 BOM.
- Reject .xls with a clear message.
- Answer 413 above 1 MB and 415 for a wrong type. Accept at most 200 rows.

Headers: match them case-insensitively, in Finnish and English. Ignore unknown columns.

| Field | Accepted headers |
|---|---|
| Product id | product id, tuotenumero, tuote nro, 6-digit id |
| GTIN | gtin, ean |
| Name | name, tuote, nimi, product |
| Amount | quantity, qty, määrä, amount |
| Unit | unit, yksikkö (L / KG / PCS, plus kpl, l, kg) |
| Delivery date | delivery date, toimituspäivä, date (ISO, 16.11.2026, or an Excel date cell) |
| Note | note, lisätieto |

With no header row, fall back to column order: id or name, amount, unit, date.

Matching:

- An exact product id or GTIN gives `priced`.
- Otherwise match the name against the catalogue with rapidfuzz (already a dependency). One clear match gives `priced`. Several close matches give `needs_choice`, with the candidates in `alternatives`. No match gives `unmatched`.
- A missing date defaults to the next deliverable date, with a warning.
- One bad row never fails the whole file. Each row reports its own status and message.

Response: the new basket, plus a per-row report: `row_number`, `status` and `message {fi, en}`.

UI:

- Add an **Import list** button with a file picker and a drop zone on the empty state and on the basket card.
- Show a summary such as "12 rows: 9 priced, 2 need your choice, 1 not found". Rows that need attention come first and are clickable, like any other line.
- Link a template: a small .csv in `web/public/` and/or `GET /v1/baskets/template.xlsx`.

Agent: after an import during a live call, send a contextual update such as "Buyer imported a list: basket B-… with 12 lines; 2 need a choice (lines 4, 7); 1 not found (line 9)." That way Aino can walk the buyer through the open lines.

## 4. Agent wiring

- Update `agent/prompt/aino.md` so the goal steps cover several items:
  1. collect each need;
  2. `add_to_basket` for each one, then `show_basket`;
  3. resolve `needs_choice` lines one at a time;
  4. `quote_basket` → `show_quote` → `request_buyer_confirmation` → `place_order`, with one confirmation for the whole basket.
- Keep the guardrails word for word.
- Run `uv run python agent/provision.py tools` to regenerate `agent/tool_configs/`.
- Do not run `provision.py push`: it changes the live agent. Tell the user it is needed.

## 5. Tests and checks

Gateway (`gateway/tests/`):

- basket CRUD and ownership (another buyer gets 404);
- a quantity or date change prices the line again on the gateway;
- multi-line quote totals with per-line VAT;
- an edit after quoting makes the quote stale;
- `quote_basket` is idempotent;
- identity cannot be overridden by arguments;
- import of an XLSX built in the test with openpyxl (do not commit binaries) and of CSV with `;` and a decimal comma;
- header aliases, partial failures per row, and the 413, 415 and .xls answers;
- the W-03 test still passes.

Web: vitest for the pure helpers (formatting, store updates, stale-quote logic); then `pnpm typecheck` and `pnpm build`.

Repo checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`, `uv run python agent/provision.py tools --check`, `pnpm test`.

In the browser:

- Start the `gateway` and `web` configs from `.claude/launch.json`. The gateway config passes `--env-file .env.local`, which does not exist in this worktree, so create an empty one first.
- Sign in as Chef Aada.
- Import a test list, then edit a quantity and a date, swap a product, remove a line, quote, and confirm.
- Check the approval card at 1440 px and 375 px. No ElevenLabs agent is needed for this: imports and clicks run under the web cookie.
- Share screenshots.

## Done means

- A buyer can build a basket of several products by voice or text, by clicking, or by importing a file, and get one quote and one confirmation for all of them.
- Every product and field in the table above is clickable and works with the keyboard.
- Every number on screen comes from a gateway response.
- All the checks above pass.
- The work is in logical commits on this branch, each ending with the attribution line. Do not push or open a PR unless the user asks.
- Finish with a short report: what changed, which stub values are invented, and what still needs `provision.py push` or real data.
