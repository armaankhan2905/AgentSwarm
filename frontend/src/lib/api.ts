import type { ResearchRequest, Session, ResearchEvent, Settings, UploadedDocument, ClaimDetail } from '../types';
import { normalizeSession, array, record, text } from './model';

let tokenProvider: () => Promise<string | null> = async () => null;
export function setTokenProvider(provider: () => Promise<string | null>) { tokenProvider = provider; }
let authInvalidated: () => void = () => {};
export function setAuthInvalidatedHandler(handler: () => void) { authInvalidated = handler; }
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); this.name = 'ApiError'; } }
export async function authenticatedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await tokenProvider(); const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try { response = await fetch(`/api${path}`, { ...init, headers }); }
  catch (error) { if (init.signal?.aborted) throw error; throw new ApiError('Cannot reach the research backend. Start the API on localhost:8000 and retry.', 0); }
  if (!response.ok) {
    const body = await response.text(); let detail = body;
    try { const data = record(JSON.parse(body)); detail = text(data.detail || data.message || data.error || data); } catch { /* Plain text errors are valid. */ }
    const error = new ApiError(detail || `Request failed (${response.status}).`, response.status);
    if (response.status === 401) authInvalidated();
    throw error;
  }
  return response;
}
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authenticatedFetch(path, init); return r.status === 204 ? undefined as T : r.json();
}
const post = (body?: unknown): RequestInit => ({ method: 'POST', ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
const path = (id: string) => `/research/${encodeURIComponent(id)}`;
export const api = {
  bootstrap: () => json<{ auth_mode?: string; supabase_url?: string; supabase_anon_key?: string }>('/bootstrap'),
  settings: () => json<Settings>('/settings'),
  testSettings: () => json<unknown>('/settings/test', post()),
  sessions: async (search: string, sort: string, signal?: AbortSignal): Promise<Session[]> => array(await json(`/research?${new URLSearchParams({ search, sort })}`, { signal })).map(normalizeSession),
  session: async (id: string, signal?: AbortSignal) => normalizeSession(await json(path(id), { signal })),
  create: async (request: ResearchRequest) => normalizeSession(await json('/research', post(request))),
  events: async (id: string, signal?: AbortSignal) => array<ResearchEvent>(await json(`${path(id)}/events`, { signal })),
  cancel: (id: string) => json(`${path(id)}/cancel`, post()),
  followUp: (id: string, question: string) => json(`${path(id)}/follow-up`, post({ question })),
  remove: (id: string) => json(path(id), { method: 'DELETE' }),
  claim: (id: string, claimId: string) => json<ClaimDetail>(`${path(id)}/claims/${encodeURIComponent(claimId)}`),
  upload: (file: File) => { const body = new FormData(); body.append('file', file); return json<UploadedDocument>('/documents', { method: 'POST', body }); },
  export: async (id: string, format: 'markdown' | 'pdf') => {
    const response = await authenticatedFetch(`${path(id)}/export?format=${format}`);
    const blob = await response.blob(); const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `agentswarm-${id}.${format === 'markdown' ? 'md' : 'pdf'}`;
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
