"""Deterministic evidence checks and atomic, serializable execution limits."""

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchError(RuntimeError):
    """An explicit failure whose latest state is available through checkpoint."""


class BudgetExceeded(ResearchError):
    pass


class ResearchCancelled(ResearchError):
    pass


def env_int(name: str, default: int, minimum: int = 1, maximum: int = 10_000_000) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError as exc:
        raise ResearchError(f"{name} must be an integer") from exc


class Budget:
    """Reservations happen before awaits, so parallel branches cannot overspend.

    tokens_reserved is a conservative charged allowance, NOT reported token usage.
    If any provider omits usage, tokens_used remains null. A failed/unknown call
    retains its token reservation; known usage can refund unused allowance.
    """

    def __init__(self, depth: str, previous: dict | None = None):
        scale = {"quick": 1, "standard": 2, "deep": 3}[depth]
        self.limits = {
            "searches": env_int("MAX_SEARCHES", 6 * scale, maximum=60),
            "fetches": env_int("MAX_FETCHES", 8 * scale, maximum=100),
            "llm_calls": env_int("MAX_LLM_CALLS", 10 * scale, maximum=60),
            "tokens": env_int("MAX_TOKENS", 120000 * scale, maximum=2000000),
            "sources": env_int("MAX_SOURCES", 8 * scale, maximum=80),
            "passages": env_int("MAX_PASSAGES", 16 * scale, maximum=160),
            "follow_up_rounds": env_int("MAX_FOLLOW_UP_ROUNDS", scale, minimum=0, maximum=5),
            "wall_seconds": env_int("MAX_WALL_SECONDS", 120 * scale, maximum=1800),
        }
        previous = previous or {}
        self.used = {key: max(0, int(previous.get("used", {}).get(key, 0)))
                     for key in ("searches", "fetches", "llm_calls", "sources", "passages", "follow_up_rounds")}
        self.tokens_reserved = max(0, int(previous.get("tokens_reserved", 0)))
        self.known_tokens = max(0, int(previous.get("known_tokens", 0)))
        self.usage_available = previous.get("usage_available", True)
        self.elapsed_before = max(0.0, float(previous.get("elapsed_seconds", 0)))
        self.started = time.monotonic()
        self.lock = asyncio.Lock()

    @property
    def remaining_seconds(self) -> float:
        return self.limits["wall_seconds"] - self.elapsed_before - (time.monotonic() - self.started)

    async def reserve(self, resource: str, amount: int = 1, tokens: int = 0):
        async with self.lock:
            if self.remaining_seconds <= 0:
                raise BudgetExceeded("Wall-time limit reached")
            if self.used[resource] + amount > self.limits[resource]:
                raise BudgetExceeded(f"{resource} limit reached")
            if self.tokens_reserved + tokens > self.limits["tokens"]:
                raise BudgetExceeded("Token allowance limit reached")
            self.used[resource] += amount
            self.tokens_reserved += tokens

    async def record_usage(self, reservation: int, input_tokens: int | None, output_tokens: int | None):
        async with self.lock:
            if input_tokens is None or output_tokens is None:
                self.usage_available = False
                return
            actual = max(0, input_tokens) + max(0, output_tokens)
            self.known_tokens += actual
            self.tokens_reserved += actual - reservation
            if self.tokens_reserved > self.limits["tokens"]:
                raise BudgetExceeded("Provider usage exceeded token allowance")

    def snapshot(self) -> dict:
        return {
            "limits": dict(self.limits), "used": dict(self.used),
            "tokens_reserved": self.tokens_reserved, "known_tokens": self.known_tokens,
            "usage_available": self.usage_available,
            "tokens_used": self.known_tokens if self.usage_available else None,
            "elapsed_seconds": round(self.elapsed_before + time.monotonic() - self.started, 3),
        }


def valid_quotes(quotes: list[dict], passages: dict[str, dict]) -> tuple[list[dict], list[str]]:
    accepted, errors = [], []
    for quote in quotes:
        passage = passages.get(quote.get("evidence_id"))
        excerpt = quote.get("excerpt", "")
        if passage is None:
            errors.append(f"Unknown evidence ID: {quote.get('evidence_id')}")
        elif not excerpt.strip() or excerpt not in passage["text"]:
            errors.append(f"Excerpt is not an exact retrieved substring: {quote.get('evidence_id')}")
        else:
            start = passage["text"].index(excerpt)
            accepted.append({**quote, "start": start, "end": start + len(excerpt)})
    return accepted, errors


_NUMBER = re.compile(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?:\s*%|\s*(?:million|billion|thousand))?", re.I)
_QUALIFIERS = [
    (r"\b(?:may|might|could|possibly|potentially)\b", r"\b(?:may|might|could|possibly|potentially|suggests?)\b", "uncertainty"),
    (r"\b(?:associated|correlat\w*|observational)\b", r"\b(?:associated|association|correlat\w*|observational)\b", "association-only evidence"),
    (r"\b(?:in mice|in rats|animal model|in vitro)\b", r"\b(?:mice|rats|animal|in vitro)\b", "non-human scope"),
]


def support_issues(claim: str, excerpts: list[str]) -> list[str]:
    """Fail closed on numbers and common dropped epistemic/population qualifiers.

    This guard supplements the semantic verifier; it cannot establish entailment.
    Numbers must match an exact lexical value/unit (no model-created conversions).
    """
    evidence = " ".join(excerpts).lower()
    normalized = lambda value: re.sub(r"\s+", "", value.lower()).replace(",", "")
    available = {normalized(number) for number in _NUMBER.findall(evidence)}
    issues = [f"Numeric value/unit absent from supporting quotes: {number}"
              for number in _NUMBER.findall(claim) if normalized(number) not in available]
    for pattern, required, label in _QUALIFIERS:
        if re.search(pattern, evidence, re.I) and not re.search(required, claim, re.I):
            issues.append(f"Claim drops {label} qualifier")
    if re.search(r"\b(?:causes?|prevents?|proves?|guarantees?|always|all patients)\b", claim, re.I):
        if re.search(r"\b(?:may|might|could|association|associated|correlat\w*|observational)\b", evidence, re.I):
            issues.append("Causal/universal wording exceeds qualified evidence")
    return issues


def citation_ids(text: str) -> list[str]:
    return re.findall(r"\[(S[\w.-]+)\]", text)
