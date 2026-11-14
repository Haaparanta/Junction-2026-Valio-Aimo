# Deploy runbook: Cloud Run (PLAN M14.1, M14.4)

One container (see `Dockerfile`) runs the FastAPI gateway and serves the built buyer UI from the same origin. This gives HTTPS for the microphone, first-party cookies and one public host for the ElevenLabs webhook tools. Cloud Build builds the image from source.

| Item | Value |
|---|---|
| Project | `famous-hull-514004-t9` (billing account "Firebase Payment") |
| Region | `europe-north1` (Finland) |
| Service | `valio-aimo` |
| Scaling | `--min-instances 1 --max-instances 1 --no-cpu-throttling`: always warm, because cold starts exceed the 20 s / 30 s tool timeouts (tech-research §7) |
| Secrets (Secret Manager) | `gateway-platform-key` → `GATEWAY_PLATFORM_KEY`, `elevenlabs-api-key` → `ELEVENLABS_API_KEY` |
| Plain env | `ELEVENLABS_AGENT_ID`, `PUBLIC_HOST`; the image sets `COOKIE_SECURE=true`, `DB_PATH=/tmp/gateway.db` |

**State is in memory.** SQLite lives in `/tmp` on the single instance, and the contract stubs keep quotes and orders in memory. A redeploy or restart forgets sessions, quotes and orders. That is fine for the stubs. M10 (audit) needs persistent storage, for example Cloud SQL or a mounted volume.

## Deploy or redeploy

```bash
gcloud run deploy valio-aimo --source . --project famous-hull-514004-t9 --region europe-north1 \
  --allow-unauthenticated --min-instances 1 --max-instances 1 --no-cpu-throttling --cpu 1 --memory 512Mi \
  --set-secrets GATEWAY_PLATFORM_KEY=gateway-platform-key:latest,ELEVENLABS_API_KEY=elevenlabs-api-key:latest \
  --set-env-vars ELEVENLABS_AGENT_ID=<agent id from .env.gateway>
```

`.gcloudignore` keeps `.env*`, `data/`, `agent/` and `docs/` out of the upload.

## Point the agent at the service (after the first deploy, or when the host changes)

```bash
HOST=$(gcloud run services describe valio-aimo --project famous-hull-514004-t9 --region europe-north1 \
  --format='value(status.url)' | sed 's#https://##')
gcloud run services update valio-aimo --project famous-hull-514004-t9 --region europe-north1 \
  --update-env-vars PUBLIC_HOST=$HOST
uv run python agent/provision.py push --host $HOST
```

`provision.py push` updates the ElevenLabs environment variable `gateway_host`, the workspace secret and the agent. The Cloud Run URL is stable, so this is needed only once.

## Rotate the platform key

```bash
python3 scripts/gen_secrets.py   # only if .env.gateway has no key; otherwise edit it there
uv run python -c "import sys; sys.path.insert(0,'gateway'); from app.settings import Settings; \
  sys.stdout.write(Settings().gateway_platform_key)" | \
  gcloud secrets versions add gateway-platform-key --project famous-hull-514004-t9 --data-file=-
uv run python agent/provision.py push --host $HOST   # same value into the ElevenLabs workspace secret
gcloud run services update valio-aimo --project famous-hull-514004-t9 --region europe-north1   # new revision reads :latest
```

## Logs

```bash
gcloud run services logs read valio-aimo --project famous-hull-514004-t9 --region europe-north1 --limit 50
```

## CI and continuous deploy: Cloud Build

This repo uses Google Cloud Build, not GitHub Actions. [`cloudbuild.yaml`](../cloudbuild.yaml) runs these steps:

1. `secrets`: a gitleaks scan of the checkout.
2. `gateway` and `web`, in parallel:
   - gateway: ruff, ruff format, pytest and the agent tool-config drift check;
   - web: tsc, vitest and the Vite build.
3. On `main` only, or with `_DEPLOY=true`: build the image, push it to Artifact Registry and deploy it to Cloud Run.

The deploy changes only the image. Env vars, secrets, scaling and public access stay as configured above.

Run it by hand. The first command runs checks only; the second runs checks and deploys:

```bash
gcloud builds submit --config cloudbuild.yaml --region europe-north1 --project famous-hull-514004-t9 .
```

```bash
gcloud builds submit --config cloudbuild.yaml --region europe-north1 --project famous-hull-514004-t9 \
  --substitutions _DEPLOY=true .
```

### Triggers (one-time setup)

1. Connect GitHub (2nd-gen connection). The command prints a link: open it, authorise the Cloud Build GitHub App and install it on `Haaparanta/Junction-2026-Valio-Aimo` only.

   ```bash
   gcloud builds connections create github valio-github --region europe-north1 --project famous-hull-514004-t9
   ```

2. Link the repository, then create the two triggers:

   ```bash
   gcloud builds repositories create junction-valio-aimo --connection valio-github --region europe-north1 \
     --project famous-hull-514004-t9 --remote-uri https://github.com/Haaparanta/Junction-2026-Valio-Aimo.git
   REPO=projects/famous-hull-514004-t9/locations/europe-north1/connections/valio-github/repositories/junction-valio-aimo
   gcloud builds triggers create github --name ci-pull-request --region europe-north1 --project famous-hull-514004-t9 \
     --repository $REPO --pull-request-pattern '^main$' --build-config cloudbuild.yaml
   gcloud builds triggers create github --name deploy-main --region europe-north1 --project famous-hull-514004-t9 \
     --repository $REPO --branch-pattern '^main$' --build-config cloudbuild.yaml
   ```

Cloud Build reports each run back to the pull request as a GitHub check.
