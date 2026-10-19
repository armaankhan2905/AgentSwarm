import type { ResearchState, Session, RecordData, ResearchEvent, Source, Passage } from '../types';

export function record(value: unknown): RecordData { return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordData : {}; }
export function array<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
export function text(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join(' · ');
  if (typeof value === 'object') return Object.entries(record(value)).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${text(v)}`).join(' · ');
  return String(value);
}
export function normalizeState(raw: unknown): ResearchState {
  const s = record(raw);
  return { ...s, plan: record(s.plan), sources: array(s.sources), evidence: array(s.evidence),
    claims: array(s.claims).map(c => { const v = record(c); return { ...v, evidence_ids: array(v.evidence_ids), contradicting_evidence_ids: array(v.contradicting_evidence_ids) }; }),
    conflicts: array(s.conflicts).map(c => { const v = record(c); return { ...v, claim_ids: array(v.claim_ids), source_ids: array(v.source_ids), evidence_ids: array(v.evidence_ids) }; }),
    gaps: array(s.gaps).map(g => { const v = record(g); return { ...v, source_ids: array(v.source_ids), evidence_ids: array(v.evidence_ids) }; }),
    report: record(s.report), budget: record(s.budget), follow_ups: array(s.follow_ups), warnings: array(s.warnings), node_states: record(s.node_states),
  } as unknown as ResearchState;
}
export function normalizeSession(raw: unknown): Session {
  const s = record(raw); const rawState = record(s.state); const state = normalizeState({ ...rawState, request: rawState.request ?? s.request });
  return { ...s, id: String(s.id ?? s.session_id ?? ''), question: text(s.question || state.question || state.request?.question), status: text(s.status) || 'queued', state } as Session;
}
export function mergeEvents(existing: ResearchEvent[], incoming: ResearchEvent[]): ResearchEvent[] {
  const map = new Map(existing.map(e => [String(e.id), e]));
  for (const event of incoming) if (event && event.id != null) map.set(String(event.id), event);
  return [...map.values()].sort((a, b) => {
    const an = Number(a.id), bn = Number(b.id);
    return Number.isFinite(an) && Number.isFinite(bn) ? an - bn : (Date.parse(a.timestamp) || 0) - (Date.parse(b.timestamp) || 0);
  });
}
export function safeUrl(value: string | undefined): string | undefined {
  if (!value) return;
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase().replace(/^\[/, '').replace(/\]$/, '').replace(/\.$/, '');
    const octets = hostname.split('.').map(Number);
    const validIpv4 = octets.length === 4 && octets.every(part => Number.isInteger(part) && part >= 0 && part <= 255);
    const privateIpv4 = validIpv4 && (
      octets[0] === 0 || octets[0] === 10 || octets[0] === 127 || octets[0] === 169 && octets[1] === 254
      || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31 || octets[0] === 192 && octets[1] === 168
      || octets[0] === 100 && octets[1] >= 64 && octets[1] <= 127 || octets[0] === 192 && octets[1] === 0
      || octets[0] === 198 && octets[1] === 18 || octets[0] === 198 && octets[1] === 19
      || octets[0] === 198 && octets[1] === 51 && octets[2] === 100 || octets[0] === 203 && octets[1] === 0 && octets[2] === 113
    );
    const privateIpv6 = hostname === '::' || hostname === '::1' || /^f[cd]/.test(hostname)
      || /^fe[89ab]/.test(hostname) || /^::ffff:(0:)?(0?127|10|169\.254|192\.168)\./.test(hostname);
    const privateHost = hostname === 'localhost' || hostname.endsWith('.localhost') || hostname.endsWith('.local')
      || hostname.endsWith('.internal') || privateIpv4 || privateIpv6;
    if ((url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password && !privateHost) return url.href;
  } catch { /* Untrusted provider URL. */ }
}
export function formatDate(value?: string): string {
  if (!value) return 'Not recorded';
  const d = new Date(value); return Number.isNaN(d.getTime()) ? 'Not recorded' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
export function isActive(status: string): boolean { return status === 'queued' || status === 'running'; }
export function gapSources(gap: { source_ids: string[]; evidence_ids: string[] }, sources: Source[], evidence: Passage[]): Source[] {
  const ids = new Set([...gap.source_ids, ...evidence.filter(e => gap.evidence_ids.includes(e.id)).map(e => e.source_id)]);
  return sources.filter(s => ids.has(s.id));
}
