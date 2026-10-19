-- Apply after 001_initial.sql and 002_security_hardening.sql.
-- The FastAPI service is the only application data API. The browser may use
-- Supabase Auth, but it must not use the table REST API for application DML.
begin;

-- Keep the application schema closed to browser roles. service_role is the
-- server-only Supabase role and is intentionally separate from authenticated.
revoke all on schema public from public, anon, authenticated;
grant usage on schema public to service_role;

grant select, insert, update, delete on public.users, public.sessions, public.plans,
    public.tasks, public.sources, public.evidence, public.claims, public.relationships,
    public.conflicts, public.gaps, public.events, public.reports, public.followups,
    public.documents, public.session_documents to service_role;
grant usage, select on sequence public.events_id_seq to service_role;

-- Also make the migration/runtime role explicit. A deployment that uses a
-- separate least-privilege role must grant the same privileges to that role
-- before setting DATABASE_URL; this block covers the common same-role setup.
do $$
declare
    table_name text;
begin
    execute format('grant usage on schema public to %I', current_user);
    foreach table_name in array array[
        'users', 'sessions', 'plans', 'tasks', 'sources', 'evidence', 'claims',
        'relationships', 'conflicts', 'gaps', 'events', 'reports', 'followups',
        'documents', 'session_documents'
    ] loop
        execute format(
            'grant select, insert, update, delete on table public.%I to %I',
            table_name, current_user
        );
    end loop;
    execute format('grant usage, select on sequence public.events_id_seq to %I', current_user);
end $$;

alter default privileges in schema public revoke all on tables from public, anon, authenticated;
alter default privileges in schema public grant select, insert, update, delete on tables to service_role;
alter default privileges in schema public grant usage, select on sequences to service_role;

do $$
begin
    execute format(
        'alter default privileges in schema public grant select, insert, update, delete on tables to %I',
        current_user
    );
    execute format(
        'alter default privileges in schema public grant usage, select on sequences to %I',
        current_user
    );
end $$;

-- Fail the deployment if a later schema edit accidentally weakens the RLS
-- boundary. FORCE RLS is required because application tables contain user data.
do $$
declare
    table_name text;
    rls_enabled boolean;
    rls_forced boolean;
begin
    foreach table_name in array array[
        'users', 'sessions', 'plans', 'tasks', 'sources', 'evidence', 'claims',
        'relationships', 'conflicts', 'gaps', 'events', 'reports', 'followups',
        'documents', 'session_documents'
    ] loop
        select c.relrowsecurity, c.relforcerowsecurity
          into rls_enabled, rls_forced
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relname = table_name and c.relkind = 'r';
        if not coalesce(rls_enabled, false) or not coalesce(rls_forced, false) then
            raise exception 'RLS is not enabled and forced for public.%', table_name;
        end if;
    end loop;
end $$;

commit;
