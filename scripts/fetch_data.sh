#!/usr/bin/env bash
# Downloads the Valio Aimo Junction 2026 challenge data into data/raw/.
# (The OpenAPI spec and product JSON Schema sit in docs/reference/: they need the portal login.)
# Needs the challenge API key in the X-API-Key header: in the cloud environment the
# network proxy injects it; locally, export VALIO_AIMO_API_KEY first.
set -euo pipefail
BASE="${VALIO_AIMO_API_BASE_URL:-https://junction26.valioaimo.fi/api}"
KEY="${VALIO_AIMO_API_KEY:-proxy-injected}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/data/raw"
mkdir -p "$OUT"
fetch() { curl -fsS -L -H "X-API-Key: $KEY" -o "$OUT/$2" "$BASE/$1/download"; echo "fetched $2"; }
fetch products products.json
fetch delivery-reliability delivery_reliability.csv
fetch carbon-footprint carbon_footprint.csv
