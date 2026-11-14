# One image: the FastAPI gateway serving the built buyer UI from the same origin.
# Built by Cloud Build (`gcloud run deploy --source .`); see docs/deploy.md.

FROM node:22-slim AS web
RUN npm install -g pnpm@12.18.0
WORKDIR /src
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY web/package.json web/
RUN pnpm install --frozen-lockfile
COPY web web
RUN pnpm --filter web build

FROM python:3.13-slim
RUN pip install --no-cache-dir uv==0.13.8
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
COPY gateway gateway
RUN uv sync --frozen --no-dev
COPY --from=web /src/web/dist web/dist
ENV PATH=/app/.venv/bin:$PATH PORT=8080 DB_PATH=/tmp/gateway.db COOKIE_SECURE=true
RUN useradd --uid 10001 app && chown -R app /app
USER app
CMD exec uvicorn app.main:app --app-dir gateway --host 0.0.0.0 --port "$PORT" --forwarded-allow-ips='*' --proxy-headers
