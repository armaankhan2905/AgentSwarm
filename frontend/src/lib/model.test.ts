import { describe, expect, it } from 'vitest';
import { evidenceGraph } from '../components/Graph';
import { documentHasActiveResearch, mergeEvents, normalizeSession, normalizeState, safeUrl } from './model';

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

  it('keeps the browser timeline bounded while retaining the newest cursor window', () => {
    const event = (id: number) => ({ id, session_id: 's', event_type: 'stage', agent: 'planner', message: String(id), timestamp: `2026-01-01T00:00:${String(id).padStart(2, '0')}Z` });
    expect(mergeEvents([], [event(1), event(2), event(3)], 2).map(e => e.id)).toEqual([2, 3]);
  });

  it('turns malformed report and graph collections into safe empty or text values', () => {
    const state = normalizeState({ plan: { subquestions: { invalid: true } }, report: { markdown: { invalid: true }, sections: { invalid: true }, citation_audit: { warnings: { invalid: true } } }, sources: [{ id: 'S1' }], claims: [{ id: 'C1', text: null, evidence_ids: null, contradicting_evidence_ids: null }] });
    expect(state.plan.subquestions).toEqual([]);
    expect(state.report.markdown).toBe('');
    expect(state.report.sections).toEqual([]);
    expect(state.claims[0].evidence_ids).toEqual([]);
  });

  it('marks documents reported as active as non-deletable', () => {
    expect(documentHasActiveResearch({ id: 'doc-1', in_use: true })).toBe(true);
    expect(documentHasActiveResearch({ id: 'doc-2', active_session_count: 0 })).toBe(false);
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
