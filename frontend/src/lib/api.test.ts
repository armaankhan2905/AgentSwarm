import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, authenticatedFetch, setTokenProvider } from './api';

describe('authenticated API behavior', () => {
  beforeEach(() => { setTokenProvider(async () => 'test-token'); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); setTokenProvider(async () => null); });

  it('adds the bearer token and converts a stalled request into a retryable timeout', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }));
    vi.stubGlobal('fetch', fetchMock);
    const request = authenticatedFetch('/slow', { timeoutMs: 50 });
    const assertion = expect(request).rejects.toMatchObject({ name: 'ApiError', status: 408 });
    await vi.advanceTimersByTimeAsync(50);
    await assertion;
    expect(fetchMock).toHaveBeenCalledWith('/api/slow', expect.objectContaining({ signal: expect.any(AbortSignal), headers: expect.any(Headers) }));
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer test-token');
  });

  it('normalizes the authenticated document list and encodes document deletion IDs', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 'doc-1', title: null, extraction_status: 'ready' }]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    const documents = await api.documents();
    await api.removeDocument('doc/1');
    expect(documents[0].title).toBe('Untitled PDF');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/documents/doc%2F1');
  });

  it('revokes every export object URL even when the browser click fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('report', { status: 200 })); vi.stubGlobal('fetch', fetchMock);
    const anchors: Array<{ href: string; download: string; click: () => void; remove: ReturnType<typeof vi.fn> }> = [];
    vi.stubGlobal('document', { body: { append: vi.fn() }, createElement: vi.fn(() => { const anchor = { href: '', download: '', click: vi.fn(() => { throw new Error('blocked'); }), remove: vi.fn() }; anchors.push(anchor); return anchor; }) });
    const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test'); const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    await expect(api.export('session-1', 'pdf')).rejects.toThrow('blocked');
    expect(anchors[0].remove).toHaveBeenCalledOnce(); expect(createUrl).toHaveBeenCalledOnce(); expect(revokeUrl).toHaveBeenCalledWith('blob:test');
  });

  it('leaves caller cancellation distinct from the request timeout', async () => {
    const controller = new AbortController(); const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => { if (init?.signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError')); return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })); }); vi.stubGlobal('fetch', fetchMock);
    const request = authenticatedFetch('/cancelled', { signal: controller.signal, timeoutMs: 10_000 }); controller.abort();
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
  });
});
