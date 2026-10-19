# AgentSwarm 35-Issue Remediation Checklist

This checklist tracks the audit scope against repository evidence. Statuses are
updated only after an implementation and an executable check support the result.

## Initial assessment

| ID | Finding | Initial status | Evidence / planned action |
|---:|---|---|---|
| 1 | `.env` credential exposure | PARTIALLY FIXED | Ignore rules exist; verify tracked files/history and document rotation action without printing secrets. |
| 2 | Vite binds development server to `0.0.0.0` | OPEN | Bind Vite development/preview servers to loopback by default; production nginx remains the external boundary. |
| 3 | `X-Real-IP` trust handling | PARTIALLY FIXED | Tighten trusted-proxy configuration instead of trusting any loopback peer/header combination. |
| 4 | Supabase database role configuration | OPEN | Add startup/readiness validation for PostgreSQL connectivity and required schema/privileges. |
| 5 | Unused PyJWT dependency | OPEN | Confirm imports; remove if unused and regenerate locked dependency metadata. |
| 6 | Missing rate limiting | OPEN | Add atomic per-user/global bounded limits for research, uploads, connectivity, and streams. |
| 7 | PDF upload validation | PARTIALLY FIXED | Add parser timeout/resource bounds and robust malformed-input handling. |
| 8 | Paid provider connectivity tests | PARTIALLY FIXED | Replace process-local cooldown with shared atomic storage and add authenticated quotas. |
| 9 | AI prompt injection | PARTIALLY FIXED | Strengthen untrusted-content framing, evidence validation, and adversarial tests. |
| 10 | Supabase RLS policies | PARTIALLY FIXED | Review migrations, add explicit grants/role checks and deployment validation documentation/tests. |
| 11 | Missing security headers | OPEN | Configure compatible headers at nginx and FastAPI response layers. |
| 12 | Markdown report rendering | ALREADY RESOLVED | `skipHtml` is present; add regression tests for malicious Markdown/links. |
| 13 | Local SQLite database exposure | PARTIALLY FIXED | Ignore rules exist; verify Git state and document local-only use. |
| 14 | `ALLOW_INSECURE_DOCKER_LOCAL_AUTH` | PARTIALLY FIXED | Enforce explicit development-only guard and reject unsafe shared/prod combinations. |
| 15 | Tavily API key handling | PARTIALLY FIXED | Keep server-side, redact logs/errors, and test request payload/header behavior. |
| 16 | Database role validation | OPEN | Implement dependency readiness checks with safe failure details. |
| 17 | Research/document limits and races | PARTIALLY FIXED | Add shared rate/quota reservations and concurrent tests. |
| 18 | LangGraph recursion handling | OPEN | Catch `GraphRecursionError`, persist checkpoint, and return honest incomplete status. |
| 19 | Uploaded-document evidence attribution | OPEN | Attribute pages/passages to all relevant subquestions or explicitly track shared evidence. |
| 20 | Document listing | OPEN | Add authenticated list endpoint, API client, and refresh-persistent UI. |
| 21 | PDF report formatting | OPEN | Render Markdown blocks (headings/lists/emphasis/links/tables) safely to ReportLab. |
| 22 | Event retention | OPEN | Bound event storage/replay while preserving active investigations and audit tail. |
| 23 | Session state loading | OPEN | Add status-only database query and use it for stream/poll/status paths. |
| 24 | Health/readiness endpoints | OPEN | Separate liveness from dependency readiness and avoid sensitive disclosure. |
| 25 | Structured logging | OPEN | Add correlation IDs, structured safe context, and exception trace logging with redaction. |
| 26 | Blocking sleep in async code | OPEN | Replace retry `time.sleep` with async-safe waits and add cancellation regression coverage. |
| 27 | Existing claims reset on follow-up | OPEN | Track evidence/assumption fingerprint and reverify only affected claims while preserving valid prior results. |
| 28 | Source-lock contention | PARTIALLY FIXED | Keep fetches outside lock and reduce critical section with indexed/deduplicated merge logic. |
| 29 | Connectivity cooldown bypass | OPEN | Persist atomic cooldown/quota in database for multi-worker correctness. |
| 30 | SSE reconnection | PARTIALLY FIXED | Use bounded cursor replay, `Last-Event-ID`, dedupe, and reconnect tests. |
| 31 | Report export cleanup | PARTIALLY FIXED | Use `try/finally` cleanup and revoke URLs safely on repeated exports. |
| 32 | Document lifecycle/accessibility | OPEN | Add listing/deletion/active-session states and accessible upload controls. |
| 33 | Routing | OPEN | Validate route IDs, malformed encoding, direct navigation, and browser history behavior. |
| 34 | Event replay/browser performance | OPEN | Add bounded/cursor event API and client windowing/retention. |
| 35 | Frontend report/graph reliability | OPEN | Harden malformed data/loading/error states and add behavior tests. |

## Verification policy

- `FIXED` requires a code change plus a relevant executed test/check.
- `ALREADY RESOLVED` is retained only when existing implementation and tests
  cover the finding; new regression tests may still be added.
- `FALSE POSITIVE` requires repository evidence showing the reported behavior
  cannot occur in the supported deployment.
- `PARTIALLY FIXED` or `BLOCKED` must name the remaining external/manual check.
