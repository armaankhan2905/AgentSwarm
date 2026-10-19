# AgentSwarm

AgentSwarm is an evidence-first research lab. A user submits a question, the
backend plans bounded research, retrieves real sources or uploaded documents,
stores passages, verifies claims, maps conflicts and gaps, and renders a
citation-audited report for inspection.

## Requirements

- Python `3.13.5` (pinned in `.python-version`)
- Node `24.13.0` (pinned in `.nvmrc` and `frontend/.nvmrc`)
- GNU Make for the convenience commands below
- Docker for the production image (optional; Docker is not required for local development)

The backend uses SQLite by default, so local development does not require a
database service. PostgreSQL/Supabase deployment is supported through the
existing migration in `supabase/migrations/001_initial.sql`.

## Setup

Create a project-local Python environment and install the pinned development
dependencies:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.lock
npm --prefix frontend ci
cp .env.example .env
cp frontend/.env.example frontend/.env.local
```

On Windows PowerShell, use `.venv\Scripts\python.exe` in place of
`.venv/bin/python`. The `Makefile` is intended for a POSIX shell; the explicit
commands above work in PowerShell as well.

The API can start without provider credentials, but research creation will
return an actionable setup error until the required server-side keys are set in
`.env`. Never put provider secrets in `frontend/.env.local` or browser code.

## Run locally

Start the backend in one terminal:

```bash
make backend-run
```

Start the Vite client in another:

```bash
npm --prefix frontend run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to the backend at
<http://localhost:8000>. Local auth is loopback-only and single-user by design.
The API now exposes only a small unauthenticated `/api/bootstrap` response so a
Supabase browser can discover its login mode; research data and integration
status remain protected.

## Checks

Run the single project check command (portable across Windows, macOS, and Linux):

```bash
python scripts/test.py
```

It runs the offline backend suite and the offline frontend suite. On systems
with GNU Make, `make test` is an equivalent convenience target. The frontend
production build is also available as:

```bash
make build
```

The tests use deterministic provider doubles only inside `backend/tests`; the
runtime never falls back to fabricated research data.

## Deploy with Docker

Build the combined image from the repository root:

```bash
docker build -t agentswarm .
docker run --rm -p 8080:80 --env-file .env agentswarm
```

Open <http://localhost:8080>. The image builds the React client, serves it with
nginx, and reverse-proxies `/api` to the FastAPI process in the same container.
For a multi-container deployment, use `frontend/Dockerfile` and point its
nginx `/api/` location at the backend service instead.

The combined image refuses `AUTH_MODE=local` by default because a public nginx
proxy is not a safe local-auth boundary. Before running the image, set
`AUTH_MODE=supabase`, provide the Supabase values, and use HTTPS at the outer
load balancer. `ALLOW_INSECURE_DOCKER_LOCAL_AUTH=1` is reserved for an isolated
developer machine and must never be used for a shared deployment. The bundled
nginx upload limit is 21 MiB, matching the default 20 MiB API limit plus
multipart overhead.

Before a shared deployment:

1. Set `AUTH_MODE=supabase` and provide the Supabase URL and public anon key.
2. Use a PostgreSQL `DATABASE_URL` and apply the Supabase migration.
3. Configure the LLM and selected search provider credentials only on the API.
4. Keep the browser client on HTTPS and configure the allowed CORS origins.

For a multi-container deployment, the standalone frontend image proxies `/api`
to a service named `backend:8000`; place both containers on the same network or
edit `frontend/nginx.conf` for your service name.

## Credentials and operator configuration

The following values must be entered by the operator in the server `.env` when
the corresponding feature is used:

- `LLM_API_KEY` is required for every research run, plus `LLM_PROVIDER`,
  `LLM_MODEL`, and (if needed) an HTTPS `LLM_BASE_URL`.
- `TAVILY_API_KEY` is required when `web` sources are selected.
- `OPENALEX_API_KEY` and `OPENALEX_EMAIL` are optional academic-provider
  enhancements.
- `DATABASE_URL` must point to the migrated PostgreSQL/Supabase database for a
  shared deployment. SQLite is suitable for local development only.
- `AUTH_MODE=supabase` requires `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the
  API. The browser may also set the same public URL and anon key as
  `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in
  `frontend/.env.local`; never put an LLM, Tavily, database, or service-role
  secret in that file.
- `CORS_ORIGINS` must list the exact HTTPS frontend origin(s). The `localhost`
  origins in `.env.example` are for local development only.

## Project layout

- `backend/app/` — FastAPI boundary, storage, provider adapters, and workflow.
- `backend/tests/` — offline API, domain, and workflow tests.
- `frontend/src/` — React/Vite research lab UI.
- `docs/ARCHITECTURE.md` — API, state, record, and security contract.
- `supabase/migrations/` — PostgreSQL schema and RLS policy.
- `Dockerfile` — reproducible combined production image.
- `requirements.lock` / `requirements-dev.lock` — pinned Python dependencies.
