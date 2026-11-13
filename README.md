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

> Status: research and planning are done; implementation has not started. See the plan.

## Docs

| Document | What it covers |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | The solution, the demo script, and 20 milestones with sub-milestones, owners, estimates and acceptance checks. Also timeline, cut lines and risks. |
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
