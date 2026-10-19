# AgentSwarm implementation contract

## Acceptance boundary

A research request becomes a persisted plan, real provider searches, stored passages,
auditable claims, conflicts and gaps, bounded follow-up rounds, and a citation-audited
report. Only backend execution events may change workflow status. Test providers live
only in tests. Missing credentials are a setup error, never a demo-data fallback.

## Boundaries

- `backend/app/models.py`, `providers.py`, `workflow.py`: research domain and LangGraph.
- `backend/app/database.py`, `main.py`, `auth.py`: storage, API and ownership.
- `frontend/`: React/Vite/TypeScript client, proxying `/api` in development.
- `backend/tests/`: offline deterministic tests.
- `supabase/migrations/`: PostgreSQL schema and RLS setup.

## Shared Python contract

`from app.models import ResearchRequest` is a Pydantic model with `question` (10–4000
characters), `depth` (`quick|standard|deep`), `source_types` (web/academic/document),
optional `date_from`, `date_to`, `context`, and `document_ids`.

`from app.workflow import ResearchEngine`:

```python
engine = ResearchEngine()
state = await engine.run(
    request=request, session_id=session_id, initial_state=existing_state_or_none,
    emit=emit, checkpoint=checkpoint, cancelled=cancelled,
)
```

`emit(event_type: str, agent: str, message: str, data: dict | None = None)` is async.
`checkpoint(state: dict)` and `cancelled() -> bool` are async. The API owns persistence,
execution jobs, and ownership; the engine owns provider calls and graph execution.
An injected `providers` object supports deterministic tests; never wire test providers
into production. Engine failures must retain the latest checkpoint and be explicit.

JSON state keys: `session_id`, `question`, `request`, `plan`, `sources`, `evidence`,
`claims`, `conflicts`, `gaps`, `report`, `budget`, `follow_ups`, `warnings`, `node_states`,
and `document_ids`. Extracted document pages are loaded only inside the worker and
are never copied into durable session checkpoints.
All collections are arrays; `plan`, `report`, `budget`, `node_states` are objects.

Record shapes (additional documented fields allowed):

- Source: `id`, `title`, `url`, `domain`, `source_type`, `retrieved_at`,
  `publication_date`, `authors`, `doi`, `retrieval_status`, `access_limitations`, `metadata`.
- Passage: `id`, `source_id`, `text`, `location`, `retrieved_at`, `subquestion_id`.
- Claim: `id`, `text`, `subquestion_id`, `status`, `explanation`, `evidence_ids`,
  `contradicting_evidence_ids`, `missing_evidence`, `requires_follow_up`, `verified_at`.
- Conflict: `id`, `description`, `claim_ids`, `source_ids`, `evidence_ids`, `conflict_type`,
  `positions`, `explanation`, `resolved`, `follow_up`.
- Gap: `id`, `title`, `description`, `category` (`EVIDENCE_BACKED|POTENTIAL`),
  `source_ids`, `evidence_ids`, `subquestion_id`, `existing_approaches`, `significance`,
  `opportunity`, `limitations`, `next_steps`.
- Plan: `objective`, `scope`, `subquestions` (objects with `id`, `question`, `priority`,
  `source_types`, `queries`, `evidence_requirements`), `completion_criteria`,
  `known_limitations`, `budget`.
- Report: `title`, `markdown`, `sections` (objects with `id`, `title`, `content`),
  `citation_audit` (`passed`, `warnings`), `created_at`.
- Event: `id`, `session_id`, `event_type`, `agent`, `message`, `data`, `timestamp`.

Claim statuses: SUPPORTED, PARTIALLY_SUPPORTED, CONTRADICTED,
INSUFFICIENT_EVIDENCE, UNVERIFIABLE. Citation labels are source IDs, e.g. `[S1]`.

## API contract

`GET /api/health` health; `GET /api/bootstrap` exposes only auth mode and public
Supabase browser configuration; `GET /api/settings` is authenticated redacted
integration status and limits.
`POST /api/settings/test` performs real connectivity tests, returning safe results.
`POST /api/research` accepts ResearchRequest, returns session with `id` and `status` (202).
`GET /api/research?search=&sort=newest` returns session array.
`GET /api/research/{id}` returns session metadata plus `state` object above.
`GET /api/research/{id}/{plan|sources|claims|conflicts|gaps|report|events}` returns that value.
`GET /api/research/{id}/claims/{claim_id}` returns claim plus `evidence` and `sources`.
`GET /api/research/{id}/stream?after=0` SSE, event name `research`, JSON event.
Use authenticated fetch streaming (not EventSource when auth enabled).
`POST /api/research/{id}/cancel`, `POST /api/research/{id}/follow-up` (`{question}`),
`DELETE /api/research/{id}`. `GET /api/research/{id}/export?format=markdown|pdf` download.
`POST /api/documents` multipart PDF returns owned document `id`, title, pages and
extraction status subject to per-user quotas; `GET /api/documents/{id}` retrieves
owned extracted document; `DELETE /api/documents/{id}` removes an unused owned
document.

Session statuses: queued, running, completed, incomplete, failed, cancelled.
No percent progress unless derived from real completed graph stages.
Missing LLM or selected web provider credentials must reject creation with actionable
503 detail (unless sufficient configured document-only support exists).

## Security / deployment

Local mode is explicitly single-user, loopback-only. When a trusted reverse proxy
is used it must overwrite `X-Real-IP`; `Host` and user-supplied forwarded headers
are never trusted. The public combined Docker image refuses local mode by default.
Supabase mode validates access
tokens with Supabase Auth and checks owner on every route, including stream and export.
PostgreSQL deployment uses Supabase migrations and RLS; browser table DML is revoked
because the backend is the API integrity boundary. Local SQLite supports offline
tests without pretending to be Supabase. No keys are returned from settings. Retrieval
rejects private/link-local/loopback IPs, unsafe schemes and redirects to unsafe hosts.
External content is data only. LLM outputs must be schema-validated and evidence IDs
validated deterministically before they are accepted.
