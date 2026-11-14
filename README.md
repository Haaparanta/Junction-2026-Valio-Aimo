# Junction 2026 · Valio Aimo · Trusted Trade Agents

A voice purchasing assistant for Valio Aimo's business customers.

**Aino** is a 2D animated virtual person with an ElevenLabs voice. She can:
- find products;
- check price and availability;
- issue fixed-price signed quotes;
- place orders within each buyer's mandate.

Orders outside the mandate go to a human approver, and every step goes into a tamper-evident audit trail.

The joke version is **Mansikki the cow**. She moos instead of talking but uses the same agent, tools and controls.

The same gateway is open to any AI agent over MCP and OpenAPI.

> Status: the voice vertical slice works end to end on contract stubs (canned W-03 answers). The basket (M21–M28) is on `main`: several products, filled by voice, clicks, an Excel or CSV list, a photo of a list or a dish, then one quote. The live agent learns the basket tools after the next `provision.py push`. Real search, offers, quotes, policy and orders are M2–M9. See the plans and [the basket status](docs/basket-plan.md#status).

## Docs

| Document | What it covers |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | The solution, the demo script, and 20 milestones with sub-milestones, owners, estimates and acceptance checks. Also timeline, cut lines and risks. |
| [docs/basket-plan.md](docs/basket-plan.md) | M21–M29: one basket filled by voice, clicks, Excel/CSV, a photo of a list or a dish, then one quote. Decisions that join the three briefs in [docs/briefs/](docs/briefs/), build order, cut lines. |
| [docs/data-and-api-findings.md](docs/data-and-api-findings.md) | What the product data and the mock price/availability API really do: traps, formulas, worked example, exception fixtures, mentor questions. |
| [docs/tech-research.md](docs/tech-research.md) | Fact-checked notes on ElevenLabs Agents, the React SDK and avatar lip-sync, cow audio, the Python gateway stack and open agent-commerce standards, with version pins. |
| [docs/reference/](docs/reference/) | Copies of the challenge OpenAPI spec and the product JSON Schema (both sit behind the portal login). |

## Get the challenge data

```bash
scripts/fetch_data.sh
```

This downloads `products.json`, `delivery_reliability.csv` and `carbon_footprint.csv` into `data/raw/`, which is git-ignored because the data is for Junction use only.

The script needs the challenge API key:
- **In the cloud environment:** the network proxy injects the key, so you don't set anything.
- **Locally:** export `VALIO_AIMO_API_KEY` first.

Never commit the key.

## Live demo

https://valio-aimo-854901616539.europe-north1.run.app runs on Cloud Run in europe-north1. Sign in as Chef Aada, then press **Talk to Aino**, or type to start a text chat. Deploying and pointing the agent at the service are described in [docs/deploy.md](docs/deploy.md).

## Run the voice slice

To develop locally, use the steps below. The agent follows whatever host `provision.py push` last set, so pushing a tunnel host takes it away from Cloud Run until you push the Cloud Run host again.

You need uv, pnpm 12, Node 22+, ngrok and an ElevenLabs account. Keys live only in git-ignored files:

| File | Holds | Written by |
|---|---|---|
| `.env` | `VALIO_AIMO_API_KEY`, and `ANTHROPIC_API_KEY` if you have no `ant auth login` profile | you |
| `.env.local` | `ELEVENLABS_API_KEY` | `npx -y @elevenlabs/cli@latest onboard init` |
| `.env.gateway` | `GATEWAY_PLATFORM_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_WEBHOOK_SECRET`, `PUBLIC_HOST` | `scripts/gen_secrets.py`, `agent/provision.py` |

In a git worktree these files must be in the worktree's own root.

1. Install everything and create the gateway secret (once):

   ```bash
   uv sync && pnpm install && python3 scripts/gen_secrets.py
   ```

2. Start the gateway (terminal 1). It loads `.env.local` explicitly; `.env` and `.env.gateway` are read by the settings:

   ```bash
   pnpm gateway
   ```

3. Open a public URL so ElevenLabs can call the webhook tools (terminal 2):

   ```bash
   ngrok http 8000
   ```

4. Point the agent at that host. This step is idempotent: it updates the `gateway_host` environment variable, the workspace secret and the agent. Then restart the gateway so it picks up the new agent id:

   ```bash
   uv run python agent/provision.py push --host <your-subdomain>.ngrok-free.app
   ```

5. Start the web app (terminal 3) and open http://localhost:5173 in desktop Chrome, with a headset:

   ```bash
   pnpm dev
   ```

Sign in as Chef Aada and press **Talk to Aino**. Chrome asks for the microphone. Then say *"I need a thousand litres of lactose-free milk by Monday"*, or the same in Finnish. Aino shows the options, makes a quote when you choose one, and asks you to press **Confirm order**. The gateway then answers `requires_escalation`, because 1,010 € is over the 500 € cap. Switch to **Mansikki** at any point in the call. Typing in the text box works during a call, and starts a text-only chat when no call is running.

The post-call webhook needs an ElevenLabs key with `webhooks_write`. If `provision.py` reports that it skipped the webhook, create an HMAC webhook in the dashboard, then rerun `push` with `--webhook-id`.

Record fixtures before Sun 15.11 17:00 Helsinki time. `data/fixtures/` stays git-ignored:

```bash
python3 scripts/record_fixtures.py
```

Tests: `uv run pytest`, `pnpm test`, `pnpm typecheck`. CI runs on Google Cloud Build (`cloudbuild.yaml`), not GitHub Actions; see [docs/deploy.md](docs/deploy.md#ci-and-continuous-deploy-cloud-build).

## Fill the basket

Aino adds each product you name to one basket, once `provision.py push` has given the live agent the basket tools. You can also fill it on screen:

| Way in | How |
|---|---|
| Clicks | **Add to basket** on an option card. Click a line's amount, unit, date or product to change it; × removes it, with **Undo**. |
| Excel or CSV | **Import list**, or drop the file. Start from `web/public/tilauslista-pohja.csv` or `GET /v1/baskets/template.xlsx`. |
| A photo of a list | **Photo to basket**. Claude reads the list; a date written on it dates every line. The photo is not stored. |
| A dish | **Dish to basket**, or tell Aino, for example *"mansikkakakku 40 hengelle maanantaiksi"*. Claude plans the ingredients, which takes about 40 s. |

Then press **Get one quote for all**. The gateway prices every line, and quotes the basket only when no line still needs a choice, an amount or a later date.

The photo and the dish need Anthropic credentials in the gateway: `ANTHROPIC_API_KEY` in `.env`, or locally just `ant auth login`. Without them those two routes answer 503 and everything else works. On Cloud Run the key is a secret; see [docs/deploy.md](docs/deploy.md#anthropic-key-photo-and-dish).
