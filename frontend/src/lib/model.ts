import type { ResearchState, Session, RecordData, ResearchEvent, Source, Passage, UploadedDocument } from '../types';

export const MAX_REPLAY_EVENTS = 500;

export function record(value: unknown): RecordData { return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordData : {}; }
export function array<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
export function text(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join(' · ');
  if (typeof value === 'object') return Object.entries(record(value)).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${text(v)}`).join(' · ');
  return String(value);
}

function stringList(value: unknown): string[] { return array(value).map(text).filter(Boolean); }

function normalizeSource(raw: unknown): Source | null {
  const value = record(raw); const id = text(value.id);
  return id ? { ...value, id, title: text(value.title) || 'Untitled source' } as Source : null;
}

function normalizePassage(raw: unknown): Passage | null {
  const value = record(raw); const id = text(value.id); const sourceId = text(value.source_id);
  return id && sourceId ? { ...value, id, source_id: sourceId, text: text(value.text) } as Passage : null;
}

function normalizeClaim(raw: unknown): RecordData | null {
  const value = record(raw); const id = text(value.id);
  return id ? { ...value, id, text: text(value.text), status: text(value.status) || 'UNVERIFIABLE', evidence_ids: stringList(value.evidence_ids), contradicting_evidence_ids: stringList(value.contradicting_evidence_ids) } : null;
}

function normalizeConflict(raw: unknown): RecordData | null {
  const value = record(raw); const id = text(value.id);
  return id ? { ...value, id, description: text(value.description), claim_ids: stringList(value.claim_ids), source_ids: stringList(value.source_ids), evidence_ids: stringList(value.evidence_ids) } : null;
}

function normalizeGap(raw: unknown): RecordData | null {
  const value = record(raw); const id = text(value.id);
  return id ? { ...value, id, title: text(value.title), description: text(value.description), category: text(value.category) || 'POTENTIAL', source_ids: stringList(value.source_ids), evidence_ids: stringList(value.evidence_ids) } : null;
}

function normalizePlan(raw: unknown): RecordData {
  const value = record(raw);
  const subquestions = array(value.subquestions).map((rawQuestion, index) => {
    const question = record(rawQuestion); const id = text(question.id) || `subquestion-${index + 1}`;
    return { ...question, id, question: text(question.question), source_types: stringList(question.source_types), queries: stringList(question.queries), evidence_requirements: question.evidence_requirements };
  });
  return { ...value, subquestions, completion_criteria: stringList(value.completion_criteria), known_limitations: stringList(value.known_limitations) };
}

function normalizeReport(raw: unknown): RecordData {
  const value = record(raw);
  const sections = array(value.sections).map((rawSection, index) => {
    const section = record(rawSection); const id = text(section.id) || `section-${index + 1}`;
    return { ...section, id, title: text(section.title) || 'Untitled section', content: text(section.content) };
  });
  const audit = record(value.citation_audit);
  return { ...value, markdown: typeof value.markdown === 'string' ? value.markdown : '', sections, citation_audit: value.citation_audit == null ? undefined : { ...audit, warnings: stringList(audit.warnings) } };
}

export function normalizeDocument(raw: unknown): UploadedDocument | null {
  const value = record(raw); const id = text(value.id);
  if (!id) return null;
  const document = { ...value, id, title: text(value.title) || 'Untitled PDF', extraction_status: text(value.extraction_status) || 'not reported' } as UploadedDocument;
  if (Array.isArray(value.pages)) document.pages = value.pages;
  if (typeof value.text_chars === 'number' && Number.isFinite(value.text_chars)) document.text_chars = value.text_chars;
  if (typeof value.size_bytes === 'number' && Number.isFinite(value.size_bytes)) document.size_bytes = value.size_bytes;
  return document;
}

export function normalizeDocuments(raw: unknown): UploadedDocument[] { const value = Array.isArray(raw) ? raw : record(raw).documents; return array(value).map(normalizeDocument).filter((document): document is UploadedDocument => document !== null); }

export function normalizeEvent(raw: unknown): ResearchEvent | null {
  const value = record(raw); const id = value.id;
  if ((typeof id !== 'string' && typeof id !== 'number') || text(id) === '') return null;
  return { ...value, id, session_id: text(value.session_id), event_type: text(value.event_type) || 'research', agent: text(value.agent) || 'system', message: text(value.message), timestamp: text(value.timestamp), data: record(value.data) } as ResearchEvent;
}

export function documentHasActiveResearch(document: UploadedDocument): boolean {
  if (document.in_use === true) return true;
  if (typeof document.active_session_count === 'number' && document.active_session_count > 0) return true;
  const statuses = array(document.active_session_statuses).map(value => text(value).toLowerCase());
  return statuses.some(status => status === 'queued' || status === 'running');
}
export function normalizeState(raw: unknown): ResearchState {
  const s = record(raw);
  const rawRequest = record(s.request);
  const request = { ...rawRequest, source_types: stringList(rawRequest.source_types), document_ids: stringList(rawRequest.document_ids) };
  return { ...s, request, plan: normalizePlan(s.plan), sources: array(s.sources).map(normalizeSource).filter((source): source is Source => source !== null), evidence: array(s.evidence).map(normalizePassage).filter((passage): passage is Passage => passage !== null),
    claims: array(s.claims).map(normalizeClaim).filter((claim): claim is RecordData => claim !== null),
    conflicts: array(s.conflicts).map(normalizeConflict).filter((conflict): conflict is RecordData => conflict !== null),
    gaps: array(s.gaps).map(normalizeGap).filter((gap): gap is RecordData => gap !== null),
    report: normalizeReport(s.report), budget: record(s.budget), follow_ups: array(s.follow_ups), warnings: stringList(s.warnings), node_states: record(s.node_states),
  } as unknown as ResearchState;
}
export function normalizeSession(raw: unknown): Session {
  const s = record(raw); const rawState = record(s.state); const state = normalizeState({ ...rawState, request: rawState.request ?? s.request });
  return { ...s, id: String(s.id ?? s.session_id ?? ''), question: text(s.question || state.question || state.request?.question), status: text(s.status) || 'queued', state } as Session;
}
export function mergeEvents(existing: ResearchEvent[], incoming: ResearchEvent[], maxEvents = MAX_REPLAY_EVENTS): ResearchEvent[] {
  const map = new Map(existing.map(e => [String(e.id), e]));
  for (const event of incoming) if (event && event.id != null) map.set(String(event.id), event);
  const sorted = [...map.values()].sort((a, b) => {
    const an = Number(a.id), bn = Number(b.id);
    return Number.isFinite(an) && Number.isFinite(bn) ? an - bn : (Date.parse(a.timestamp) || 0) - (Date.parse(b.timestamp) || 0);
  });
  const limit = Number.isInteger(maxEvents) && maxEvents > 0 ? maxEvents : MAX_REPLAY_EVENTS;
  return sorted.slice(-limit);
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
  const sourceIds = Array.isArray(gap?.source_ids) ? gap.source_ids : []; const evidenceIds = Array.isArray(gap?.evidence_ids) ? gap.evidence_ids : [];
  const ids = new Set([...sourceIds, ...evidence.filter(e => evidenceIds.includes(e.id)).map(e => e.source_id)]);
  return sources.filter(s => ids.has(s.id));
}
