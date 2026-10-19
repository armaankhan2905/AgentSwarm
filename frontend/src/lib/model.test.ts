import { describe, expect, it } from 'vitest';
import { evidenceGraph } from '../components/Graph';
import { mergeEvents, normalizeSession, normalizeState, safeUrl } from './model';

describe('contract mapping', () => {
  it('keeps flexible backend fields while defaulting absent collections to honest empties', () => {
    const session = normalizeSession({ id: 'abc', status: 'running', question: 'A real question', state: { plan: { objective: 'Find evidence' }, claims: [{ id: 'C1', text: 'Claim', status: 'SUPPORTED' }] } });
    expect(session.id).toBe('abc');
    expect(session.state.plan.objective).toBe('Find evidence');
    expect(session.state.claims).toHaveLength(1);
    expect(session.state.sources).toEqual([]);
    expect(normalizeState(null).warnings).toEqual([]);
  });

  it('merges replayed and live events by id in timeline order', () => {
    const event = (id: number, message: string) => ({ id, session_id: 's', event_type: 'stage', agent: 'planner', message, timestamp: `2026-01-01T00:00:0${id}Z` });
    expect(mergeEvents([event(1, 'old')], [event(1, 'replayed update'), event(2, 'new')]).map(e => e.message)).toEqual(['replayed update', 'new']);
  });

  it('rejects unsafe citation URLs', () => {
    expect(safeUrl('https://example.com/paper')).toBe('https://example.com/paper');
    expect(safeUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeUrl('http://127.0.0.1/admin')).toBeUndefined();
    expect(safeUrl('http://169.254.169.254/latest/meta-data')).toBeUndefined();
    expect(safeUrl('http://[fd00::1]/admin')).toBeUndefined();
    expect(safeUrl('https://user:password@example.com/paper')).toBeUndefined();
    expect(safeUrl('not a url')).toBeUndefined();
  });
});

describe('evidence graph', () => {
  it('only creates relationships backed by stored evidence ids', () => {
    const graph = evidenceGraph(normalizeState({ sources: [{ id: 'S1', title: 'Paper' }, { id: 'S2', title: 'Other' }], evidence: [{ id: 'E1', source_id: 'S1', text: 'passage' }], claims: [{ id: 'C1', text: 'supported', status: 'SUPPORTED', evidence_ids: ['E1'], contradicting_evidence_ids: [] }, { id: 'C2', text: 'unsupported', status: 'SUPPORTED', evidence_ids: ['missing'], contradicting_evidence_ids: [] }] }));
    expect(graph.edges).toEqual([{ from: 'S1', to: 'C1', label: 'supports' }]);
    expect(graph.nodes.map(node => node.id)).toEqual(['S1', 'S2', 'C1', 'C2']);
  });
});
