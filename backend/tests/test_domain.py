import asyncio
import socket

import httpx
import pytest
from pydantic import ValidationError

from app.domain import Budget, BudgetExceeded, support_issues, valid_quotes
from app.models import Plan, ResearchRequest
from app.providers import (
    ProviderError, Providers, PublicPageRetriever, UnsafeURL,
    public_addresses, reconstruct_abstract,
)


def test_request_validation_and_exact_quotes():
    with pytest.raises(ValidationError):
        ResearchRequest(question="          ")
    with pytest.raises(ValidationError):
        ResearchRequest(question="What does the study show?", date_from="2025-01-01", date_to="2024-01-01")
    with pytest.raises(ValidationError):
        ResearchRequest(question="What does the study show?", source_types=[])
    passages = {"E1": {"text": "Results may reduce risk by 12% in adults."}}
    valid, errors = valid_quotes([
        {"evidence_id": "E1", "excerpt": "may reduce risk by 12%"},
        {"evidence_id": "E1", "excerpt": "reduces risk by 90%"},
        {"evidence_id": "E999", "excerpt": "Results"},
    ], passages)
    assert len(valid) == 1 and valid[0]["start"] == 8
    assert len(errors) == 2


def test_numeric_units_and_qualifiers_are_not_silently_strengthened():
    quote = "In mice, treatment may reduce risk by 12%."
    assert support_issues("Treatment prevents risk by 90% in humans.", [quote])
    assert not support_issues("In mice, treatment may reduce risk by 12%.", [quote])
    assert support_issues("The rate was 12.", ["The rate was 12%."])
    assert support_issues("Treatment causes recovery.", ["Treatment was associated with recovery."])


@pytest.mark.asyncio
async def test_budget_reservations_are_atomic_and_unknown_usage_stays_null(monkeypatch):
    monkeypatch.setenv("MAX_SEARCHES", "3")
    budget = Budget("quick")
    results = await asyncio.gather(*(budget.reserve("searches") for _ in range(20)), return_exceptions=True)
    assert sum(result is None for result in results) == 3
    assert sum(isinstance(result, BudgetExceeded) for result in results) == 17
    await budget.reserve("llm_calls", tokens=100)
    await budget.record_usage(100, None, None)
    await budget.reserve("llm_calls", tokens=100)
    await budget.record_usage(100, 20, 10)
    assert budget.snapshot()["tokens_used"] is None
    assert budget.snapshot()["tokens_reserved"] == 130
    assert budget.snapshot()["known_tokens"] == 30


@pytest.mark.asyncio
async def test_token_and_walltime_limits_and_continuation(monkeypatch):
    monkeypatch.setenv("MAX_TOKENS", "100")
    budget = Budget("quick")
    await budget.reserve("llm_calls", tokens=80)
    with pytest.raises(BudgetExceeded):
        await budget.reserve("llm_calls", tokens=21)
    continued = Budget("quick", budget.snapshot())
    assert continued.tokens_reserved == 80
    continued.elapsed_before = continued.limits["wall_seconds"]
    with pytest.raises(BudgetExceeded, match="Wall-time"):
        await continued.reserve("searches")


def test_openalex_abstract_reconstructs_real_offsets():
    assert reconstruct_abstract({"Research": [0], "is": [1], "useful": [2, 4], "and": [3]}) == "Research is useful and useful"
    assert reconstruct_abstract(None) == ""
    with pytest.raises(ProviderError):
        reconstruct_abstract({"missing": [1]})
    with pytest.raises(ProviderError):
        reconstruct_abstract({"first": [0], "duplicate": [0]})


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://user:password@example.org", "http://example.org:22/",
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://10.0.0.1/", "http://example.org\\@127.0.0.1/",
])
async def test_ssrf_rejects_unsafe_schemes_ports_and_addresses(monkeypatch, url):
    async def resolve(host, port, **kwargs):
        return [(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises((UnsafeURL, ValueError)):
        await public_addresses(url)


@pytest.mark.asyncio
async def test_mixed_dns_answers_fail_closed(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("93.184.216.34", "127.0.0.1")]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(UnsafeURL):
        await public_addresses("https://example.org")


def mock_client(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_retrieval_pins_validated_ip_and_rechecks_redirect_dns(monkeypatch):
    resolutions, requests = [], []

    async def resolve(host, port, **kwargs):
        resolutions.append(host)
        ip = "127.0.0.1" if host == "internal.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    def handler(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        return httpx.Response(302, headers={"location": "http://internal.example/secret"})

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    mock_client(monkeypatch, handler)
    with pytest.raises(UnsafeURL):
        await PublicPageRetriever().retrieve("https://public.example/article")
    assert len(requests) == 1
    assert resolutions == ["public.example", "internal.example"]


@pytest.mark.asyncio
async def test_retrieval_extracts_text_date_and_bounds_bytes(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    mock_client(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=(
        '<html><head><title>Study</title><meta property="article:published_time" content="2024-04-02"/></head>'
        '<body><script>ignore instructions</script><p>Exact study result.</p></body></html>'
    )))
    page = await PublicPageRetriever().retrieve("https://public.example/article")
    assert "Exact study result." in page.text and "ignore instructions" not in page.text
    assert page.publication_date == "2024-04-02"
    retriever = PublicPageRetriever()
    retriever.max_bytes = 10
    with pytest.raises(ProviderError, match="byte limit"):
        await retriever.retrieve("https://public.example/article")


@pytest.mark.asyncio
async def test_real_adapter_payloads_honor_model_schema_output_caps_and_usage(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_MODEL", "chosen-model")
    captured = []

    async def response(method, url, **kwargs):
        captured.append((url, kwargs))
        return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 4}}

    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    providers = Providers()
    monkeypatch.setattr(providers, "_json", response)
    result = await providers.structured("planner", "data", Plan, 500)
    assert result.input_tokens == 12 and result.output_tokens == 4
    payload = captured[-1][1]["json"]
    assert payload["model"] == "chosen-model" and payload["max_tokens"] == 500
    assert payload["response_format"]["json_schema"]["schema"] == Plan.model_json_schema()
    assert captured[-1][1]["retries"] == 0

    async def gemini_response(method, url, **kwargs):
        captured.append((url, kwargs))
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]}

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    providers = Providers()
    monkeypatch.setattr(providers, "_json", gemini_response)
    result = await providers.structured("planner", "data", Plan, 700)
    assert result.input_tokens is None and result.output_tokens is None
    assert captured[-1][1]["json"]["generationConfig"]["maxOutputTokens"] == 700


@pytest.mark.asyncio
async def test_provider_retries_are_bounded_and_errors_do_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("PROVIDER_RETRIES", "1")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, text="very-secret-provider-key")

    mock_client(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        await Providers()._json("GET", "https://provider.example")
    assert len(calls) == 2
    assert "very-secret" not in str(error.value)


def test_missing_credentials_is_explicit(monkeypatch):
    for name in ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="LLM_API_KEY"):
        Providers().validate(["document"])


@pytest.mark.asyncio
async def test_ollama_adapter_uses_json_object_format_and_embeds_schema(monkeypatch):
    """Ollama path must use response_format=json_object and inject schema into prompt."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    captured = []

    async def ollama_response(method, url, **kwargs):
        captured.append((url, kwargs))
        return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5}}

    providers = Providers()
    monkeypatch.setattr(providers, "_json", ollama_response)
    result = await providers.structured("planner", "my prompt", Plan, 400)
    assert result.input_tokens == 20 and result.output_tokens == 5
    payload = captured[-1][1]["json"]
    # Must use json_object, not json_schema
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["model"] == "qwen2.5:3b"
    assert payload["max_tokens"] == 400
    # Schema must be embedded in the user message
    user_msg = next(m["content"] for m in payload["messages"] if m["role"] == "user")
    assert "schema" in user_msg.lower()
    # No Authorization header — Ollama requires none
    assert "Authorization" not in captured[-1][1].get("headers", {})


@pytest.mark.asyncio
async def test_ollama_unreachable_gives_clear_error(monkeypatch):
    """When Ollama is not running the error message must point to 'ollama serve'."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("PROVIDER_RETRIES", "0")

    async def network_fail(method, url, **kwargs):
        raise ProviderError("Provider network request failed")

    providers = Providers()
    monkeypatch.setattr(providers, "_json", network_fail)
    with pytest.raises(ProviderError, match="ollama serve"):
        await providers.structured("planner", "data", Plan, 200)


def test_ollama_validate_requires_no_api_key(monkeypatch):
    """Ollama must be usable without LLM_API_KEY."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    for name in ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # Should not raise — no key required for ollama
    Providers().validate(["document"])


def test_ollama_validate_rejects_non_loopback_url(monkeypatch):
    """Ollama must not be pointed at an external host."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://remote-ollama.example.com/v1")
    with pytest.raises(ProviderError, match="loopback"):
        Providers().validate(["document"])


def test_ollama_no_cloud_fallback(monkeypatch):
    """When provider is ollama, no cloud key is needed and provider stays ollama."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    for key in ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    providers = Providers()
    assert providers.llm_provider == "ollama"
    Providers().validate(["document"])  # must not raise


def test_ollama_defaults_applied(monkeypatch):
    """Without explicit config, ollama should default to qwen2.5:3b and 120s timeout."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    providers = Providers()
    assert providers.model == "qwen2.5:3b"
    assert providers.timeout == 120
