"""SQLAlchemy persistence; each checkpoint updates snapshot and entities atomically."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON, Boolean, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text,
    UniqueConstraint, create_engine, delete, event, func, select, text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

TERMINAL_STATUSES = {"completed", "incomplete", "failed", "cancelled"}


class QuotaExceeded(ValueError):
    """A bounded per-user resource or lifecycle operation was refused."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class ResearchSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    request: Mapped[dict] = mapped_column(JSON)
    state: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now, index=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (Index("ix_sessions_owner_created", "owner_id", "created_at"),)


class Plan(Base):
    __tablename__ = "plans"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class EntityMixin:
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Task(EntityMixin, Base):
    __tablename__ = "tasks"
    question: Mapped[str] = mapped_column(Text)


class Source(EntityMixin, Base):
    __tablename__ = "sources"
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30), index=True)


class Evidence(EntityMixin, Base):
    __tablename__ = "evidence"
    source_id: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "source_id"], ["sources.session_id", "sources.id"], ondelete="CASCADE"),
        Index("ix_evidence_source", "session_id", "source_id"),
    )


class Claim(EntityMixin, Base):
    __tablename__ = "claims"
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), index=True)


class Conflict(EntityMixin, Base):
    __tablename__ = "conflicts"
    description: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class Gap(EntityMixin, Base):
    __tablename__ = "gaps"
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))


class Relationship(Base):
    __tablename__ = "relationships"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    relation: Mapped[str] = mapped_column(String(40))
    claim_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    conflict_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gap_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "claim_id"], ["claims.session_id", "claims.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["session_id", "evidence_id"], ["evidence.session_id", "evidence.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["session_id", "source_id"], ["sources.session_id", "sources.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["session_id", "conflict_id"], ["conflicts.session_id", "conflicts.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["session_id", "gap_id"], ["gaps.session_id", "gaps.id"], ondelete="CASCADE"),
        Index("ix_relationships_claim", "session_id", "claim_id"),
        Index("ix_relationships_evidence", "session_id", "evidence_id"),
        Index("ix_relationships_source", "session_id", "source_id"),
    )


class ResearchEvent(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    agent: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)
    timestamp: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (Index("ix_events_session_cursor", "session_id", "id"),)


class Report(Base):
    __tablename__ = "reports"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)


class Followup(EntityMixin, Base):
    __tablename__ = "followups"
    question: Mapped[str] = mapped_column(Text)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSON)
    extraction_status: Mapped[str] = mapped_column(String(30))
    size_bytes: Mapped[int] = mapped_column(Integer)
    text_chars: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class SessionDocument(Base):
    __tablename__ = "session_documents"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)


def session_dict(row: ResearchSession, *, include_state: bool = True) -> dict:
    value = {key: getattr(row, key) for key in ("id", "question", "status", "request", "error", "created_at", "updated_at")}
    state = row.state or {}
    value["summary"] = {
        "source_count": len(state.get("sources", [])),
        "evidence_count": len(state.get("evidence", [])),
        "claim_count": len(state.get("claims", [])),
    }
    if include_state:
        value["state"] = state
    return value


def event_dict(row: ResearchEvent) -> dict:
    return {key: getattr(row, key) for key in ("id", "session_id", "event_type", "agent", "message", "data", "timestamp")}


class Database:
    def __init__(self, url: str):
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite:"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url in {"sqlite:///:memory:", "sqlite://"}:
                options["poolclass"] = StaticPool
        else:
            # Supabase's transaction pooler cannot retain named prepared statements.
            options["connect_args"] = {"prepare_threshold": None}
        self.engine = create_engine(url, **options)
        if url.startswith("sqlite:"):
            @event.listens_for(self.engine, "connect")
            def sqlite_constraints(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        # PostgreSQL schema and RLS must be installed by the versioned migration.
        if self.engine.dialect.name == "sqlite":
            Base.metadata.create_all(self.engine)
            with self.engine.begin() as connection:
                columns = {row[1] for row in connection.execute(sql_text("PRAGMA table_info(documents)"))}
                if "text_chars" not in columns:
                    connection.execute(sql_text("ALTER TABLE documents ADD COLUMN text_chars INTEGER NOT NULL DEFAULT 0"))

    def ensure_user(self, owner_id: str):
        # ON CONFLICT avoids two concurrent authenticated requests racing to create a user.
        if self.engine.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        with self.sessions.begin() as db:
            db.execute(insert(User).values(id=owner_id, created_at=now()).on_conflict_do_nothing(index_elements=["id"]))

    def create_session(
        self,
        owner_id: str,
        request: dict,
        documents: list[dict],
        *,
        max_active_sessions: int | None = None,
        max_total_sessions: int | None = None,
        max_queued_sessions: int | None = None,
    ) -> dict:
        session_id = str(uuid4())
        document_ids = list(dict.fromkeys(str(document["id"]) for document in documents))
        state = {
            "session_id": session_id, "question": request["question"], "request": request,
            "plan": {}, "sources": [], "evidence": [], "claims": [], "conflicts": [],
            "gaps": [], "report": {}, "budget": {}, "follow_ups": [], "warnings": [],
            "node_states": {}, "document_ids": document_ids,
        }
        with self.sessions.begin() as db:
            # Locking the owner row makes the quota check and session insert a
            # single tenant-serialized operation on PostgreSQL. SQLite's
            # transaction write lock provides the same protection locally.
            db.scalar(select(User).where(User.id == owner_id).with_for_update())
            if max_active_sessions is not None:
                active = db.scalar(select(func.count()).select_from(ResearchSession).where(
                    ResearchSession.owner_id == owner_id,
                    ResearchSession.status.in_(["queued", "running"]),
                )) or 0
                if active >= max_active_sessions:
                    raise QuotaExceeded("Your research queue is full; wait for an existing session to finish")
            if max_total_sessions is not None:
                total = db.scalar(select(func.count()).select_from(ResearchSession).where(ResearchSession.owner_id == owner_id)) or 0
                if total >= max_total_sessions:
                    raise QuotaExceeded("Research history quota reached; delete an older session before starting another")
            if max_queued_sessions is not None:
                queued = db.scalar(select(func.count()).select_from(ResearchSession).where(ResearchSession.status.in_(["queued", "running"]))) or 0
                if queued >= max_queued_sessions:
                    raise QuotaExceeded("Research queue is full; retry later")
            row = ResearchSession(id=session_id, owner_id=owner_id, question=request["question"], request=request, state=state)
            db.add(row)
            db.flush()
            for document in documents:
                db.add(SessionDocument(session_id=session_id, document_id=document["id"]))
            self._event(db, session_id, "session_queued", "orchestrator", "Research queued", {"status": "queued"})
        return session_dict(row)

    def get_session(self, session_id: str, owner_id: str | None = None) -> dict | None:
        with self.sessions() as db:
            query = select(ResearchSession).where(ResearchSession.id == session_id)
            if owner_id is not None:
                query = query.where(ResearchSession.owner_id == owner_id)
            row = db.scalar(query)
            return session_dict(row) if row else None

    def documents_for_session(self, session_id: str) -> list[dict]:
        with self.sessions() as db:
            query = (
                select(Document)
                .join(SessionDocument, SessionDocument.document_id == Document.id)
                .where(SessionDocument.session_id == session_id)
                .order_by(Document.created_at, Document.id)
            )
            return [self.document_dict(row) for row in db.scalars(query)]

    def count_active_sessions(self, owner_id: str) -> int:
        with self.sessions() as db:
            return int(db.scalar(
                select(func.count()).select_from(ResearchSession).where(
                    ResearchSession.owner_id == owner_id,
                    ResearchSession.status.in_(["queued", "running"]),
                )
            ) or 0)

    def list_sessions(self, owner_id: str, search: str, sort: str, limit: int = 100) -> list[dict]:
        with self.sessions() as db:
            query = select(ResearchSession).where(ResearchSession.owner_id == owner_id)
            if search:
                query = query.where(ResearchSession.question.contains(search, autoescape=True))
            column = ResearchSession.updated_at if sort == "updated" else ResearchSession.created_at
            query = query.order_by(column.asc() if sort == "oldest" else column.desc(), ResearchSession.id).limit(limit)
            return [session_dict(row, include_state=False) for row in db.scalars(query)]

    @staticmethod
    def _event(db, session_id: str, event_type: str, agent: str, message: str, data: dict | None = None):
        row = ResearchEvent(session_id=session_id, event_type=event_type, agent=agent, message=message, data=data or {})
        db.add(row)
        db.flush()
        return event_dict(row)

    def append_event(self, session_id: str, event_type: str, agent: str, message: str, data: dict | None = None):
        with self.sessions.begin() as db:
            row = db.get(ResearchSession, session_id)
            if row is None or row.status == "cancelled":
                return None
            return self._event(db, session_id, event_type, agent, message, data)

    def events(self, session_id: str, after: int = 0, limit: int | None = None) -> list[dict]:
        with self.sessions() as db:
            query = select(ResearchEvent).where(ResearchEvent.session_id == session_id, ResearchEvent.id > after).order_by(ResearchEvent.id)
            if limit:
                query = query.limit(limit)
            return [event_dict(row) for row in db.scalars(query)]

    def transition(self, session_id: str, status: str, *, error: str | None = None) -> bool:
        with self.sessions.begin() as db:
            row = db.scalar(select(ResearchSession).where(ResearchSession.id == session_id).with_for_update())
            if row is None or row.status in TERMINAL_STATUSES:
                return False
            row.status, row.error, row.updated_at = status, error, now()
            row.state = {**row.state, "status": status}
            self._event(db, session_id, f"session_{status}", "orchestrator", error or f"Research {status}", {"status": status})
        return True

    def recover_abandoned(self):
        with self.sessions.begin() as db:
            rows = db.scalars(select(ResearchSession).where(ResearchSession.status.in_(["queued", "running"]))).all()
            for row in rows:
                row.status = "incomplete"
                row.state = {**row.state, "status": "incomplete"}
                row.error = "Execution interrupted by server restart. Latest checkpoint retained; submit a follow-up to continue."
                row.updated_at = now()
                self._event(db, row.id, "session_incomplete", "orchestrator", row.error, {"status": "incomplete"})

    def checkpoint(self, session_id: str, state: dict):
        with self.sessions.begin() as db:
            row = db.scalar(select(ResearchSession).where(ResearchSession.id == session_id).with_for_update())
            if row is None:
                return
            snapshot = deepcopy(state)
            snapshot["session_id"] = session_id
            snapshot["question"] = row.question
            snapshot["request"] = row.request
            # API documents and follow-ups are authoritative input, not model output.
            snapshot.pop("documents", None)
            stored_ids = row.state.get("document_ids") or [
                str(document.get("id")) for document in row.state.get("documents", [])
                if isinstance(document, dict) and document.get("id")
            ]
            snapshot["document_ids"] = list(dict.fromkeys(stored_ids))
            if not snapshot.get("follow_ups"):
                snapshot["follow_ups"] = row.state.get("follow_ups", [])
            snapshot["status"] = row.status  # A checkpoint must never undo cancellation.
            self._normalize(db, session_id, snapshot)
            row.state, row.updated_at = snapshot, now()

    @staticmethod
    def _normalize(db, session_id: str, state: dict):
        for model in (Relationship, Evidence, Claim, Conflict, Gap, Source, Task, Plan, Report, Followup):
            db.execute(delete(model).where(model.session_id == session_id))
        plan = state.get("plan") or {}
        if plan:
            db.add(Plan(session_id=session_id, payload=plan))
            for task in plan.get("subquestions", []):
                db.add(Task(session_id=session_id, id=task["id"], question=task["question"], payload=task))
        for source in state.get("sources", []):
            db.add(Source(session_id=session_id, id=source["id"], title=source.get("title", ""), url=source.get("url", ""), source_type=source.get("source_type", "web"), payload=source))
        db.flush()
        for passage in state.get("evidence", []):
            db.add(Evidence(session_id=session_id, id=passage["id"], source_id=passage["source_id"], text=passage["text"], payload=passage))
        for claim in state.get("claims", []):
            db.add(Claim(session_id=session_id, id=claim["id"], text=claim["text"], status=claim["status"], payload=claim))
        for conflict in state.get("conflicts", []):
            db.add(Conflict(session_id=session_id, id=conflict["id"], description=conflict.get("description", ""), resolved=conflict.get("resolved", False), payload=conflict))
        for gap in state.get("gaps", []):
            db.add(Gap(session_id=session_id, id=gap["id"], title=gap.get("title", ""), category=gap.get("category", "POTENTIAL"), payload=gap))
        db.flush()
        ids = {key: {record["id"] for record in state.get(key, [])} for key in ("claims", "evidence", "sources", "conflicts", "gaps")}

        def link(relation: str, **references):
            names = {"claim_id": "claims", "evidence_id": "evidence", "source_id": "sources", "conflict_id": "conflicts", "gap_id": "gaps"}
            if not all(value in ids[names[key]] for key, value in references.items()):
                raise ValueError("Checkpoint contains an unknown entity reference")
            db.add(Relationship(session_id=session_id, id=str(uuid4()), relation=relation, **references))

        for passage in state.get("evidence", []):
            link("passage_source", evidence_id=passage["id"], source_id=passage["source_id"])
        for claim in state.get("claims", []):
            for field, relation in (("evidence_ids", "supports"), ("contradicting_evidence_ids", "contradicts")):
                for evidence_id in claim.get(field, []):
                    link(relation, claim_id=claim["id"], evidence_id=evidence_id)
        for collection, owner_key in (("conflicts", "conflict_id"), ("gaps", "gap_id")):
            for record in state.get(collection, []):
                for field, target in (("claim_ids", "claim_id"), ("source_ids", "source_id"), ("evidence_ids", "evidence_id")):
                    for target_id in record.get(field, []):
                        link("references", **{owner_key: record["id"], target: target_id})
        report = state.get("report") or {}
        if report:
            db.add(Report(session_id=session_id, title=report.get("title", "Research report"), markdown=report.get("markdown", ""), payload=report))
        for index, followup in enumerate(state.get("follow_ups", [])):
            record = followup if isinstance(followup, dict) else {"question": str(followup)}
            db.add(Followup(session_id=session_id, id=str(record.get("id", f"F{index + 1}")), question=record.get("question", ""), payload=record))

    def queue_followup(
        self,
        session_id: str,
        question: str,
        *,
        max_active_sessions: int | None = None,
        max_queued_sessions: int | None = None,
    ) -> dict | None:
        with self.sessions.begin() as db:
            row = db.scalar(select(ResearchSession).where(ResearchSession.id == session_id).with_for_update())
            if row is None or row.status not in TERMINAL_STATUSES:
                return None
            db.scalar(select(User).where(User.id == row.owner_id).with_for_update())
            if max_active_sessions is not None:
                active = db.scalar(select(func.count()).select_from(ResearchSession).where(
                    ResearchSession.owner_id == row.owner_id,
                    ResearchSession.status.in_(["queued", "running"]),
                )) or 0
                if active >= max_active_sessions:
                    raise QuotaExceeded("Your research queue is full; wait for an existing session to finish")
            if max_queued_sessions is not None:
                queued = db.scalar(select(func.count()).select_from(ResearchSession).where(ResearchSession.status.in_(["queued", "running"]))) or 0
                if queued >= max_queued_sessions:
                    raise QuotaExceeded("Research queue is full; retry later")
            state = deepcopy(row.state)
            followup = {"id": str(uuid4()), "question": question, "created_at": now()}
            state.setdefault("follow_ups", []).append(followup)
            state["follow_up_question"] = question
            state["status"] = "queued"
            row.state, row.status, row.error, row.updated_at = state, "queued", None, now()
            self._normalize(db, session_id, state)
            self._event(db, session_id, "follow_up_queued", "orchestrator", "Follow-up queued", {"question": question, "status": "queued"})
        return session_dict(row)

    def delete_session(self, session_id: str):
        with self.sessions.begin() as db:
            db.execute(delete(ResearchSession).where(ResearchSession.id == session_id))

    def add_document(
        self,
        owner_id: str,
        title: str,
        pages: list,
        status: str,
        size_bytes: int,
        *,
        max_documents: int,
        max_bytes: int,
        max_chars: int,
    ) -> dict:
        text_chars = sum(len(page.get("text", "")) for page in pages if isinstance(page, dict) and isinstance(page.get("text"), str))
        with self.sessions.begin() as db:
            db.scalar(select(User).where(User.id == owner_id).with_for_update())
            count, stored_bytes, stored_chars = db.execute(
                select(
                    func.count(Document.id),
                    func.coalesce(func.sum(Document.size_bytes), 0),
                    func.coalesce(func.sum(Document.text_chars), 0),
                ).where(Document.owner_id == owner_id)
            ).one()
            if count >= max_documents:
                raise QuotaExceeded("Document quota reached; delete an older document before uploading another")
            if int(stored_bytes or 0) + size_bytes > max_bytes:
                raise QuotaExceeded("Stored document byte quota reached; delete an older document before uploading another")
            if int(stored_chars or 0) + text_chars > max_chars:
                raise QuotaExceeded("Stored extracted-text quota reached; delete an older document before uploading another")
            row = Document(id=str(uuid4()), owner_id=owner_id, title=title, pages=pages, extraction_status=status, size_bytes=size_bytes)
            row.text_chars = text_chars
            db.add(row)
            db.flush()
            return self.document_dict(row)

    @staticmethod
    def document_dict(row: Document) -> dict:
        return {key: getattr(row, key) for key in ("id", "title", "pages", "extraction_status", "size_bytes", "text_chars", "created_at")}

    def get_document(self, document_id: str, owner_id: str) -> dict | None:
        with self.sessions() as db:
            row = db.scalar(select(Document).where(Document.id == document_id, Document.owner_id == owner_id))
            return self.document_dict(row) if row else None

    def delete_document(self, document_id: str, owner_id: str) -> bool:
        with self.sessions.begin() as db:
            row = db.scalar(select(Document).where(Document.id == document_id, Document.owner_id == owner_id).with_for_update())
            if row is None:
                return False
            active = db.scalar(
                select(ResearchSession.id)
                .join(SessionDocument, SessionDocument.session_id == ResearchSession.id)
                .where(
                    SessionDocument.document_id == document_id,
                    ResearchSession.status.in_(["queued", "running"]),
                )
                .limit(1)
            )
            if active is not None:
                raise QuotaExceeded("The document is being used by an active research session")
            db.delete(row)
            return True
