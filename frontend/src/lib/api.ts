import type { ResearchRequest, Session, ResearchEvent, Settings, UploadedDocument, ClaimDetail } from '../types';
import { mergeEvents, normalizeDocument, normalizeDocuments, normalizeEvent, normalizeSession, array, record, text } from './model';

export const API_TIMEOUT_MS = 15_000;
let tokenProvider: () => Promise<string | null> = async () => null;
export function setTokenProvider(provider: () => Promise<string | null>) { tokenProvider = provider; }
let authInvalidated: () => void = () => {};
export function setAuthInvalidatedHandler(handler: () => void) { authInvalidated = handler; }
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); this.name = 'ApiError'; } }
export type AuthenticatedRequestInit = RequestInit & { timeoutMs?: number };
export async function authenticatedFetch(path: string, init: AuthenticatedRequestInit = {}): Promise<Response> {
  const token = await tokenProvider(); const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const controller = new AbortController(); const timeoutMs = init.timeoutMs ?? API_TIMEOUT_MS; let timedOut = false;
  const abortFromCaller = () => controller.abort(init.signal?.reason);
  if (init.signal) {
    if (init.signal.aborted) abortFromCaller();
    else init.signal.addEventListener('abort', abortFromCaller, { once: true });
  }
  const timeout = timeoutMs > 0 ? setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs) : undefined;
  const { timeoutMs: _timeoutMs, signal: _signal, ...requestInit } = init;
  let response: Response;
  try { response = await fetch(`/api${path}`, { ...requestInit, signal: controller.signal, headers }); }
  catch (error) {
    if (timedOut) throw new ApiError(`The research backend did not respond within ${Math.ceil(timeoutMs / 1000)} seconds. Retry the request.`, 408);
    if (init.signal?.aborted) throw error;
    throw new ApiError('Cannot reach the research backend. Start the API on localhost:8000 and retry.', 0);
  } finally {
    if (timeout) clearTimeout(timeout);
    init.signal?.removeEventListener('abort', abortFromCaller);
  }
  if (!response.ok) {
    const body = await response.text(); let detail = body;
    try { const data = record(JSON.parse(body)); detail = text(data.detail || data.message || data.error || data); } catch { /* Plain text errors are valid. */ }
    const error = new ApiError(detail || `Request failed (${response.status}).`, response.status);
    if (response.status === 401) authInvalidated();
    throw error;
  }
  return response;
}
async function json<T>(path: string, init?: AuthenticatedRequestInit): Promise<T> {
  const r = await authenticatedFetch(path, init); if (r.status === 204) return undefined as T;
  try { return await r.json() as T; } catch { throw new ApiError('The backend returned an invalid JSON response.', 502); }
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
  events: async (id: string, signal?: AbortSignal, after?: string | number): Promise<ResearchEvent[]> => mergeEvents([], array(await json(`${path(id)}/events${after == null ? '' : `?after=${encodeURIComponent(after)}`}`, { signal })).map(normalizeEvent).filter((event): event is ResearchEvent => event !== null)),
  cancel: (id: string) => json(`${path(id)}/cancel`, post()),
  followUp: (id: string, question: string) => json(`${path(id)}/follow-up`, post({ question })),
  remove: (id: string) => json(path(id), { method: 'DELETE' }),
  claim: (id: string, claimId: string) => json<ClaimDetail>(`${path(id)}/claims/${encodeURIComponent(claimId)}`),
  documents: async (signal?: AbortSignal): Promise<UploadedDocument[]> => normalizeDocuments(await json('/documents', { signal })),
  upload: async (file: File) => { const body = new FormData(); body.append('file', file); const document = normalizeDocument(await json('/documents', { method: 'POST', body, timeoutMs: 30_000 })); if (!document) throw new ApiError('The backend returned an invalid document.', 502); return document; },
  removeDocument: (id: string) => json(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  export: async (id: string, format: 'markdown' | 'pdf') => {
    const response = await authenticatedFetch(`${path(id)}/export?format=${format}`, { timeoutMs: 30_000 });
    const blob = await response.blob(); let url: string | undefined; let anchor: HTMLAnchorElement | undefined;
    try {
      url = URL.createObjectURL(blob);
      anchor = document.createElement('a'); anchor.href = url; anchor.download = `agentswarm-${id}.${format === 'markdown' ? 'md' : 'pdf'}`;
      document.body.append(anchor); anchor.click();
    } finally {
      anchor?.remove();
      if (url) URL.revokeObjectURL(url);
    }
  },
};
