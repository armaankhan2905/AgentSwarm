import type { ResearchEvent } from '../types';
import { authenticatedFetch } from './api';

/** Incremental SSE parser: handles CRLF, comments, multiline data, and split UTF-8 via TextDecoder. */
export function createSSEParser(emit: (event: ResearchEvent) => void) {
  let buffer = ''; let data: string[] = []; let name = ''; let id = '';
  function line(value: string) {
    if (!value) {
      if (data.length && (!name || name === 'research')) {
        try { const event = JSON.parse(data.join('\n')) as ResearchEvent;
          if (event && typeof event === 'object' && (event.id != null || id)) emit({ ...event, id: event.id ?? id });
        } catch { /* Ignore malformed frames; persisted events are replayed on reconnect. */ }
      }
      data = []; name = ''; id = ''; return;
    }
    if (value.startsWith(':')) return;
    const colon = value.indexOf(':'); const field = colon < 0 ? value : value.slice(0, colon);
    let content = colon < 0 ? '' : value.slice(colon + 1); if (content.startsWith(' ')) content = content.slice(1);
    if (field === 'data') data.push(content); if (field === 'event') name = content; if (field === 'id') id = content;
  }
  return (chunk: string) => {
    buffer += chunk;
    let index: number;
    while ((index = buffer.indexOf('\n')) >= 0) { const value = buffer.slice(0, index).replace(/\r$/, ''); buffer = buffer.slice(index + 1); line(value); }
  };
}
export async function streamEvents(sessionId: string, after: string | number, signal: AbortSignal, emit: (event: ResearchEvent) => void, connected: () => void) {
  const response = await authenticatedFetch(`/research/${encodeURIComponent(sessionId)}/stream?after=${encodeURIComponent(after)}`, { signal, headers: { Accept: 'text/event-stream' } });
  if (!response.body) throw new Error('This browser cannot read the event stream. Snapshots will still refresh.');
  connected(); const reader = response.body.getReader(); const decoder = new TextDecoder(); const parse = createSSEParser(emit);
  try { while (!signal.aborted) { const result = await reader.read(); if (result.done) { parse(decoder.decode()); break; } parse(decoder.decode(result.value, { stream: true })); } }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
