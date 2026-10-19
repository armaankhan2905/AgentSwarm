"""Controlled offline providers exist only in tests; no runtime demo fallback."""

import asyncio
import copy
import json

import pytest

from app.models import ResearchRequest
from app.providers import LLMResult, ProviderError, RetrievedPage, RetrievedSource
from app.workflow import ResearchEngine


TEXT = "In adults, treatment may reduce risk by 12%."


class ControlledProviders:
    def __init__(self, *, follow_up=False, usage=True):
        self.calls = []
        self.searches = []
        self.active_searches = 0
        self.max_active_searches = 0
        self.follow_up = follow_up
        self.usage = usage
        self.verification_inputs = []
        self.gap_round = 0
        self.extract_override = None
        self.verdict_override = None
        self.conflict_override = None
        self.gap_override = None
        self.report_override = None

    async def structured(self, role, prompt, schema, max_tokens):
        data = json.loads(prompt)
        self.calls.append((role, data))
        if role == "planner":
            result = {
                "objective": data["request"]["question"], "scope": "Selected evidence only",
                "subquestions": [{"id": "Q1", "question": "What does the evidence show?", "priority": 1,
                                  "source_types": data["request"]["source_types"], "queries": ["treatment risk adults"],
                                  "evidence_requirements": ["Direct results with population and uncertainty"]}],
                "completion_criteria": ["Evidence answers Q1"], "known_limitations": [], "budget": {},
            }
        elif role == "extractor":
            passage = data["passages"][0]
            result = {"claims": self.extract_override if self.extract_override is not None else [{
                "text": TEXT, "subquestion_id": "Q1", "quotes": [{"evidence_id": passage["id"], "excerpt": TEXT}],
            }]}
        elif role == "semantic_verifier":
            self.verification_inputs.append(copy.deepcopy(data))
            result = {"verdicts": [{
                "claim_id": item["id"], "status": "SUPPORTED", "explanation": "Exact population, uncertainty, value and result are entailed.",
                "supporting_quotes": [{"evidence_id": data["passages"][0]["id"], "excerpt": TEXT}],
                "contradicting_quotes": [], "missing_evidence": [], "requires_follow_up": False,
            } for item in data["claims"]]}
            if self.verdict_override:
                for item in result["verdicts"]:
                    item.update(self.verdict_override)
        elif role == "conflict_analyst":
            result = {"conflicts": self.conflict_override or []}
        elif role == "gap_analyst":
            self.gap_round += 1
            result = {"gaps": [], "complete": not self.follow_up or self.gap_round > 1,
                      "explanation": "Coverage reviewed against completion criteria.",
                      "follow_up_queries": [{"subquestion_id": "Q1", "source_type": data["allowed_source_types"][0],
                                             "query": "targeted replication trial adults", "reason": "Check independent replication"}]
                      if self.follow_up else []}
            if self.gap_override:
                result.update(self.gap_override)
        elif role == "report_writer":
            result = self.report_override or {"title": "Evidence report", "sections": [{
                "id": "results", "title": "Findings", "content": "", "claim_ids": [item["id"] for item in data["claims"]],
            }]}
        else:
            raise AssertionError(f"Unexpected real role: {role}")
        return LLMResult(result, 40 if self.usage else None, 20 if self.usage else None)

    async def _search(self, kind, query, limit, date_from, date_to):
        self.searches.append((kind, query, date_from, date_to))
        self.active_searches += 1
        self.max_active_searches = max(self.max_active_searches, self.active_searches)
        await asyncio.sleep(0.01)
        self.active_searches -= 1
        number = len(self.searches)
        return [RetrievedSource(
            title="Real adapter fixture", url=f"https://{kind}.example/study/{query.replace(' ', '-')}",
            source_type=kind, text=TEXT if kind == "academic" else "",
            publication_date="2024-06-01", location={"kind": "abstract"},
            metadata={"provider": "controlled-test-only", "sequence": number},
        )]

    async def search_web(self, query, limit, date_from, date_to):
        return await self._search("web", query, limit, date_from, date_to)

    async def search_academic(self, query, limit, date_from, date_to):
        return await self._search("academic", query, limit, date_from, date_to)

    async def retrieve(self, url):
        return RetrievedPage(url=url, text=TEXT, publication_date="2024-06-01", location={"kind": "html_text"})


async def run(providers, *, request=None, initial_state=None, cancelled=None):
    checkpoints, events = [], []

    async def checkpoint(state):
        # Persisted callbacks must be independent JSON snapshots.
        checkpoints.append(json.loads(json.dumps(state)))

    async def emit(event_type, agent, message, data=None):
        events.append({"event_type": event_type, "agent": agent, "message": message, "data": data})

    async def not_cancelled():
        return False

    state = await ResearchEngine(providers=providers).run(
        request=request or ResearchRequest(question="What does treatment evidence show?"), session_id="session-test",
        initial_state=initial_state, emit=emit, checkpoint=checkpoint, cancelled=cancelled or not_cancelled,
    )
    return state, checkpoints, events


@pytest.mark.asyncio
async def test_full_parallel_graph_creates_auditable_report_and_real_stage_checkpoints():
    providers = ControlledProviders()
    state, checkpoints, events = await run(providers)
    assert state["status"] == "completed"
    assert providers.max_active_searches == 2
    assert {item["source_type"] for item in state["sources"]} == {"web", "academic"}
    assert state["claims"][0]["status"] == "SUPPORTED"
    assert state["report"]["citation_audit"]["passed"]
    assert "[S1]" in state["report"]["markdown"]
    assert state["budget"]["tokens_used"] == 360
    for passage in state["evidence"]:
        assert passage["text"] == TEXT
        assert passage["location"]["char_end"] - passage["location"]["char_start"] == len(TEXT)
    for name, info in state["node_states"].items():
        assert info["status"] == "completed"
        assert any(snapshot["node_states"].get(name, {}).get("status") == "running" for snapshot in checkpoints)
        assert any(event["event_type"] == "node_completed" and event["agent"] == name for event in events)
    assert checkpoints[0]["sources"] == []
    assert checkpoints[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_conditional_targeted_follow_up_merges_new_passages_and_reverifies():
    providers = ControlledProviders(follow_up=True)
    state, _, events = await run(providers)
    assert state["status"] == "completed"
    assert len(providers.verification_inputs) == 2
    assert len(providers.verification_inputs[1]["passages"]) > len(providers.verification_inputs[0]["passages"])
    assert state["node_states"]["merge_and_reverify"]["runs"] == 2
    assert state["budget"]["used"]["follow_up_rounds"] == 1
    assert any("targeted replication" in item[1] for item in providers.searches)
    assert any(event["event_type"] == "follow_up_started" for event in events)


@pytest.mark.asyncio
async def test_follow_up_rounds_are_bounded_even_if_llm_never_declares_complete(monkeypatch):
    monkeypatch.setenv("MAX_FOLLOW_UP_ROUNDS", "1")
    providers = ControlledProviders(follow_up=True)
    providers.gap_override = {"complete": False}
    state, _, _ = await run(providers)
    assert state["status"] == "incomplete"
    assert state["budget"]["used"]["follow_up_rounds"] == 1
    assert len(providers.verification_inputs) == 2
    assert "incomplete" in state["report"]["markdown"]


@pytest.mark.asyncio
@pytest.mark.parametrize("quote", [
    {"evidence_id": "E999", "excerpt": TEXT},
    {"evidence_id": "E1", "excerpt": "Treatment prevents disease in 90% of humans."},
])
async def test_invented_evidence_ids_or_excerpts_never_become_claims(quote):
    providers = ControlledProviders()
    providers.extract_override = [{"text": "Invented finding", "subquestion_id": "Q1", "quotes": [quote]}]
    state, _, _ = await run(providers)
    assert state["claims"] == [] and state["status"] == "incomplete"
    assert any("Rejected extracted claim" in warning for warning in state["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Treatment prevents risk by 90% in humans.", "Treatment reduces risk by 12% in adults."])
async def test_verifier_cannot_override_numeric_or_dropped_qualifier_guards(text):
    providers = ControlledProviders()
    providers.extract_override = [{"text": text, "subquestion_id": "Q1", "quotes": [{"evidence_id": "E1", "excerpt": TEXT}]}]
    state, _, _ = await run(providers)
    assert state["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert state["claims"][0]["missing_evidence"]
    assert state["status"] == "incomplete"


@pytest.mark.asyncio
async def test_verifier_rejects_fabricated_supporting_excerpts():
    providers = ControlledProviders()
    providers.verdict_override = {"supporting_quotes": [{"evidence_id": "E1", "excerpt": "made up"}]}
    state, _, _ = await run(providers)
    assert state["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert state["claims"][0]["evidence_ids"] == []


@pytest.mark.asyncio
async def test_document_only_consumes_requested_pdf_pages_with_locations_and_no_search():
    providers = ControlledProviders(usage=False)
    state, _, _ = await run(providers, request=ResearchRequest(
        question="What do uploaded studies show?", source_types=["document"], document_ids=["doc-a"],
    ), initial_state={"documents": [
        {"id": "doc-a", "title": "Uploaded PDF", "pages": [{"text": TEXT, "page": 7}]},
        {"id": "doc-b", "title": "Unselected", "pages": [{"text": "Not selected.", "page": 1}]},
    ]})
    assert providers.searches == []
    assert len(state["sources"]) == 1
    assert state["sources"][0]["metadata"]["document_id"] == "doc-a"
    assert state["evidence"][0]["location"]["page"] == 7
    assert state["budget"]["tokens_used"] is None
    assert "pages 7" in state["report"]["markdown"]


@pytest.mark.asyncio
async def test_date_and_source_scope_are_enforced_on_backend():
    providers = ControlledProviders()
    state, _, _ = await run(providers, request=ResearchRequest(
        question="What does selected evidence show?", source_types=["academic"], date_from="2025-01-01", date_to="2025-12-31",
    ))
    assert state["sources"] == [] and state["evidence"] == []
    assert state["status"] == "incomplete"
    assert all(item[0] == "academic" and item[2:] == ("2025-01-01", "2025-12-31") for item in providers.searches)


@pytest.mark.asyncio
async def test_selected_date_range_rejects_unknown_document_dates():
    state, _, _ = await run(ControlledProviders(), request=ResearchRequest(
        question="What does the supplied document show?", source_types=["document"], date_from="2024-01-01",
    ), initial_state={"documents": [{"id": "doc-a", "pages": [{"text": TEXT, "page": 1}]}]})
    assert not state["sources"]
    assert any("publication date" in warning for warning in state["warnings"])


@pytest.mark.asyncio
async def test_atomic_search_limit_is_shared_across_parallel_branches(monkeypatch):
    monkeypatch.setenv("MAX_SEARCHES", "1")
    providers = ControlledProviders()
    state, _, _ = await run(providers)
    assert len(providers.searches) == 1
    assert state["budget"]["used"]["searches"] == 1


@pytest.mark.asyncio
async def test_follow_up_overrides_reach_planner_and_cannot_widen_source_scope():
    providers = ControlledProviders()
    state, _, _ = await run(providers, request=ResearchRequest(
        question="What does selected evidence show?", source_types=["academic"],
    ), initial_state={"follow_up_overrides": {
        "question": "Does independent replication agree?",
        "queries": [{"subquestion_id": "Q1", "query": "precise user follow-up", "source_type": "academic", "reason": "user"},
                    {"subquestion_id": "Q1", "query": "forbidden web search", "source_type": "web", "reason": "user"}],
    }})
    assert providers.calls[0][1]["follow_up_question"] == "Does independent replication agree?"
    assert [item[:2] for item in providers.searches] == [("academic", "precise user follow-up")]
    assert state["follow_ups"][0]["kind"] == "user"
    assert "follow_up_overrides" not in state


@pytest.mark.asyncio
async def test_report_writer_prose_and_invented_claim_references_cannot_create_findings():
    providers = ControlledProviders()
    providers.report_override = {"title": "Invented", "sections": [{
        "id": "fake", "title": "Unsupported assertion", "content": "The treatment cures everyone [S999].",
        "claim_ids": ["C999", "C1"],
    }]}
    state, _, _ = await run(providers)
    assert "cures everyone" not in state["report"]["markdown"]
    assert "S999" not in state["report"]["markdown"]
    assert state["report"]["citation_audit"]["passed"]
    assert TEXT in state["report"]["markdown"]


@pytest.mark.asyncio
async def test_failures_keep_latest_checkpoint_and_do_not_complete_failed_stages():
    providers = ControlledProviders()
    checkpoints, events = [], []

    async def broken(*args):
        raise ProviderError("Controlled provider outage")

    async def checkpoint(state):
        checkpoints.append(state)

    async def emit(*args):
        events.append(args)

    providers.structured = broken
    with pytest.raises(ProviderError, match="outage"):
        await ResearchEngine(providers).run(
            ResearchRequest(question="What does treatment evidence show?"), "session-test", checkpoint=checkpoint, emit=emit,
        )
    assert checkpoints[-1]["status"] == "failed"
    assert checkpoints[-1]["node_states"]["planner"]["status"] == "failed"
    assert not any(item[0] == "node_completed" for item in events)


@pytest.mark.asyncio
async def test_cancellation_interrupts_inflight_provider_and_checkpoints_real_stage():
    providers = ControlledProviders()
    started, stopped = asyncio.Event(), asyncio.Event()
    checkpoints = []

    async def slow(*args):
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()

    async def cancelled():
        return started.is_set()

    async def checkpoint(state):
        checkpoints.append(state)

    providers.structured = slow
    with pytest.raises(Exception, match="cancelled"):
        await ResearchEngine(providers).run(ResearchRequest(question="What does treatment evidence show?"), "cancel-test", checkpoint=checkpoint, cancelled=cancelled)
    assert stopped.is_set()
    assert checkpoints[-1]["status"] == "cancelled"
    assert checkpoints[-1]["node_states"]["planner"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_tight_token_limit_retains_honest_partial_report(monkeypatch):
    monkeypatch.setenv("MAX_TOKENS", "1")
    providers = ControlledProviders()
    state, checkpoints, events = await run(providers)
    assert state["status"] == "incomplete"
    assert providers.calls == []
    assert not state["claims"]
    assert "Research is incomplete" in state["report"]["markdown"]
    assert state["node_states"]["planner"]["status"] == "failed"
    assert not any(item["event_type"] == "node_completed" and item["agent"] == "planner" for item in events)
