import { useMemo, useState } from 'react';
import { GitBranch, List, Network } from 'lucide-react';
import type { ResearchState } from '../types';
import { gapSources } from '../lib/model';
import { Badge, Button, Empty } from './ui';

export interface GraphNode { id: string; label: string; kind: 'source' | 'claim' | 'gap' }
export interface GraphEdge { from: string; to: string; label: string; contradicts?: boolean }
export function evidenceGraph(state: ResearchState): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [...state.sources.map(s => ({ id: s.id, label: s.title, kind: 'source' as const })), ...state.claims.map(c => ({ id: c.id, label: c.text, kind: 'claim' as const })), ...state.gaps.map(g => ({ id: g.id, label: g.title, kind: 'gap' as const }))];
  const edges: GraphEdge[] = [];
  for (const claim of state.claims) for (const source of state.sources) {
    const passages = state.evidence.filter(p => p.source_id === source.id);
    if (passages.some(p => claim.evidence_ids.includes(p.id))) edges.push({ from: source.id, to: claim.id, label: 'supports' });
    if (passages.some(p => claim.contradicting_evidence_ids.includes(p.id))) edges.push({ from: source.id, to: claim.id, label: 'contradicts', contradicts: true });
  }
  for (const gap of state.gaps) for (const source of gapSources(gap, state.sources, state.evidence)) edges.push({ from: source.id, to: gap.id, label: 'cited by gap' });
  return { nodes, edges };
}
export function RelationshipGraph({ state, onSource, onClaim, onGap, gapsOnly = false }: { state: ResearchState; onSource: (id: string) => void; onClaim: (id: string) => void; onGap?: (id: string) => void; gapsOnly?: boolean }) {
  const [list, setList] = useState(false);
  const graph = useMemo(() => evidenceGraph(state), [state]);
  const nodes = graph.nodes.filter(n => !gapsOnly || n.kind !== 'claim'); const ids = new Set(nodes.map(n => n.id));
  const edges = graph.edges.filter(e => ids.has(e.from) && ids.has(e.to));
  const kinds = gapsOnly ? ['source', 'gap'] : ['source', 'claim', 'gap'];
  const groups = kinds.map(kind => nodes.filter(n => n.kind === kind));
  const height = Math.max(240, Math.max(...groups.map(g => g.length), 0) * 57 + 65);
  const positions = new Map(nodes.map(node => {
    const col = kinds.indexOf(node.kind); const row = groups[col].findIndex(n => n.id === node.id);
    return [node.id, { x: 20 + col * (660 / Math.max(1, kinds.length - 1)), y: 50 + row * 57 }];
  }));
  const activate = (node: GraphNode) => { if (node.kind === 'source') onSource(node.id); if (node.kind === 'claim') onClaim(node.id); if (node.kind === 'gap') onGap?.(node.id); };
  return <section className="relationship-graph"><div className="graph-header"><span className="eyebrow"><GitBranch size={14} /> {gapsOnly ? 'SOURCE → GAP RELATIONSHIPS' : 'LIVE EVIDENCE NETWORK'}</span><Button variant="ghost" onClick={() => setList(!list)} aria-pressed={list}>{list ? <Network size={14} /> : <List size={14} />}{list ? 'Graph view' : 'Accessible list'}</Button></div>{!nodes.length ? <Empty icon={<Network size={27} />} title="Waiting for the first evidence trail">Real sources, claims, and gaps will form this network as the backend stores their relationships.</Empty> : list ? <div className="graph-list"><h3 className="sr-only">Research entities</h3>{nodes.map(n => <div key={n.id}><Badge>{n.kind}</Badge><button className="text-link" onClick={() => activate(n)}>{n.id} · {n.label}</button><ul>{edges.filter(e => e.from === n.id || e.to === n.id).map((e, i) => <li key={i}>{e.from} <span className={e.contradicts ? 'amber-text' : 'lime-text'}>{e.label}</span> {e.to}</li>)}</ul></div>)}</div> : <div className="graph-scroll"><svg viewBox={`0 0 880 ${height}`} style={{ minHeight: Math.min(height, 450) }} role="img" aria-label={`${nodes.length} real research entities connected by ${edges.length} stored evidence relationships. Switch to accessible list to inspect all relationships.`}>{kinds.map((kind, i) => <text key={kind} x={20 + i * (660 / Math.max(1, kinds.length - 1))} y={20} className="graph-column-label">{kind.toUpperCase()}S</text>)}{edges.map((edge, i) => { const a = positions.get(edge.from)!; const b = positions.get(edge.to)!; return <path key={i} d={`M ${a.x + 180} ${a.y + 18} C ${a.x + 230} ${a.y + 18}, ${b.x - 50} ${b.y + 18}, ${b.x} ${b.y + 18}`} className={`graph-edge ${edge.contradicts ? 'contradicts' : ''}`}><title>{edge.from} {edge.label} {edge.to}</title></path>; })}{nodes.map(n => { const p = positions.get(n.id)!; return <g key={n.id} className={`graph-node ${n.kind}`} transform={`translate(${p.x},${p.y})`} role="button" tabIndex={0} aria-label={`${n.kind} ${n.id}: ${n.label}`} onClick={() => activate(n)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(n); } }}><title>{n.id}: {n.label}</title><rect width="180" height="38" /><rect x="9" y="15" width="7" height="7" className="node-mark" /><text x="25" y="16" className="node-id">{n.id}</text><text x="25" y="29" className="node-label">{n.label.length > 24 ? `${n.label.slice(0, 23)}…` : n.label}</text></g>; })}</svg></div>}<footer className="graph-legend"><span><i className="lime-line" />Stored evidence link</span><span><i className="amber-line" />Contradicting passage</span><span>{nodes.length} entities / {edges.length} relations</span></footer></section>;
}
