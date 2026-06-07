# MarkItDown API

An HTTP wrapper around [MarkItDown](../packages/markitdown) that lets a frontend
(or any HTTP client) convert documents to Markdown without shelling out to the
CLI.

> **Fork-isolation notice:** Everything described in this document — `api/`,
> `docker-compose.yml`, and `api/sync-fork.sh` — is *new* code layered on top of
> the upstream [microsoft/markitdown](https://github.com/microsoft/markitdown)
> project. None of it touches an upstream file or path, so pulling in upstream
> changes can never delete or overwrite it (see [Keeping the fork in
> sync](#keeping-the-fork-in-sync)).

---

## Contents

- [Web UI](#web-ui)
- [Endpoints](#endpoints)
- [Configuration](#configuration)
- [Running locally](#running-locally)
- [Running with Docker](#running-with-docker)
- [Deploying](#deploying)
- [Authentication](#authentication)
- [Keeping the fork in sync](#keeping-the-fork-in-sync)
- [Project layout](#project-layout)

---

## Web UI

Visit `/` and you'll get a small, opinionated, slightly sassy single-page app
([`static/index.html`](static/index.html)) — a drag-and-drop file zone, a
"just give me a URL" tab, an optional API-key field (remembered in
`localStorage`), and an output panel with copy/download buttons. It's plain
HTML/CSS/vanilla JS served directly by FastAPI's `StaticFiles` — no build
step, no extra dependencies, no separate container.

It talks to the exact same `/convert/file` and `/convert/url` endpoints
documented below, so anything the UI can do, your own frontend can do too —
the UI is really just a reference client (with attitude) that also happens to
be useful on its own.

If you'd rather not serve it (e.g. you're running this purely as a headless
backend behind your own frontend), you can remove the `app.mount(...)` call at
the bottom of `main.py` — every other endpoint works identically without it.

---

## Endpoints

All endpoints are served from the FastAPI app in [`main.py`](main.py). Once
running, interactive docs are available at `/docs` (Swagger UI) and `/redoc`.

| Method | Path            | Auth | Description                                              |
|--------|-----------------|------|----------------------------------------------------------|
| GET    | `/health`       | No   | Liveness/readiness probe. Returns `{"status": "ok"}`.   |
| GET    | `/info`         | No   | API/version info and feature flags (LLM enabled, auth required, upload limits). |
| POST   | `/convert/file` | Yes  | Upload a file (`multipart/form-data`, field `file`) and convert it to Markdown. |
| POST   | `/convert/url`  | Yes  | Convert a remote document or webpage given as `{"url": "..."}` (JSON body). |

### `POST /convert/file`

```bash
curl -X POST http://localhost:8000/convert/file \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/path/to/report.pdf"
```

### `POST /convert/url`

```bash
curl -X POST http://localhost:8000/convert/url \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'
```

### Response shape

Both conversion endpoints return:

```json
{
  "markdown": "# Document title\n\n...converted content...",
  "title": "Document title",
  "source": "report.pdf"
}
```

### Error responses

| Status | Meaning                                                            |
|--------|--------------------------------------------------------------------|
| 401    | Missing/invalid `X-API-Key` (only when `API_KEY` is configured)    |
| 413    | Upload exceeded `MAX_UPLOAD_BYTES`                                  |
| 415    | No converter recognizes the file format (`UnsupportedFormatException`) |
| 422    | A converter was found but conversion failed (`FileConversionException`) |
| 500    | Unexpected server error                                            |

---

## Configuration

The API is configured entirely through environment variables — there is no
config file to keep in sync with upstream.

| Variable             | Default            | Purpose                                                                 |
|----------------------|--------------------|-------------------------------------------------------------------------|
| `API_KEY`            | *(empty)*          | Static key required in the `X-API-Key` header. Empty = auth disabled (dev mode). |
| `OPENAI_API_KEY`     | *(empty)*          | When set, enables LLM-generated descriptions for images/audio (passed to MarkItDown as `llm_client`/`llm_model`). |
| `OPENAI_BASE_URL`    | *(empty)*          | Optional override, e.g. to point at an Azure OpenAI / OpenAI-compatible endpoint. |
| `OPENAI_MODEL`       | `gpt-4o-mini`      | Model used for image/audio descriptions when `OPENAI_API_KEY` is set.   |
| `MAX_UPLOAD_BYTES`   | `52428800` (50 MiB)| Maximum accepted size for `/convert/file` uploads.                      |
| `CORS_ALLOW_ORIGINS` | *(empty)*          | Comma-separated list of allowed origins for browser-based frontends. Empty = CORS middleware disabled. |
| `API_PORT`           | `8000`             | *(docker-compose only)* host port mapped to the container's port 8000.  |

---

## Running locally

Requires Python 3.10+ (matching `packages/markitdown`'s `requires-python`).

```bash
# From the repo root
pip install -e packages/markitdown[all]
pip install -r api/requirements.txt

uvicorn api.main:app --reload --port 8000
```

Then visit `http://localhost:8000/docs`.

---

## Running with Docker

### Docker Compose (recommended)

```bash
# With an API key (recommended for anything beyond local dev)
API_KEY=mysecret docker compose up --build

# Dev mode — no auth required
docker compose up --build

# With LLM-powered image/audio descriptions
API_KEY=mysecret OPENAI_API_KEY=sk-... docker compose up --build
```

This builds [`api/Dockerfile`](Dockerfile) using the repo root as the build
context (so it can install the local `packages/markitdown` source rather than
a published release) and exposes the API on `http://localhost:8000` (override
with `API_PORT`).

### Plain `docker build` / `docker run`

```bash
docker build -f api/Dockerfile -t markitdown-api .
docker run --rm -p 8000:8000 \
  -e API_KEY=mysecret \
  -e OPENAI_API_KEY=sk-... \
  markitdown-api
```

> **Note:** the API image is independent of the repo's existing root
> [`Dockerfile`](../Dockerfile), which packages the MarkItDown *CLI* for
> stdin/stdout use. The two serve different purposes and can coexist —
> neither references the other.

---

## Deploying

The API is a stateless FastAPI/Uvicorn service — it holds no persistent data
(uploaded files are written to a temp file for the duration of a single
request and discarded immediately after). That makes it straightforward to run
on most container platforms:

1. **Build & push the image:**
   ```bash
   docker build -f api/Dockerfile -t <registry>/<image>:<tag> .
   docker push <registry>/<image>:<tag>
   ```
2. **Run it** behind your platform's load balancer / ingress, exposing
   container port `8000`. Typical targets: a single VM with `docker compose`,
   a managed container service (ECS, Cloud Run, Azure Container Apps, Fly.io,
   Render, Railway), or a Kubernetes `Deployment` + `Service`.
3. **Set environment variables** for the deployment (`API_KEY` at minimum —
   see [Configuration](#configuration)). Treat `API_KEY` and `OPENAI_API_KEY`
   as secrets (platform secret store / Kubernetes `Secret`, not plain env in
   source control).
4. **Wire up health checks** against `GET /health` (already configured in
   `docker-compose.yml`'s `healthcheck` block — mirror it in your platform's
   probe configuration).
5. **Put it behind HTTPS.** The API itself speaks plain HTTP; terminate TLS at
   your load balancer / reverse proxy (nginx, Caddy, your cloud provider's
   ingress, etc.) as you would for any other backend service.
6. **Scale horizontally if needed.** Each request is independent and
   converters run in-process, so you can run multiple replicas behind a load
   balancer with no shared state or sticky sessions required. CPU/IO-heavy
   conversions (large PDFs, audio transcription) benefit most from extra
   replicas rather than larger single instances.

### Resource notes

- Conversions of large PDFs, audio files (via `ffmpeg`), or images (via
  `exiftool` and, optionally, an LLM call) are CPU/IO bound and can take
  several seconds. Size request timeouts at your reverse proxy / platform
  accordingly (e.g. ≥ 60s).
- `MAX_UPLOAD_BYTES` guards the API itself, but make sure any reverse proxy or
  platform-level body-size limit (e.g. nginx `client_max_body_size`, cloud LB
  request size limits) is configured to match or exceed it.

---

## Authentication

Authentication is a static API key checked against the `X-API-Key` request
header (see `require_api_key` in [`main.py`](main.py)):

- Set `API_KEY` to require it. Requests with a missing or mismatched header
  receive `401 Unauthorized`.
- Leave `API_KEY` unset/empty to disable auth entirely — useful for local
  development, **not recommended for any publicly reachable deployment**.

This is intentionally simple (no user accounts, no token issuance/rotation
endpoints) — it's meant to gate a backend service consumed by a trusted
frontend, not to be a full auth system. If you need per-user auth, put this
API behind a gateway/BFF that handles it and forwards a shared `X-API-Key`.

---

## Keeping the fork in sync

This is a fork of [microsoft/markitdown](https://github.com/microsoft/markitdown)
with the API layer added on top. **Do not use GitHub's "Sync fork" /
"Discard ... and sync" button, and do not `git reset --hard upstream/main`** —
both perform a fast-forward/reset that throws away any commits that exist only
on your fork, which would silently delete `api/`, `docker-compose.yml`, and
this README.

Instead, use a **merge**, which is non-destructive: it three-way-merges
upstream's history into yours, so files that only exist on your side (like
everything under `api/`) are simply kept. Real conflicts — i.e. upstream
edited a path you've also changed — are surfaced for manual review instead of
being silently resolved one way or the other.

A helper script automates this safely:

```bash
api/sync-fork.sh          # fetch + merge upstream/main, stop for you to review
api/sync-fork.sh --push   # ...then push the result to origin
```

It will:
- add the `upstream` remote (`https://github.com/microsoft/markitdown.git`) if
  missing,
- refuse to run on a dirty working tree,
- merge `upstream/main` with `--no-ff` (always creates a merge commit, never a
  silent fast-forward), and
- abort cleanly with instructions if the merge produces conflicts.

Because `api/` is a path that doesn't exist upstream, merges essentially never
conflict with it — conflicts can only arise on files this fork has *also*
modified outside `api/` (which, by convention, should be none).

---

## Project layout

```
api/
├── main.py                # FastAPI app: routes, auth, MarkItDown wiring, static mount
├── static/
│   └── index.html         # The sassy little reference web UI (served at "/")
├── requirements.txt       # API-only dependencies (fastapi, uvicorn, openai, ...)
├── Dockerfile             # Standalone image; built with the repo root as context
├── Dockerfile.dockerignore # Per-Dockerfile override of the root .dockerignore,
│                          # which excludes everything except packages/ (and
│                          # would otherwise drop api/ from the build context —
│                          # BuildKit auto-detects "<dockerfile>.dockerignore")
├── sync-fork.sh           # Safe upstream-merge helper (see above)
└── README.md              # This file

docker-compose.yml    # Single-service compose file for the API (repo root)
```

Everything needed to build, run, and deploy the API lives in these files —
nothing under `packages/` or any other upstream path is modified.
