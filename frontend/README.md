# AgentSwarm frontend

The React + TypeScript + Vite client for the AgentSwarm evidence-first research lab.
It is deliberately API-backed: the UI does not contain mock sessions, fake graph
movement, fabricated events, or demo source history.

## Requirements

- Node `24.13.0` (the version is pinned in `.nvmrc`)
- The AgentSwarm API running at `http://localhost:8000` for local development

## Setup

```bash
npm ci
cp .env.example .env.local
```

Supabase public URL/key values are only needed when the backend reports
`auth_mode: supabase`. Never put a service-role key in `.env.local`.

## Run

```bash
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to `http://localhost:8000`.

## Test and build

```bash
npm test
npm run build
```

Tests are offline and cover flexible API state mapping, authenticated SSE frame
parsing, event replay deduplication, safe source URLs, citation heading IDs, and
evidence-backed graph relationships.

## Deploy

The included Dockerfile builds the static client with Node 24 and serves it with
nginx:

```bash
docker build -t agentswarm-frontend ./frontend
docker run --rm -p 8080:80 agentswarm-frontend
```

For a deployed environment, configure the nginx `/api/` location or an external
reverse proxy to the backend API. SPA fallback is already enabled. The backend
must enforce ownership for Supabase sessions, stream replay, cancellation,
follow-ups, and exports.

## Backend assumptions

- API paths and state/event records follow `../docs/ARCHITECTURE.md`.
- `GET /api/research/{id}/stream?after=N` is an authenticated `research` SSE stream.
- `GET /api/research/{id}/events` returns the persisted event array used before and
  during reconnect.
- Settings are redacted and may have provider-specific extra fields; the settings
  screen renders unknown safe fields without displaying secret/token/key values.
- The UI treats missing provider credentials as setup errors and leaves the
  backend's actionable message visible.
