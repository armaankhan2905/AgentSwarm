import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSSEParser, streamEvents } from './stream';

afterEach(() => vi.restoreAllMocks());

describe('authenticated stream frame parsing', () => {
  it('parses split CRLF frames and multiline data without inventing events', () => {
    const received: unknown[] = []; const parse = createSSEParser(event => received.push(event));
    parse(': keep alive\r\n\r\nevent: research\r\nid: 7\r\ndata: {"id":7,\r\ndata: "session_id":"s","event_type":"stage","agent":"planner","message":"ready","timestamp":"2026-01-01T00:00:00Z"}\r\n\r\n');
    parse('event: ignored\ndata: {"id":8}\n\n');
    expect(received).toEqual([{ id: 7, session_id: 's', event_type: 'stage', agent: 'planner', message: 'ready', timestamp: '2026-01-01T00:00:00Z' }]);
  });

  it('waits for the event terminator across chunks', () => {
    const received: unknown[] = []; const parse = createSSEParser(event => received.push(event));
    parse('event: research\ndata: {"id":1,"message":"par');
    expect(received).toEqual([]);
    parse('tial"}\n\n');
    expect(received).toEqual([{ id: 1, message: 'partial' }]);
  });

  it('reconnects with both the cursor query and Last-Event-ID header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(controller) { controller.close(); } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    vi.stubGlobal('fetch', fetchMock);
    await streamEvents('session/1', 41, new AbortController().signal, () => {}, () => {});
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/research/session%2F1/stream?after=41');
    expect(new Headers(init.headers).get('Last-Event-ID')).toBe('41');
  });
});
