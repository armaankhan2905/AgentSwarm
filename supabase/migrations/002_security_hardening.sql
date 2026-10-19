-- Apply after 001_initial.sql. This is idempotent for installations that
-- already created the text_chars quota column from the hardened schema.
begin;

alter table public.documents add column if not exists text_chars integer not null default 0;

-- AgentSwarm uses the FastAPI service as the only application data API. Auth
-- tokens are still used for identity, but must not be able to write arbitrary
-- JSON state through the Supabase REST/Data API and bypass server validation.
revoke all on public.users, public.sessions, public.plans, public.tasks, public.sources,
    public.evidence, public.claims, public.relationships, public.conflicts, public.gaps,
    public.events, public.reports, public.followups, public.documents, public.session_documents from authenticated;
revoke all on sequence public.events_id_seq from authenticated;

commit;
