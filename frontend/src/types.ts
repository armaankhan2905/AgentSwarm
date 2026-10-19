export type RecordData = Record<string, unknown>;
export type SessionStatus = 'queued' | 'running' | 'completed' | 'incomplete' | 'failed' | 'cancelled' | string;
export interface ResearchRequest {
  question: string; depth: 'quick' | 'standard' | 'deep'; source_types: string[];
  date_from?: string; date_to?: string; context?: string; document_ids: string[];
}
export interface Source {
  id: string; title: string; url?: string; domain?: string; source_type?: string;
  retrieved_at?: string; publication_date?: string; authors?: string[]; doi?: string;
  retrieval_status?: string; access_limitations?: string[] | string; metadata?: RecordData;
}
export interface Passage { id: string; source_id: string; text: string; location?: string; retrieved_at?: string; subquestion_id?: string }
export interface Claim {
  id: string; text: string; subquestion_id?: string; status: string; explanation?: string;
  evidence_ids: string[]; contradicting_evidence_ids: string[]; missing_evidence?: string[] | string;
  requires_follow_up?: boolean; verified_at?: string;
}
export interface Conflict {
  id: string; description: string; claim_ids: string[]; source_ids: string[]; evidence_ids: string[];
  conflict_type?: string; positions?: unknown; explanation?: string; resolved?: boolean; follow_up?: unknown;
}
export interface Gap {
  id: string; title: string; description: string; category: 'EVIDENCE_BACKED' | 'POTENTIAL' | string;
  source_ids: string[]; evidence_ids: string[]; subquestion_id?: string; existing_approaches?: unknown;
  significance?: string; opportunity?: string; limitations?: string[] | string; next_steps?: string[] | string;
}
export interface Subquestion { id: string; question: string; priority?: string | number; source_types?: string[]; queries?: string[]; evidence_requirements?: string[] | string }
export interface Plan { objective?: string; scope?: unknown; subquestions?: Subquestion[]; completion_criteria?: string[]; known_limitations?: string[]; budget?: RecordData }
export interface Report {
  title?: string; markdown?: string; sections?: { id: string; title: string; content: string }[];
  citation_audit?: { passed?: boolean; warnings?: string[] }; created_at?: string;
}
export interface ResearchState {
  session_id?: string; question?: string; request?: Partial<ResearchRequest>; plan: Plan;
  sources: Source[]; evidence: Passage[]; claims: Claim[]; conflicts: Conflict[]; gaps: Gap[];
  report: Report; budget: RecordData; follow_ups: unknown[]; warnings: string[]; node_states: Record<string, unknown>;
}
export interface Session {
  id: string; question: string; status: SessionStatus; created_at?: string; updated_at?: string;
  error?: unknown; summary?: { source_count?: number; evidence_count?: number; claim_count?: number }; state: ResearchState; [key: string]: unknown;
}
export interface ResearchEvent { id: string | number; session_id: string; event_type: string; agent: string; message: string; data?: RecordData; timestamp: string }
export interface Settings extends RecordData { auth_mode?: string; supabase_url?: string; supabase_anon_key?: string; integrations?: unknown; limits?: unknown }
export interface UploadedDocument {
  id: string;
  title?: string;
  pages?: unknown[];
  text_chars?: number;
  extraction_status?: string;
  size_bytes?: number;
  created_at?: string;
  in_use?: boolean;
  active_session_count?: number;
  deletable?: boolean;
  [key: string]: unknown;
}
export interface ClaimDetail extends Claim { evidence: Passage[]; sources: Source[] }
