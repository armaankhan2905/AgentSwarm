"""Offline API/storage boundary tests. Synthetic engines/transports exist only here."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
import logging
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import func, select

from app.auth import LOCAL_USER_ID
from app.config import Settings
from app.database import (
    Claim, Conflict, Database, Document, Evidence, Followup, Gap, Plan,
    RateLimitBucket, Relationship, Report, ResearchEvent, ResearchSession, Source, Task,
)
from app.main import create_app


QUESTION = "What evidence supports energy storage research?"
REQUEST = {"question": QUESTION, "source_types": ["academic"], "depth": "quick"}


def config(tmp_path, **overrides):
    values = {
        "_env_file": None, "database_url": f"sqlite:///{(tmp_path / 'api.sqlite').as_posix()}",
        "auth_mode": "local", "cors_origins": "http://localhost:5173",
        "llm_provider": "openai", "llm_model": "test-model", "llm_api_key": "test-llm-secret",
        "llm_base_url": "https://llm.example/v1", "tavily_api_key": "test-web-secret",
        "openalex_api_key": "", "openalex_email": "", "supabase_url": "", "supabase_anon_key": "",
        "max_concurrent_sessions": 2, "max_queued_sessions": 100,
    }
    values.update(overrides)
    return Settings(**values)


def research_state(initial):
    state = deepcopy(initial)
    state.update(
        plan={"objective": QUESTION, "scope": "Storage", "subquestions": [{"id": "Q1", "question": "Which finding is supported?", "priority": 1, "source_types": ["academic"], "queries": ["storage"], "evidence_requirements": ["A passage"]}], "completion_criteria": ["Assess a finding"], "known_limitations": [], "budget": {}},
        sources=[{"id": "S1", "title": "A study", "url": "https://example.org/study", "domain": "example.org", "source_type": "academic", "retrieved_at": "2026-01-01T00:00:00Z", "publication_date": None, "authors": [], "doi": None, "retrieval_status": "retrieved", "access_limitations": [], "metadata": {}}],
        evidence=[{"id": "E1", "source_id": "S1", "text": "Storage may improve reliability.", "location": {"page": 1}, "retrieved_at": "2026-01-01T00:00:00Z", "subquestion_id": "Q1"}],
        claims=[{"id": "C1", "text": "Storage may improve reliability.", "subquestion_id": "Q1", "status": "SUPPORTED", "explanation": "Exact retrieved evidence", "evidence_ids": ["E1"], "contradicting_evidence_ids": [], "missing_evidence": [], "requires_follow_up": False, "verified_at": "2026-01-01T00:00:00Z"}],
        conflicts=[{"id": "X1", "description": "A remaining disagreement", "claim_ids": ["C1"], "source_ids": ["S1"], "evidence_ids": ["E1"], "conflict_type": "scope", "positions": ["Narrow scope"], "explanation": "Further work needed", "resolved": False, "follow_up": "Check scope"}],
        gaps=[{"id": "G1", "title": "Scope", "description": "Broader scope remains untested", "category": "POTENTIAL", "source_ids": ["S1"], "evidence_ids": ["E1"], "subquestion_id": "Q1", "existing_approaches": [], "significance": "Unknown", "opportunity": "Study scope", "limitations": [], "next_steps": ["Retrieve more evidence"]}],
        report={"title": "Persisted report", "markdown": "# Persisted report\n\nStorage may improve reliability. [S1]\n\n<untrusted & text>", "sections": [], "citation_audit": {"passed": True, "warnings": []}, "created_at": "2026-01-01T00:00:00Z"},
        budget={"used": {"searches": 1}}, node_states={"planner": {"status": "completed"}}, status="completed",
    )
    return state


class CompleteEngine:
    async def run(self, *, request, session_id, initial_state, emit, checkpoint, cancelled):
        assert request.question == QUESTION
        assert session_id == initial_state["session_id"]
        state = research_state(initial_state)
        await checkpoint(state)
        await emit("node_completed", "planner", "Real boundary checkpoint", {"subquestion_id": "Q1"})
        return state


@pytest.fixture
def api(tmp_path):
    app = create_app(config(tmp_path))
    app.state.engine_factory = CompleteEngine
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        yield client, app


def wait_status(client, session_id, expected=None):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        result = client.get(f"/api/research/{session_id}")
        assert result.status_code == 200, result.text
        session = result.json()
        if session["status"] in (expected or {"completed", "incomplete", "cancelled", "failed"}):
            return session
        time.sleep(0.01)
    pytest.fail(f"Session did not reach expected status: {session}")


def start(client):
    response = client.post("/api/research", json=REQUEST)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def pdf_bytes(*pages):
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for text in pages:
        if text:
            canvas.drawString(40, 700, text)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def test_create_persisted_entities_children_claims_and_export(api):
    client, app = api
    session_id = start(client)
    session = wait_status(client, session_id)
    assert session["status"] == "completed"
    assert session["state"]["status"] == "completed"
    for collection in ("sources", "claims", "conflicts", "gaps", "events"):
        response = client.get(f"/api/research/{session_id}/{collection}")
        assert response.status_code == 200
        assert isinstance(response.json(), list) and response.json()
    assert client.get(f"/api/research/{session_id}/plan").json()["objective"] == QUESTION
    detail = client.get(f"/api/research/{session_id}/claims/C1").json()
    assert detail["evidence"][0]["source_id"] == detail["sources"][0]["id"] == "S1"
    assert client.get(f"/api/research/{session_id}/claims/unknown").status_code == 404
    assert client.get(f"/api/research/{session_id}/unknown").status_code == 404
    history = client.get("/api/research", params={"search": "energy storage", "sort": "newest"}).json()
    assert isinstance(history, list) and history[0]["id"] == session_id
    assert client.get("/api/research?search=unmatched").json() == []
    assert client.get("/api/research?search=%").json() == []  # LIKE wildcard is literal.
    markdown = client.get(f"/api/research/{session_id}/export?format=markdown")
    assert markdown.text == session["state"]["report"]["markdown"]
    pdf = client.get(f"/api/research/{session_id}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert "attachment" in pdf.headers["content-disposition"]
    legacy = deepcopy(session["state"])
    legacy["report"] = {"title": "Legacy report", "sections": [{"title": "Findings", "content": "A stored section."}]}
    app.state.database.checkpoint(session_id, legacy)
    markdown = client.get(f"/api/research/{session_id}/export?format=markdown")
    assert markdown.status_code == 200 and markdown.text == "## Findings\n\nA stored section."
    pdf = client.get(f"/api/research/{session_id}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    with app.state.database.sessions() as db:
        for model in (Plan, Task, Source, Evidence, Claim, Conflict, Gap, Relationship, Report):
            assert db.scalar(select(func.count()).select_from(model).where(model.session_id == session_id)) > 0


def test_events_are_persisted_sse_replays_only_after_cursor(api):
    client, _ = api
    session_id = start(client)
    wait_status(client, session_id)
    events = client.get(f"/api/research/{session_id}/events").json()
    cursor = events[0]["id"]
    stream = client.get(f"/api/research/{session_id}/stream?after={cursor}")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    frames = stream.text.strip().split("\n\n")
    replay = [json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: "))) for frame in frames]
    assert replay == events[1:]
    assert all("event: research" in frame for frame in frames)
    assert client.get(f"/api/research/{session_id}/stream", headers={"Last-Event-ID": str(events[-1]["id"])}).text == ""
    assert client.get(f"/api/research/{session_id}/stream", headers={"Last-Event-ID": "bad"}).status_code == 400


def test_exception_retains_latest_checkpoint_and_sanitizes_secrets(api):
    client, app = api

    class FailingEngine:
        async def run(self, *, initial_state, checkpoint, emit, **kwargs):
            state = research_state(initial_state)
            state["report"] = {}
            state["warnings"] = ["test-llm-secret"]
            await checkpoint(state)
            await emit("provider_error", "web", "test-web-secret", {"api_key": "unrelated-secret"})
            raise RuntimeError("test-llm-secret https://private.example?token=secret")

    app.state.engine_factory = FailingEngine
    session_id = start(client)
    result = wait_status(client, session_id)
    assert result["status"] == "failed"
    assert result["state"]["claims"][0]["id"] == "C1"
    assert result["state"]["warnings"] == ["[REDACTED]"]
    body = json.dumps(result) + client.get(f"/api/research/{session_id}/events").text
    assert "test-llm-secret" not in body and "test-web-secret" not in body and "unrelated-secret" not in body
    assert client.get(f"/api/research/{session_id}/export").status_code == 409


def test_provider_failure_can_be_recovered_by_followup_from_checkpoint(api):
    client, app = api
    calls = 0

    class ProviderFailureThenRecovery:
        async def run(self, *, initial_state, checkpoint, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                state = research_state(initial_state)
                state["report"] = {}
                await checkpoint(state)
                raise RuntimeError("temporary provider outage")
            return await CompleteEngine().run(initial_state=initial_state, checkpoint=checkpoint, **kwargs)

    app.state.engine_factory = ProviderFailureThenRecovery
    session_id = start(client)
    failed = wait_status(client, session_id)
    assert failed["status"] == "failed"
    response = client.post(f"/api/research/{session_id}/follow-up", json={"question": "Can the failed investigation be retried?"})
    assert response.status_code == 202, response.text
    recovered = wait_status(client, session_id)
    assert recovered["status"] == "completed"
    assert calls == 2


def test_transient_database_checkpoint_failure_is_retried(api):
    client, app = api
    original = app.state.database.checkpoint
    attempts = 0

    def flaky_checkpoint(session_id, state):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary database outage")
        return original(session_id, state)

    app.state.database.checkpoint = flaky_checkpoint
    session_id = start(client)
    result = wait_status(client, session_id)
    assert result["status"] == "completed"
    assert attempts >= 2


def test_failed_checkpoint_rolls_back_entities_and_snapshot(api):
    client, app = api

    class InvalidCheckpointEngine:
        async def run(self, *, initial_state, checkpoint, **kwargs):
            state = research_state(initial_state)
            await checkpoint(state)
            state["evidence"][0]["source_id"] = "missing-source"
            await checkpoint(state)

    app.state.engine_factory = InvalidCheckpointEngine
    session_id = start(client)
    result = wait_status(client, session_id)
    assert result["status"] == "failed"
    assert result["state"]["evidence"][0]["source_id"] == "S1"
    assert client.get(f"/api/research/{session_id}/claims/C1").json()["sources"][0]["id"] == "S1"
    with app.state.database.sessions() as db:
        assert db.get(Evidence, (session_id, "E1")).source_id == "S1"


def test_cancellation_wins_over_late_engine_checkpoint(api):
    client, app = api

    class LateCheckpointEngine:
        async def run(self, *, initial_state, checkpoint, emit, **kwargs):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                state = research_state(initial_state)
                await checkpoint(state)
                await emit("research_completed", "engine", "Late completion")
                return state

    app.state.engine_factory = LateCheckpointEngine
    session_id = start(client)
    wait_status(client, session_id, {"running"})
    response = client.post(f"/api/research/{session_id}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    result = wait_status(client, session_id)
    assert result["state"]["status"] == "cancelled"
    events = client.get(f"/api/research/{session_id}/events").json()
    assert events[-1]["event_type"] == "session_cancelled"
    assert not any(item["event_type"] == "research_completed" for item in events)


def test_followup_receives_saved_state_and_preserves_budget(api):
    client, app = api
    session_id = start(client)
    first = wait_status(client, session_id)
    seen = []

    class FollowupEngine:
        async def run(self, *, initial_state, **kwargs):
            seen.append(deepcopy(initial_state))
            initial_state.pop("follow_up_question")
            return initial_state

    app.state.engine_factory = FollowupEngine
    response = client.post(f"/api/research/{session_id}/follow-up", json={"question": "What remains uncertain about scope?"})
    assert response.status_code == 202
    wait_status(client, session_id)
    assert seen[0]["follow_up_question"] == "What remains uncertain about scope?"
    assert seen[0]["budget"] == first["state"]["budget"]
    assert seen[0]["claims"] == first["state"]["claims"]
    with app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Followup).where(Followup.session_id == session_id)) == 1


def test_pdf_upload_page_extraction_and_document_input(api):
    client, app = api
    response = client.post("/api/documents", files={"file": ("../../study.pdf", pdf_bytes("First page evidence.", "Second page evidence."), "application/pdf")})
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["title"] == "study.pdf"
    assert document["extraction_status"] == "extracted"
    assert [page["page"] for page in document["pages"]] == [1, 2]
    assert "Second page evidence." in document["pages"][1]["text"]
    assert client.get("/api/documents").json() == [document]
    assert client.get(f"/api/documents/{document['id']}").json() == document
    inputs = []

    class DocumentEngine(CompleteEngine):
        async def run(self, **kwargs):
            inputs.extend(kwargs["initial_state"]["documents"])
            return await super().run(**kwargs)

    app.state.engine_factory = DocumentEngine
    result = client.post("/api/research", json={**REQUEST, "source_types": ["document"], "document_ids": [document["id"]]})
    assert result.status_code == 202
    session = wait_status(client, result.json()["id"])
    assert inputs == [document]
    assert "documents" not in session["state"]


def test_bootstrap_is_public_but_local_proxy_spoof_is_rejected(tmp_path):
    app = create_app(config(tmp_path))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        bootstrap = client.get("/api/bootstrap")
        assert bootstrap.status_code == 200 and bootstrap.json()["auth_mode"] == "local"
        assert client.get("/api/settings", headers={"Host": "localhost", "X-Real-IP": "203.0.113.10"}).status_code == 403


def test_document_ids_cannot_be_smuggled_into_non_document_research(api):
    client, _ = api
    document = client.post("/api/documents", files={"file": ("study.pdf", pdf_bytes("Evidence"), "application/pdf")}).json()
    response = client.post("/api/research", json={**REQUEST, "document_ids": [document["id"]]})
    assert response.status_code == 422


def test_real_engine_document_flow_uses_shared_callbacks_and_persistence(api):
    from app.providers import LLMResult
    from app.workflow import ResearchEngine

    client, app = api

    class DocumentProviders:
        async def structured(self, role, prompt, schema, max_tokens):
            data = json.loads(prompt)
            if role == "planner":
                result = research_state({})["plan"]
                result["subquestions"][0]["source_types"] = ["document"]
            elif role == "extractor":
                passage = data["passages"][0]
                result = {"claims": [{"text": "Storage may improve reliability.", "subquestion_id": "Q1", "quotes": [{"evidence_id": passage["id"], "excerpt": "Storage may improve reliability."}]}]}
            elif role == "semantic_verifier":
                result = {"verdicts": [{"claim_id": claim["id"], "status": "SUPPORTED", "explanation": "Exact qualified passage", "supporting_quotes": claim["quotes"], "contradicting_quotes": [], "missing_evidence": [], "requires_follow_up": False} for claim in data["claims"]]}
            elif role == "conflict_analyst":
                result = {"conflicts": []}
            elif role == "gap_analyst":
                result = {"gaps": [], "complete": True, "explanation": "The requested finding has retrieved support", "follow_up_queries": []}
            elif role == "report_writer":
                result = {"title": "Findings", "sections": [{"id": "findings", "title": "Findings", "content": "", "claim_ids": [claim["id"] for claim in data["claims"]]}]}
            else:
                raise AssertionError(f"Unexpected role: {role}")
            return LLMResult(schema.model_validate(result).model_dump(mode="json"), 10, 10)

    app.state.engine_factory = lambda: ResearchEngine(providers=DocumentProviders())
    document = client.post("/api/documents", files={"file": ("evidence.pdf", pdf_bytes("Storage may improve reliability."), "application/pdf")}).json()
    response = client.post("/api/research", json={**REQUEST, "source_types": ["document"], "document_ids": [document["id"]]})
    assert response.status_code == 202, response.text
    result = wait_status(client, response.json()["id"])
    assert result["status"] == "completed", result
    assert result["state"]["sources"][0]["source_type"] == "document"
    assert result["state"]["evidence"][0]["location"]["page"] == 1
    assert result["state"]["report"]["citation_audit"]["passed"] is True
    assert "[S1]" in result["state"]["report"]["markdown"]
    events = client.get(f"/api/research/{result['id']}/events").json()
    assert any(event["event_type"] == "citation_audit_completed" for event in events)


@pytest.mark.parametrize("data,content_type,expected", [(b"not pdf", "application/pdf", 422), (b"%PDF-broken", "application/pdf", 422), (b"fake", "text/plain", 415)])
def test_rejects_invalid_pdf(api, data, content_type, expected):
    client, _ = api
    assert client.post("/api/documents", files={"file": ("study.pdf", data, content_type)}).status_code == expected


def test_pdf_page_size_and_empty_text_limits(tmp_path):
    app = create_app(config(tmp_path, max_upload_bytes=4096, max_pdf_pages=1))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.post("/api/documents", files={"file": ("large.pdf", b"%PDF-" + b"x" * 4096, "application/pdf")}).status_code == 413
        assert client.post("/api/documents", files={"file": ("pages.pdf", pdf_bytes("One", "Two"), "application/pdf")}).status_code == 422
        blank = client.post("/api/documents", files={"file": ("blank.pdf", pdf_bytes(""), "application/pdf")}).json()
        assert blank["extraction_status"] == "no_text"
        response = client.post("/api/research", json={**REQUEST, "source_types": ["document"], "document_ids": [blank["id"]]})
        assert response.status_code == 422


def test_pdf_resource_signature_and_object_limits(tmp_path):
    app = create_app(config(tmp_path, max_pdf_objects=100))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        body = b"%PDF-1.7\n" + (b"1 0 obj\n" * 101) + b"%%EOF"
        response = client.post("/api/documents", files={"file": ("objects.pdf", body, "application/pdf")})
        assert response.status_code == 422 and "objects" in response.text


def test_health_readiness_and_redacted_request_correlation(tmp_path, caplog):
    app = create_app(config(tmp_path))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        ready = client.get("/api/readiness", headers={"X-Request-ID": "trace-123"})
        assert ready.status_code == 200
        assert ready.headers["x-request-id"] == "trace-123"
        assert ready.json() == {"status": "ready", "checks": {"database": "ok", "configuration": "ok"}}
        with caplog.at_level(logging.INFO, logger="app.main"):
            client.get("/api/settings", headers={"X-Request-ID": "safe-trace"})
        assert "request_completed" in caplog.text
        assert "test-llm-secret" not in caplog.text
        app.state.database.readiness = lambda: (_ for _ in ()).throw(RuntimeError("database-password"))
        unavailable = client.get("/api/readiness")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"status": "not_ready", "checks": {"database": "unavailable", "configuration": "ok"}}
        assert "database-password" not in unavailable.text


def test_database_rate_limit_is_atomic_across_workers(tmp_path):
    url = f"sqlite:///{(tmp_path / 'shared.sqlite').as_posix()}"
    databases = [Database(url) for _ in range(4)]
    databases[0].initialize()
    with ThreadPoolExecutor(max_workers=12) as pool:
        decisions = list(pool.map(
            lambda index: databases[index % len(databases)].consume_rate_limit(
                "research:shared-user", limit=3, window_seconds=60
            ),
            range(24),
        ))
    assert sum(decision.allowed for decision in decisions) == 3
    assert all(decision.retry_after > 0 for decision in decisions if not decision.allowed)
    with databases[0].sessions() as db:
        assert db.scalar(select(func.count()).select_from(RateLimitBucket)) == 1
    for database in databases:
        database.engine.dispose()


def test_research_and_upload_limits_are_shared_api_boundaries(tmp_path):
    app = create_app(config(tmp_path, research_rate_limit=1, upload_rate_limit=1))
    app.state.engine_factory = CompleteEngine
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        first = client.post("/api/research", json=REQUEST)
        assert first.status_code == 202
        limited_research = client.post("/api/research", json=REQUEST)
        assert limited_research.status_code == 429
        first_upload = client.post("/api/documents", files={"file": ("one.pdf", pdf_bytes("Evidence"), "application/pdf")})
        assert first_upload.status_code == 201
        limited_upload = client.post("/api/documents", files={"file": ("two.pdf", pdf_bytes("Evidence"), "application/pdf")})
        assert limited_upload.status_code == 429


def test_stream_uses_status_only_session_reads_and_terminal_event_retention(tmp_path):
    app = create_app(config(tmp_path, event_audit_tail=2))
    app.state.engine_factory = CompleteEngine
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        session_id = start(client)
        wait_status(client, session_id)
        original_get = app.state.database.get_session
        app.state.database.get_session = lambda *args, **kwargs: pytest.fail("stream loaded the full JSON snapshot")
        try:
            assert client.get(f"/api/research/{session_id}/stream").status_code == 200
        finally:
            app.state.database.get_session = original_get

        session = app.state.database.create_session(LOCAL_USER_ID, REQUEST, [])
        for number in range(4):
            assert app.state.database.append_event(session["id"], "audit", "test", f"event-{number}")
        assert len(app.state.database.events(session["id"])) == 5
        assert app.state.database.transition(session["id"], "completed")
        retained = app.state.database.events(session["id"])
        assert len(retained) == 2
        assert retained[-1]["event_type"] == "session_completed"


def test_invalid_engine_status_fails_closed_to_terminal_enum(api):
    client, app = api

    class InvalidStatusEngine:
        async def run(self, *, initial_state, checkpoint, **kwargs):
            state = research_state(initial_state)
            state["status"] = "not-a-session-status"
            await checkpoint(state)
            return state

    app.state.engine_factory = InvalidStatusEngine
    result = wait_status(client, start(client))
    assert result["status"] == "failed"
    assert result["state"]["status"] == "failed"


def test_missing_credentials_return_503_without_creating_session(tmp_path):
    app = create_app(config(tmp_path, llm_api_key="", tavily_api_key=""))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        result = client.post("/api/research", json={**REQUEST, "source_types": ["web"]})
        assert result.status_code == 503
        assert "LLM_API_KEY" in result.text and "TAVILY_API_KEY" in result.text
        assert client.get("/api/research").json() == []


def test_local_auth_requires_loopback_peer_host_and_allowed_origin(tmp_path):
    app = create_app(config(tmp_path))
    with TestClient(app, base_url="http://localhost", client=("203.0.113.1", 50000)) as client:
        assert client.get("/api/settings", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    app = create_app(config(tmp_path))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/settings", headers={"Host": "attacker.example"}).status_code == 403
        assert client.post("/api/settings/test", headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.get("/api/settings", headers={"Origin": "http://localhost:5173"}).status_code == 200


@pytest.fixture
def authenticated_api(tmp_path):
    app = create_app(config(tmp_path, auth_mode="supabase", cors_origins="https://research.example", supabase_url="https://auth.example", supabase_anon_key="anon-test-key"))
    app.state.engine_factory = CompleteEngine
    owners = {"alice-token": str(uuid4()), "bob-token": str(uuid4())}
    requests = []

    def auth_response(request):
        requests.append(request)
        assert str(request.url) == "https://auth.example/auth/v1/user"
        assert request.headers["apikey"] == "anon-test-key"
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        return httpx.Response(200, json={"id": owners[token]}) if token in owners else httpx.Response(401)

    with TestClient(app, base_url="https://research.example") as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(auth_response))
        client.headers["Authorization"] = "Bearer alice-token"
        yield client, app, owners, requests


def test_supabase_verifies_tokens_and_isolates_history_and_every_child(authenticated_api):
    client, app, owners, requests = authenticated_api
    session_id = start(client)
    wait_status(client, session_id)
    document = client.post("/api/documents", files={"file": ("owned.pdf", pdf_bytes("Owned evidence"), "application/pdf")}).json()
    client.headers["Authorization"] = "Bearer bob-token"
    assert client.get("/api/research").json() == []
    for suffix in ("", "/plan", "/sources", "/claims", "/conflicts", "/gaps", "/report", "/events", "/claims/C1", "/stream", "/export?format=markdown", "/export?format=pdf"):
        assert client.get(f"/api/research/{session_id}{suffix}").status_code == 404, suffix
    assert client.post(f"/api/research/{session_id}/cancel").status_code == 404
    assert client.post(f"/api/research/{session_id}/follow-up", json={"question": "Can this evidence be expanded?"}).status_code == 404
    assert client.delete(f"/api/research/{session_id}").status_code == 404
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
    assert client.post("/api/research", json={**REQUEST, "source_types": ["document"], "document_ids": [document["id"]]}).status_code == 404
    assert app.state.database.get_session(session_id, owners["alice-token"]) is not None
    client.headers["Authorization"] = "Bearer invalid-token"
    assert client.get("/api/settings").status_code == 401
    del client.headers["Authorization"]
    assert client.get(f"/api/research/{session_id}/stream").status_code == 401
    assert requests


def test_settings_redacted_and_connectivity_makes_real_http_request(api):
    client, app = api
    public = client.get("/api/settings")
    assert public.status_code == 200
    assert "test-llm-secret" not in public.text and "test-web-secret" not in public.text
    calls = []

    def provider_response(request):
        calls.append(request)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-llm-secret"
        assert json.loads(request.content)["model"] == "test-model"
        return httpx.Response(401, json={"error": "test-llm-secret"})

    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(provider_response))
    result = client.post("/api/settings/test", json={"integration": "llm"})
    assert result.status_code == 200 and calls
    assert result.json()[0]["ok"] is False and "HTTP 401" in result.text
    assert "test-llm-secret" not in result.text
    limited = client.post("/api/settings/test", json={"integration": "llm"})
    assert limited.status_code == 429 and limited.headers.get("retry-after")


def test_startup_recovers_abandoned_sessions_and_durable_history(tmp_path):
    settings = config(tmp_path)
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        app.state.database.ensure_user(LOCAL_USER_ID)
        seed = app.state.database.create_session(LOCAL_USER_ID, REQUEST, [])
        app.state.database.checkpoint(seed["id"], research_state(seed["state"]))
        app.state.database.transition(seed["id"], "running")
    reopened = create_app(settings)
    with TestClient(reopened, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        result = client.get(f"/api/research/{seed['id']}").json()
        assert result["status"] == "incomplete"
        assert result["state"]["evidence"][0]["id"] == "E1"
        assert client.get(f"/api/research/{seed['id']}/events").json()[-1]["event_type"] == "session_incomplete"


def test_delete_cascades_all_session_children_but_preserves_uploaded_document(api):
    client, app = api
    session_id = start(client)
    wait_status(client, session_id)
    doc = client.post("/api/documents", files={"file": ("keep.pdf", pdf_bytes("Keep this document"), "application/pdf")}).json()
    assert client.delete(f"/api/research/{session_id}").status_code == 204
    assert client.get(f"/api/research/{session_id}").status_code == 404
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200
    with app.state.database.sessions() as db:
        for model in (ResearchSession, Plan, Task, Source, Evidence, Claim, Conflict, Gap, Relationship, ResearchEvent, Report, Followup):
            column = model.id if model is ResearchSession else model.session_id
            assert db.scalar(select(func.count()).select_from(model).where(column == session_id)) == 0


def test_execution_concurrency_queue_capacity_and_followup_conflict(tmp_path):
    app = create_app(config(tmp_path, max_concurrent_sessions=1, max_queued_sessions=2))

    class BlockingEngine:
        active = 0
        peak = 0

        async def run(self, **kwargs):
            type(self).active += 1
            type(self).peak = max(type(self).peak, type(self).active)
            try:
                await asyncio.sleep(60)
            finally:
                type(self).active -= 1

    app.state.engine_factory = BlockingEngine
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        first, second = start(client), start(client)
        wait_status(client, first, {"running"})
        assert client.get(f"/api/research/{second}").json()["status"] == "queued"
        assert client.post("/api/research", json=REQUEST).status_code == 503
        assert client.post(f"/api/research/{first}/follow-up", json={"question": "Can this evidence be expanded?"}).status_code == 409
        client.post(f"/api/research/{first}/cancel")
        wait_status(client, second, {"running"})
        assert BlockingEngine.peak == 1


@pytest.mark.parametrize("values", [{"auth_mode": "disabled"}, {"auth_mode": "supabase"}, {"cors_origins": "https://public.example"}, {"database_url": "mysql://unsupported"}, {"llm_base_url": "https://user:secret@example.org"}, {"llm_base_url": "http://provider.example/v1"}])
def test_invalid_server_configuration_rejected(tmp_path, values):
    with pytest.raises(ValidationError):
        config(tmp_path, **values)


def test_streamed_request_body_is_bounded_before_parsing(tmp_path):
    app = create_app(config(tmp_path, max_json_bytes=1024))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        result = client.post("/api/research", content=iter([b"x" * 700, b"y" * 700]), headers={"Content-Type": "application/json"})
        assert result.status_code == 413
        assert client.get("/api/research").json() == []
