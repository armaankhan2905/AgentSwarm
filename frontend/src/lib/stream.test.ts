import { describe, expect, it } from 'vitest';
import { createSSEParser } from './stream';

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
});
