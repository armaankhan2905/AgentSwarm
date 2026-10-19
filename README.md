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
ordered migrations in `supabase/migrations/`.

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

Start the backend in one terminal. The explicit loopback bind keeps the
development API off the local network:

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
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

Build the combined image from the repository root. The Dockerfile uses the
pinned Node/Python runtimes, `npm ci`, and `requirements.lock`:

```bash
docker build --pull -t agentswarm .
docker run --rm -p 8080:8080 --env-file .env agentswarm
```

Open <http://localhost:8080>. The image builds the React client, serves it with
non-root nginx on port 8080, and reverse-proxies `/api` to the FastAPI process
on loopback inside the same container. The entrypoint waits for the API
startup lifecycle, including PostgreSQL initialization/recovery, before nginx
starts. The image healthcheck probes the same `/api/health` route through the
proxy.
For a multi-container deployment, use `frontend/Dockerfile` and point its
nginx `/api/` location at the backend service instead.

The combined image refuses `AUTH_MODE=local` unless all three explicit
development controls are present:

```text
AUTH_MODE=local
ALLOW_INSECURE_DOCKER_LOCAL_AUTH=1
APP_ENV=development
DEPLOYMENT_SCOPE=isolated
```

For that isolated case, bind the host port to loopback, for example
`-p 127.0.0.1:8080:8080`. A shared or production deployment must use
`AUTH_MODE=supabase`, `ALLOW_INSECURE_DOCKER_LOCAL_AUTH=0`,
`APP_ENV=production`, and `DEPLOYMENT_SCOPE=shared`. Provide the Supabase
values and use HTTPS at the outer load balancer. HSTS belongs at that TLS
boundary; the internal container listener is HTTP. The bundled nginx upload
limit is 21 MiB, matching the default 20 MiB API limit plus multipart
overhead. The image runs as UID 10001 and keeps nginx temporary files under
`/tmp/nginx`.

Before a shared deployment:

1. Set `AUTH_MODE=supabase`, `APP_ENV=production`,
   `DEPLOYMENT_SCOPE=shared`, and provide the Supabase URL and public anon key.
2. Use a PostgreSQL `DATABASE_URL` for a server-only database role and apply
   migrations `001_initial.sql`, `002_security_hardening.sql`, and
   `003_deployment_privileges.sql`, and `004_rate_limit_buckets.sql` in order.
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
- `TAVILY_API_KEY` is server-only. Do not create a `VITE_TAVILY_API_KEY`, put
  it in `frontend/.env.local`, pass it as a frontend build argument, or expose
  it in browser requests. The API sends it to Tavily server-side.
- `OPENALEX_API_KEY` and `OPENALEX_EMAIL` are optional academic-provider
  enhancements.
- `DATABASE_URL` must point to the migrated PostgreSQL/Supabase database for a
  shared deployment. SQLite is suitable for local development only. The
PostgreSQL runtime role must have `USAGE` on schema `public`, DML privileges
  on every AgentSwarm table, and `USAGE`/`SELECT` on `public.events_id_seq`.
  Do not use the `anon` or `authenticated` roles for this connection. A
  dedicated server role should be non-public and have the RLS bypass required
  for the trusted API worker; never put a service-role JWT in browser code.
- `AUTH_MODE=supabase` requires `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the
  API. The browser may also set the same public URL and anon key as
  `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in
  `frontend/.env.local`; never put an LLM, Tavily, database, or service-role
  secret in that file.
- `CORS_ORIGINS` must list the exact HTTPS frontend origin(s). The `localhost`
  origins in `.env.example` are for local development only.

### PostgreSQL deployment and readiness

Apply the migrations with a database owner/migration role, then run the API
with a server-only PostgreSQL connection role. The migrations revoke table and
schema access from `anon`, `authenticated`, and `public`, retain owner-scoped
RLS policies for authenticated Supabase clients, force RLS on every application
table, and grant server-side DML to Supabase `service_role` plus the migration
role. If the runtime role is separate, grant it the documented schema/table/
sequence privileges before setting `DATABASE_URL`; the API does not perform
schema creation in PostgreSQL.

These checks can be run as the intended runtime role without printing the
connection string or any secret:

```sql
select current_database(), current_user, current_schema();
select has_schema_privilege(current_user, 'public', 'USAGE');
select has_table_privilege(current_user, 'public.sessions', 'SELECT,INSERT,UPDATE,DELETE');
select has_sequence_privilege(current_user, 'public.events_id_seq', 'USAGE,SELECT');
select relname, relrowsecurity, relforcerowsecurity
  from pg_class join pg_namespace on pg_namespace.oid = pg_class.relnamespace
 where nspname = 'public' and relkind = 'r' and relname in
 ('users', 'sessions', 'documents', 'events');
```

Container startup waits for `/api/health` before exposing nginx. API startup
initializes/reconnects the configured database and recovers abandoned work, so
a failed PostgreSQL connection prevents the container from becoming ready.
The Docker healthcheck remains intentionally credential-free and only reports
the service boundary status; monitor PostgreSQL separately for ongoing
dependency health.

## Project layout

- `backend/app/` — FastAPI boundary, storage, provider adapters, and workflow.
- `backend/tests/` — offline API, domain, and workflow tests.
- `frontend/src/` — React/Vite research lab UI.
- `docs/ARCHITECTURE.md` — API, state, record, and security contract.
- `supabase/migrations/` — PostgreSQL schema and RLS policy.
- `Dockerfile` — reproducible combined production image.
- `requirements.lock` / `requirements-dev.lock` — pinned Python dependencies.
