"""Authenticated research API, durable SSE and bounded background execution."""

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import json
import logging
import os
import re
import time
from typing import Annotated, Literal
from uuid import UUID
from uuid import uuid4
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .auth import Identity, current_user
from .config import Settings, get_settings
from .database import Database, QuotaExceeded, TERMINAL_STATUSES
from .models import ResearchRequest

logger = logging.getLogger(__name__)
User = Annotated[Identity, Depends(current_user)]


class BodyLimitMiddleware:
    """Cap request bytes before parsing while bounding concurrent buffering."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings
        self.upload_slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        upload = scope["path"].rstrip("/") == "/api/documents"
        limit = self.settings.max_upload_bytes + 65536 if upload else self.settings.max_json_bytes
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
        if length > limit:
            return await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
        slot = self.upload_slots if upload else None
        if slot:
            await slot.acquire()
        try:
            body = bytearray()
            while True:
                try:
                    message = await asyncio.wait_for(receive(), self.settings.request_body_timeout_seconds)
                except asyncio.TimeoutError:
                    return await JSONResponse({"detail": "Request body timed out"}, status_code=408)(scope, receive, send)
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > limit:
                    return await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, bounded_receive, send)
        finally:
            if slot:
                slot.release()

    class TooLarge(Exception):
        pass

    class RequestTimeout(Exception):
        pass


def redact(value, settings: Settings):
    """Keep provider errors/events/checkpoints from disclosing server credentials."""
    secrets = [settings.llm_api_key, settings.tavily_api_key, settings.openalex_api_key, settings.supabase_anon_key]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)\bBearer\s+[\w.\-]+", "Bearer [REDACTED]", value)
        return re.sub(r"(?i)([?&](?:api_key|apikey|key|token|access_token)=)[^&#\s]+", r"\1[REDACTED]", value)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if re.fullmatch(r"(?i)(?:api[_-]?key|authorization|password|secret|access[_-]?token)", str(key)) else redact(item, settings)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, settings) for item in value]
    return value


def structured_log(level: int, event: str, settings: Settings, **fields):
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(redact(payload, settings), ensure_ascii=False, separators=(",", ":"), default=str))


class ExecutionManager:
    def __init__(self, app: FastAPI):
        self.app = app
        self.db = app.state.database
        self.semaphore = asyncio.Semaphore(app.state.settings.max_concurrent_sessions)
        self.queue_lock = asyncio.Lock()
        self.tasks: dict[str, asyncio.Task] = {}
        self.stopping = False

    def check_capacity(self, owner_id: str):
        settings = self.app.state.settings
        if self.stopping or len(self.tasks) >= settings.max_queued_sessions:
            raise HTTPException(503, "Research queue is full; retry later", headers={"Retry-After": "10"})
        if self.db.count_active_sessions(owner_id) >= settings.max_active_sessions_per_user:
            raise HTTPException(429, "Your research queue is full; wait for an existing session to finish", headers={"Retry-After": "10"})

    def submit(self, session_id: str):
        task = asyncio.create_task(self.run(session_id), name=f"research-{session_id}")
        self.tasks[session_id] = task

        def finished(done):
            if self.tasks.get(session_id) is done:
                self.tasks.pop(session_id, None)
            if not done.cancelled() and done.exception():
                logger.error("Research task failed (%s)", type(done.exception()).__name__)

        task.add_done_callback(finished)

    async def run(self, session_id: str):
        try:
            async with self.semaphore:
                session = self.db.get_session(session_id)
                if not session or session["status"] != "queued":
                    return
                if not self.db.transition(session_id, "running"):
                    return
                initial_state = session["state"]
                initial_state["documents"] = self.db.documents_for_session(session_id)

                async def emit(event_type: str, agent: str, message: str, data: dict | None = None):
                    payload = redact(data or {}, self.app.state.settings)
                    safe_message = redact(str(message), self.app.state.settings)
                    last_error = None
                    for attempt in range(3):
                        try:
                            self.db.append_event(session_id, str(event_type)[:100], str(agent)[:100], safe_message, payload)
                            return
                        except Exception as exc:
                            last_error = exc
                            if attempt < 2:
                                await asyncio.sleep(0.05 * (attempt + 1))
                    raise last_error

                async def checkpoint(state: dict):
                    snapshot = redact(state, self.app.state.settings)
                    last_error = None
                    for attempt in range(3):
                        try:
                            self.db.checkpoint(session_id, snapshot)
                            return
                        except Exception as exc:
                            last_error = exc
                            if attempt < 2:
                                await asyncio.sleep(0.05 * (attempt + 1))
                    raise last_error

                async def cancelled() -> bool:
                    current = self.db.get_session_status(session_id)
                    return self.stopping or current is None or current["status"] == "cancelled"

                factory = self.app.state.engine_factory
                if factory is None:
                    # Workflow is independently owned and need not exist at API import time.
                    from .workflow import ResearchEngine
                    factory = ResearchEngine
                engine = factory()
                request = ResearchRequest.model_validate(session["request"])
                result = await engine.run(
                    request=request, session_id=session_id, initial_state=initial_state,
                    emit=emit, checkpoint=checkpoint, cancelled=cancelled,
                )
                if not isinstance(result, dict):
                    raise ValueError("Engine returned no checkpoint")
                await checkpoint(result)
                if await cancelled():
                    return
                report = result.get("report") or {}
                complete = bool(report.get("markdown")) and report.get("citation_audit", {}).get("passed") is True
                requested_status = result.get("status")
                if requested_status is not None and requested_status not in TERMINAL_STATUSES:
                    raise ValueError("Engine returned an invalid terminal session status")
                status = "completed" if complete and requested_status not in {"incomplete", "failed", "cancelled"} else "incomplete"
                if requested_status == "failed":
                    status = "failed"
                elif requested_status == "cancelled":
                    status = "cancelled"
                self.db.transition(session_id, status)
        except asyncio.CancelledError:
            await self.safe_transition(session_id, "incomplete", error="Execution interrupted. Latest checkpoint retained; submit a follow-up to continue.")
            raise
        except Exception as exc:
            # Provider exception text may contain request URLs, tokens, or response bodies.
            logger.error("Research execution failed (%s)", type(exc).__name__)
            await self.safe_transition(session_id, "failed", error="Research execution failed. Latest checkpoint retained. Check provider configuration and submit a follow-up to retry.")

    async def safe_transition(self, session_id: str, status: str, *, error: str | None = None):
        """Do not let a reporting failure escape and strand a durable run forever."""
        for attempt in range(3):
            try:
                return self.db.transition(session_id, status, error=error)
            except Exception:
                if attempt == 2:
                    logger.error("Could not persist session %s terminal status", session_id)
                else:
                    await asyncio.sleep(0.05 * (attempt + 1))
        return False

    def cancel(self, session_id: str):
        task = self.tasks.get(session_id)
        if task and not task.done():
            task.cancel()

    async def shutdown(self):
        self.stopping = True
        for session_id, task in list(self.tasks.items()):
            await self.safe_transition(session_id, "incomplete", error="Execution interrupted by server shutdown. Latest checkpoint retained.")
            task.cancel()
        if self.tasks:
            await asyncio.wait(list(self.tasks.values()), timeout=10)


class FollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=10, max_length=4000)

    @field_validator("question")
    @classmethod
    def trimmed(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Question is too short")
        return value


class ConnectivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration: Literal["all", "llm", "tavily", "openalex", "supabase"] = "all"


async def connectivity_test(app: FastAPI, integration: str) -> dict:
    settings, client = app.state.settings, app.state.http
    configured = {
        "llm": bool(settings.llm_api_key), "tavily": bool(settings.tavily_api_key),
        "openalex": True, "supabase": bool(settings.supabase_url and settings.supabase_anon_key),
    }[integration]
    if not configured:
        return {"integration": integration, "ok": False, "status": "not_configured", "message": "Required server configuration is missing"}
    started = time.monotonic()
    try:
        if integration == "llm":
            # A tiny real completion tests the configured model, not just a public health URL.
            if settings.llm_provider == "gemini":
                response = await client.post(
                    f"{settings.llm_base_url}/models/{quote(settings.llm_model, safe='')}:generateContent",
                    headers={"x-goog-api-key": settings.llm_api_key},
                    json={"contents": [{"parts": [{"text": "Reply OK."}]}], "generationConfig": {"maxOutputTokens": 16}},
                    timeout=settings.connectivity_timeout_seconds,
                )
            else:
                response = await client.post(
                    f"{settings.llm_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json={"model": settings.llm_model, "messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 8},
                    timeout=settings.connectivity_timeout_seconds,
                )
        elif integration == "tavily":
            response = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": settings.tavily_api_key, "query": "research", "max_results": 1},
                timeout=settings.connectivity_timeout_seconds,
            )
        elif integration == "openalex":
            params = {"search": "research", "per-page": 1}
            if settings.openalex_api_key:
                params["api_key"] = settings.openalex_api_key
            if settings.openalex_email:
                params["mailto"] = settings.openalex_email
            response = await client.get("https://api.openalex.org/works", params=params, timeout=settings.connectivity_timeout_seconds)
        else:
            response = await client.get(f"{settings.supabase_url}/auth/v1/settings", headers={"apikey": settings.supabase_anon_key}, timeout=settings.connectivity_timeout_seconds)
        if not response.is_success:
            return {"integration": integration, "ok": False, "status": "error", "message": f"Provider rejected connectivity test (HTTP {response.status_code})"}
        body = response.json()
        valid = isinstance(body, dict)
        if integration == "llm":
            valid = valid and bool(body.get("candidates" if settings.llm_provider == "gemini" else "choices"))
        elif integration in {"tavily", "openalex"}:
            valid = valid and isinstance(body.get("results"), list)
        if not valid:
            raise ValueError("Unexpected provider response")
        return {"integration": integration, "ok": True, "status": "connected", "latency_ms": round((time.monotonic() - started) * 1000)}
    except (httpx.HTTPError, ValueError, TypeError):
        return {"integration": integration, "ok": False, "status": "error", "message": "Provider could not be reached or returned an invalid response"}


def extract_pdf(data: bytes, settings: Settings) -> tuple[list[dict], str]:
    if len(data) > settings.max_upload_bytes or len(data) < 8:
        raise HTTPException(422, "Upload is not a valid PDF")
    # PDF headers may be preceded by a bounded binary preamble, but accepting
    # an arbitrary prefix makes file-type checks easy to evade. The EOF check
    # rejects truncated bodies before pypdf allocates parser structures.
    if data[:1024].find(b"%PDF-") < 0 or b"%%EOF" not in data[-1024:]:
        raise HTTPException(422, "Upload is not a valid PDF")
    if len(re.findall(rb"\b\d+\s+\d+\s+obj\b", data)) > settings.max_pdf_objects:
        raise HTTPException(422, "PDF contains too many objects")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise HTTPException(422, "Encrypted PDFs are not supported")
        if not 1 <= len(reader.pages) <= settings.max_pdf_pages:
            raise HTTPException(422, f"PDF must contain 1–{settings.max_pdf_pages} pages")
        pages, total = [], 0
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\x00", "")
            total += len(text)
            if total > settings.max_document_chars:
                raise HTTPException(422, "Extracted PDF text exceeds the document limit")
            pages.append({"page": number, "text": text, "extraction_status": "extracted" if text.strip() else "no_text"})
        status = "extracted" if all(page["text"].strip() for page in pages) else "partial" if any(page["text"].strip() for page in pages) else "no_text"
        return pages, status
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "PDF could not be parsed or its text could not be extracted") from None


def report_pdf(title: str, markdown: str) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output, title=title, author="AgentSwarm", pagesize=(8.5 * inch, 11 * inch))
    styles = getSampleStyleSheet()
    styles["BodyText"].textColor = colors.HexColor("#172033")
    story = []
    for line in markdown.splitlines():
        if not line.strip():
            story.append(Spacer(1, 6))
            continue
        heading = len(line) - len(line.lstrip("#")) if line.startswith("#") else 0
        style = styles["Heading1" if heading == 1 else "Heading2" if heading else "BodyText"]
        text = line[heading:].strip() if heading else line
        # Never interpret retrieved/LLM content as ReportLab XML or remote resources.
        # ReportLab's Paragraph parser accepts a small XML-like language. Escape
        # all report content and drop control characters that can make a valid
        # Markdown export fail during PDF generation.
        text = "".join(char for char in text if char in "\t\r\n" or ord(char) >= 32)
        text = escape(text).replace("\t", "    ")
        story.append(Paragraph(text, style))
    document.build(story)
    return output.getvalue()


def report_markdown(report: dict) -> str:
    """Return a portable Markdown document from current and legacy report shapes."""
    markdown = report.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown.replace("\r\n", "\n").replace("\r", "\n")
    sections = report.get("sections")
    if not isinstance(sections, list):
        return ""
    rendered = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "Section").strip()
        content = section.get("content")
        if not isinstance(content, str):
            content = ""
        content = content.strip()
        if title or content:
            rendered.append(f"## {title}\n\n{content}".rstrip())
    return "\n\n".join(rendered)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database(
        settings.database_url,
        event_replay_limit=settings.event_replay_limit,
        event_audit_tail=settings.event_audit_tail,
    )

    # Current provider adapters read their integration credentials directly from the
    # agreed environment names. Keep this compatibility bridge in the API boundary;
    # provider ownership remains in providers.py.
    if settings.llm_provider == "gemini":
        if settings.llm_api_key:
            os.environ["GEMINI_API_KEY"] = settings.llm_api_key
    else:
        if settings.llm_api_key:
            os.environ["OPENAI_API_KEY"] = settings.llm_api_key
        if settings.llm_base_url:
            os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
    os.environ["LLM_PROVIDER"] = settings.llm_provider
    os.environ["LLM_MODEL"] = settings.llm_model
    if settings.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = settings.tavily_api_key
    if settings.openalex_api_key:
        os.environ["OPENALEX_API_KEY"] = settings.openalex_api_key
    if settings.openalex_email:
        os.environ["OPENALEX_EMAIL"] = settings.openalex_email

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        database.recover_abandoned()
        app.state.http = httpx.AsyncClient(follow_redirects=False, trust_env=False)
        app.state.execution = ExecutionManager(app)
        app.state.pdf_semaphore = asyncio.Semaphore(settings.max_pdf_concurrency)
        try:
            yield
        finally:
            await app.state.execution.shutdown()
            await app.state.http.aclose()
            database.engine.dispose()

    app = FastAPI(title="AgentSwarm API", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.database = settings, database
    app.state.engine_factory = None
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type", "Last-Event-ID"], expose_headers=["Content-Disposition"])

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", supplied) else str(uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            structured_log(
                logging.ERROR,
                "request_failed",
                settings,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            raise
        response.headers["X-Request-ID"] = request_id
        structured_log(
            logging.INFO,
            "request_completed",
            settings,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI's default includes raw invalid input and exception context.
        errors = [{"loc": error["loc"], "type": error["type"], "msg": "Invalid request value"} for error in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        structured_log(
            logging.ERROR,
            "api_exception",
            settings,
            request_id=getattr(request.state, "request_id", ""),
            exception_type=type(exc).__name__,
        )
        return JSONResponse({"detail": "The server could not complete this request"}, status_code=500)

    def owned_session(session_id: str, user: Identity) -> dict:
        try:
            session_id = str(UUID(session_id))
        except ValueError:
            raise HTTPException(404, "Research session not found") from None
        value = database.get_session(session_id, user.id)
        if value is None:
            raise HTTPException(404, "Research session not found")
        return value

    def owned_session_status(session_id: str, user: Identity) -> dict:
        try:
            session_id = str(UUID(session_id))
        except ValueError:
            raise HTTPException(404, "Research session not found") from None
        value = database.get_session_status(session_id, user.id)
        if value is None:
            raise HTTPException(404, "Research session not found")
        return value

    def owned_document(document_id: str, user: Identity) -> dict:
        try:
            document_id = str(UUID(document_id))
        except ValueError:
            raise HTTPException(404, "Document not found") from None
        value = database.get_document(document_id, user.id)
        if value is None:
            raise HTTPException(404, "Document not found")
        return value

    def provider_ready(source_types: list[str]):
        missing = settings.missing_credentials(source_types)
        if missing:
            raise HTTPException(503, "Configure required server credentials: " + ", ".join(missing))

    def quota_http_error(exc: QuotaExceeded) -> HTTPException:
        status = 503 if "queue is full" in str(exc).lower() else 429
        return HTTPException(status, str(exc), headers={"Retry-After": "10"})

    def enforce_rate_limit(key: str, *, limit: int, window_seconds: float, message: str):
        decision = database.consume_rate_limit(key, limit=limit, window_seconds=window_seconds)
        if not decision.allowed:
            raise HTTPException(429, message, headers={"Retry-After": str(decision.retry_after)})

    async def allow_connectivity_test(user_id: str):
        enforce_rate_limit(
            f"connectivity:{user_id}",
            limit=1,
            window_seconds=settings.connectivity_cooldown_seconds,
            message="Connectivity tests are rate-limited; retry later",
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/readiness")
    async def readiness():
        checks = {"database": "ok", "configuration": "ok"}
        try:
            database.readiness()
        except Exception:
            checks["database"] = "unavailable"
        ready = all(value == "ok" for value in checks.values())
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "checks": checks},
            status_code=200 if ready else 503,
        )

    @app.get("/api/bootstrap")
    async def bootstrap():
        # These values are public Supabase client configuration, not service
        # credentials. Keeping auth mode outside the protected settings route
        # prevents a fresh browser from getting stuck before login.
        return {
            "auth_mode": settings.auth_mode,
            "supabase_url": settings.supabase_url if settings.auth_mode == "supabase" else "",
            "supabase_anon_key": settings.supabase_anon_key if settings.auth_mode == "supabase" else "",
        }

    @app.get("/api/settings")
    async def public_settings(user: User):
        return redact(settings.public_status(), settings)

    @app.post("/api/settings/test")
    async def test_settings(user: User, body: ConnectivityRequest | None = None):
        await allow_connectivity_test(user.id)
        integration = body.integration if body else "all"
        names = ["llm", "tavily", "openalex", "supabase"] if integration == "all" else [integration]
        return await asyncio.gather(*(connectivity_test(app, name) for name in names))

    @app.post("/api/research", status_code=202)
    async def start_research(body: ResearchRequest, user: User):
        documents = [owned_document(document_id, user) for document_id in dict.fromkeys(body.document_ids)]
        if "document" in body.source_types and not documents:
            raise HTTPException(422, "Document research requires at least one owned PDF document")
        if body.source_types == ["document"] and not any(page["text"].strip() for doc in documents for page in doc["pages"]):
            raise HTTPException(422, "The selected PDFs contain no extractable text; OCR is required")
        selected_chars = sum(
            int(document.get("text_chars") or sum(
                len(page.get("text", "")) for page in document.get("pages", [])
                if isinstance(page, dict) and isinstance(page.get("text"), str)
            ))
            for document in documents
        )
        if selected_chars > settings.max_selected_document_chars:
            raise HTTPException(413, "Selected documents exceed the aggregate extracted-text limit")
        provider_ready(body.source_types)
        enforce_rate_limit(
            f"research:{user.id}",
            limit=settings.research_rate_limit,
            window_seconds=settings.research_rate_window_seconds,
            message="Research creation is rate-limited; retry later",
        )
        async with app.state.execution.queue_lock:
            app.state.execution.check_capacity(user.id)
            try:
                session = database.create_session(
                    user.id, body.model_dump(mode="json"), documents,
                    max_active_sessions=settings.max_active_sessions_per_user,
                    max_total_sessions=settings.max_total_sessions_per_user,
                    max_queued_sessions=settings.max_queued_sessions,
                )
            except QuotaExceeded as exc:
                raise quota_http_error(exc) from None
            app.state.execution.submit(session["id"])
        return redact(session, settings)

    @app.get("/api/research")
    async def history(user: User, search: str = Query(default="", max_length=4000), sort: Literal["newest", "oldest", "updated"] = "newest", limit: int = Query(default=100, ge=1, le=500)):
        return redact(database.list_sessions(user.id, search, sort, min(limit, settings.max_history_items)), settings)

    @app.get("/api/research/{session_id}")
    async def get_research(session_id: str, user: User):
        return redact(owned_session(session_id, user), settings)

    @app.post("/api/research/{session_id}/cancel")
    async def cancel_research(session_id: str, user: User):
        session = owned_session(session_id, user)
        if database.transition(session["id"], "cancelled"):
            app.state.execution.cancel(session["id"])
        return redact(owned_session(session["id"], user), settings)

    @app.post("/api/research/{session_id}/follow-up", status_code=202)
    async def followup(session_id: str, body: FollowupRequest, user: User):
        session = owned_session(session_id, user)
        if session["status"] not in TERMINAL_STATUSES or session["id"] in app.state.execution.tasks:
            raise HTTPException(409, "Wait for the current execution to stop before submitting a follow-up")
        provider_ready(session["request"]["source_types"])
        async with app.state.execution.queue_lock:
            app.state.execution.check_capacity(user.id)
            try:
                updated = database.queue_followup(
                    session["id"], body.question,
                    max_active_sessions=settings.max_active_sessions_per_user,
                    max_queued_sessions=settings.max_queued_sessions,
                )
            except QuotaExceeded as exc:
                raise quota_http_error(exc) from None
            if updated is None:
                raise HTTPException(409, "This session is already executing")
            app.state.execution.submit(session["id"])
        return redact(updated, settings)

    @app.delete("/api/research/{session_id}", status_code=204)
    async def delete_research(session_id: str, user: User):
        session = owned_session(session_id, user)
        app.state.execution.cancel(session["id"])
        database.delete_session(session["id"])
        return Response(status_code=204)

    @app.get("/api/research/{session_id}/stream")
    async def stream(session_id: str, request: Request, user: User, after: int = Query(default=0, ge=0, le=2147483647)):
        session = owned_session_status(session_id, user)
        cursor = request.headers.get("last-event-id")
        if cursor is not None:
            try:
                after = max(after, int(cursor))
                if not 0 <= int(cursor) <= 2147483647:
                    raise ValueError
            except ValueError:
                raise HTTPException(400, "Last-Event-ID must be a nonnegative integer") from None

        async def generate():
            nonlocal after
            heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                current = database.get_session_status(session["id"], user.id)
                if current is None:
                    return
                batch = database.events(session["id"], after, limit=settings.event_replay_limit)
                for item in batch:
                    after = item["id"]
                    payload = json.dumps(redact(item, settings), ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {after}\nevent: research\ndata: {payload}\n\n"
                if len(batch) == settings.event_replay_limit:
                    continue
                if current["status"] in TERMINAL_STATUSES:
                    return
                if time.monotonic() - heartbeat >= 15:
                    heartbeat = time.monotonic()
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/research/{session_id}/export")
    async def export(session_id: str, user: User, format: Literal["markdown", "pdf"] = "markdown"):
        session = owned_session(session_id, user)
        report = redact(session["state"].get("report") or {}, settings)
        markdown = report_markdown(report)
        if not markdown:
            raise HTTPException(409, "No persisted report is available for export")
        filename = f"agentswarm-{session['id']}"
        if format == "markdown":
            return Response(markdown, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}.md"'})
        data = await asyncio.to_thread(report_pdf, report.get("title", "Research report"), markdown)
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})

    @app.get("/api/research/{session_id}/claims/{claim_id}")
    async def claim_detail(session_id: str, claim_id: str, user: User):
        state = owned_session(session_id, user)["state"]
        claim = next((item for item in state.get("claims", []) if item["id"] == claim_id), None)
        if claim is None:
            raise HTTPException(404, "Claim not found")
        ids = set(claim.get("evidence_ids", []) + claim.get("contradicting_evidence_ids", []))
        evidence = [item for item in state.get("evidence", []) if item["id"] in ids]
        source_ids = {item["source_id"] for item in evidence}
        sources = [item for item in state.get("sources", []) if item["id"] in source_ids]
        return redact({**claim, "evidence": evidence, "sources": sources}, settings)

    @app.get("/api/research/{session_id}/{resource}")
    async def child_resource(
        session_id: str,
        resource: str,
        user: User,
        after: int = Query(default=0, ge=0, le=2147483647),
        limit: int = Query(default=250, ge=1, le=5000),
    ):
        if resource == "events":
            session = owned_session_status(session_id, user)
            return redact(database.events(session["id"], after=after, limit=min(limit, settings.event_replay_limit)), settings)
        session = owned_session(session_id, user)
        if resource not in {"plan", "sources", "claims", "conflicts", "gaps", "report"}:
            raise HTTPException(404, "Resource not found")
        return redact(session["state"].get(resource, {} if resource in {"plan", "report"} else []), settings)

    @app.post("/api/documents", status_code=201)
    async def upload_document(user: User, file: UploadFile = File(...)):
        try:
            if file.content_type not in {"application/pdf", "application/octet-stream"}:
                raise HTTPException(415, "Only PDF uploads are supported")
            enforce_rate_limit(
                f"upload:{user.id}",
                limit=settings.upload_rate_limit,
                window_seconds=settings.upload_rate_window_seconds,
                message="PDF uploads are rate-limited; retry later",
            )
            data = await file.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                raise HTTPException(413, "PDF exceeds the upload size limit")
            async with app.state.pdf_semaphore:
                try:
                    pages, status = await asyncio.wait_for(
                        asyncio.to_thread(extract_pdf, data, settings),
                        timeout=settings.pdf_parse_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    raise HTTPException(422, "PDF parsing timed out") from None
            # The original filename is display text only; no upload ever becomes a path.
            title = (file.filename or "Untitled PDF").replace("\\", "/").rsplit("/", 1)[-1]
            title = "".join(char for char in title if char.isprintable())[:200] or "Untitled PDF"
            try:
                document = database.add_document(
                    user.id, title, pages, status, len(data),
                    max_documents=settings.max_documents_per_user,
                    max_bytes=settings.max_document_bytes_per_user,
                    max_chars=settings.max_document_chars_per_user,
                )
            except QuotaExceeded as exc:
                raise HTTPException(413, str(exc)) from None
            return redact(document, settings)
        finally:
            await file.close()

    @app.get("/api/documents")
    async def list_documents(user: User, limit: int = Query(default=1000, ge=1, le=1000)):
        return redact(database.list_documents(user.id, min(limit, settings.max_documents_per_user)), settings)

    @app.get("/api/documents/{document_id}")
    async def get_document(document_id: str, user: User):
        return redact(owned_document(document_id, user), settings)

    @app.delete("/api/documents/{document_id}", status_code=204)
    async def delete_document(document_id: str, user: User):
        try:
            document_id = str(UUID(document_id))
        except ValueError:
            raise HTTPException(404, "Document not found") from None
        try:
            deleted = database.delete_document(document_id, user.id)
        except QuotaExceeded as exc:
            raise HTTPException(409, str(exc)) from None
        if not deleted:
            raise HTTPException(404, "Document not found")
        return Response(status_code=204)

    return app


app = create_app()
