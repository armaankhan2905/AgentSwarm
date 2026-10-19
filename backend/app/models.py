"""Public request/state records and schema-validated research role outputs."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceType = Literal["web", "academic", "document"]
ClaimStatus = Literal[
    "SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE", "UNVERIFIABLE",
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchRequest(Record):
    question: str = Field(min_length=10, max_length=4000)
    depth: Literal["quick", "standard", "deep"] = "standard"
    source_types: list[SourceType] = Field(default_factory=lambda: ["web", "academic"], min_length=1)
    date_from: date | None = None
    date_to: date | None = None
    context: str | None = Field(default=None, max_length=12000)
    document_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_scope(self):
        self.question = self.question.strip()
        if len(self.question) < 10:
            raise ValueError("question must contain at least 10 non-padding characters")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        self.source_types = list(dict.fromkeys(self.source_types))
        self.document_ids = list(dict.fromkeys(self.document_ids))
        if self.document_ids and "document" not in self.source_types:
            raise ValueError("document_ids require document source research")
        return self


class Subquestion(Record):
    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    priority: int = Field(default=1, ge=1, le=5)
    source_types: list[SourceType] = Field(min_length=1, max_length=3)
    queries: list[str] = Field(min_length=1, max_length=5)
    evidence_requirements: list[str] = Field(default_factory=list, max_length=10)


class Plan(Record):
    objective: str
    scope: str
    subquestions: list[Subquestion] = Field(min_length=1, max_length=12)
    completion_criteria: list[str] = Field(min_length=1, max_length=12)
    known_limitations: list[str] = Field(default_factory=list, max_length=12)
    budget: dict[str, Any] = Field(default_factory=dict)


class Source(Record):
    id: str
    title: str
    url: str
    domain: str
    source_type: SourceType
    retrieved_at: str
    publication_date: str | None = None
    authors: list[str] = Field(default_factory=list)
    doi: str | None = None
    retrieval_status: str = "metadata_only"
    access_limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Passage(Record):
    id: str
    source_id: str
    text: str
    location: dict[str, Any]
    retrieved_at: str
    subquestion_id: str


class Quote(Record):
    evidence_id: str
    excerpt: str = Field(min_length=1, max_length=6000)


class CandidateClaim(Record):
    text: str = Field(min_length=1, max_length=2000)
    subquestion_id: str
    quotes: list[Quote] = Field(min_length=1, max_length=12)


class Extraction(Record):
    claims: list[CandidateClaim] = Field(default_factory=list, max_length=35)


class Claim(Record):
    id: str
    text: str
    subquestion_id: str
    status: ClaimStatus = "INSUFFICIENT_EVIDENCE"
    explanation: str = "Pending semantic verification"
    evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    requires_follow_up: bool = True
    verified_at: str | None = None
    quotes: list[Quote] = Field(default_factory=list)


class ClaimVerdict(Record):
    claim_id: str
    status: ClaimStatus
    explanation: str
    supporting_quotes: list[Quote] = Field(default_factory=list, max_length=12)
    contradicting_quotes: list[Quote] = Field(default_factory=list, max_length=12)
    missing_evidence: list[str] = Field(default_factory=list, max_length=12)
    requires_follow_up: bool


class Verification(Record):
    verdicts: list[ClaimVerdict] = Field(default_factory=list, max_length=70)


class Conflict(Record):
    id: str
    description: str
    claim_ids: list[str] = Field(min_length=1, max_length=12)
    source_ids: list[str] = Field(default_factory=list, max_length=24)
    evidence_ids: list[str] = Field(min_length=1, max_length=24)
    conflict_type: str
    positions: list[str] = Field(min_length=1, max_length=12)
    explanation: str
    resolved: bool = False
    follow_up: str | None = None


class ConflictAnalysis(Record):
    conflicts: list[Conflict] = Field(default_factory=list, max_length=20)


class Gap(Record):
    id: str
    title: str
    description: str
    category: Literal["EVIDENCE_BACKED", "POTENTIAL"]
    source_ids: list[str] = Field(default_factory=list, max_length=24)
    evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    evidence_quotes: list[Quote] = Field(default_factory=list, max_length=12)
    subquestion_id: str
    existing_approaches: list[str] = Field(default_factory=list, max_length=12)
    significance: str
    opportunity: str
    limitations: list[str] = Field(default_factory=list, max_length=12)
    next_steps: list[str] = Field(default_factory=list, max_length=12)


class TargetedQuery(Record):
    subquestion_id: str
    query: str = Field(min_length=3, max_length=500)
    source_type: SourceType
    reason: str


class GapAnalysis(Record):
    gaps: list[Gap] = Field(default_factory=list, max_length=20)
    complete: bool
    explanation: str
    follow_up_queries: list[TargetedQuery] = Field(default_factory=list, max_length=12)


class ReportSection(Record):
    id: str
    title: str
    content: str
    claim_ids: list[str] = Field(default_factory=list, max_length=70)


class ReportDraft(Record):
    title: str
    sections: list[ReportSection] = Field(min_length=1, max_length=16)
