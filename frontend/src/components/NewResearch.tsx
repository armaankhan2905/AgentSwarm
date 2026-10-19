import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { ArrowDown, ArrowRight, BookOpen, Check, FileText, Globe2, Layers, Paperclip, RefreshCw, ScanLine, ShieldCheck, SlidersHorizontal, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import { documentHasActiveResearch } from '../lib/model';
import type { ResearchRequest, UploadedDocument } from '../types';
import { Badge, Button, Modal, Notice } from './ui';

const depthOptions = [
  { id: 'quick', name: 'Quick scan', detail: 'A focused pass for a fast orientation.' },
  { id: 'standard', name: 'Standard', detail: 'Balanced breadth, depth, and verification.' },
  { id: 'deep', name: 'Deep dive', detail: 'More agents, sources, and scrutiny.' },
] as const;

const sourceOptions = [
  { id: 'web', name: 'Web research', detail: 'Current public sources', icon: Globe2 },
  { id: 'academic', name: 'Academic', detail: 'Papers and scholarly sources', icon: BookOpen },
  { id: 'document', name: 'Your documents', detail: 'Search uploaded PDFs', icon: FileText },
] as const;

export function NewResearch({ onCreated }: { onCreated: (id: string) => void }) {
  const [question, setQuestion] = useState(''); const [depth, setDepth] = useState<ResearchRequest['depth']>('standard');
  const [sources, setSources] = useState<string[]>(['web', 'academic']); const [context, setContext] = useState('');
  const [dateFrom, setDateFrom] = useState(''); const [dateTo, setDateTo] = useState(''); const [advanced, setAdvanced] = useState(false);
  const [documents, setDocuments] = useState<UploadedDocument[]>([]); const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true); const [uploading, setUploading] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [documentError, setDocumentError] = useState(''); const [documentStatus, setDocumentStatus] = useState('');
  const [deleting, setDeleting] = useState<UploadedDocument | null>(null); const [deletingId, setDeletingId] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshDocuments = useCallback(async () => {
    setDocumentsLoading(true); setDocumentError('');
    try { setDocuments(await api.documents()); }
    catch (e) { setDocumentError((e as Error).message); }
    finally { setDocumentsLoading(false); }
  }, []);

  useEffect(() => { const controller = new AbortController(); void (async () => { setDocumentsLoading(true); setDocumentError(''); try { setDocuments(await api.documents(controller.signal)); } catch (e) { if (!controller.signal.aborted) setDocumentError((e as Error).message); } finally { if (!controller.signal.aborted) setDocumentsLoading(false); } })(); return () => controller.abort(); }, []);

  function toggleSource(type: string) { const selected = sources.includes(type); if (type === 'document' && selected) setSelectedIds([]); setSources(old => selected ? old.filter(s => s !== type) : [...old, type]); }

  function toggleDocument(document: UploadedDocument) {
    setDocumentError(''); setDocumentStatus('');
    const selected = selectedIds.includes(document.id); const next = selected ? selectedIds.filter(id => id !== document.id) : [...selectedIds, document.id];
    setSelectedIds(next); setSources(current => next.length ? current.includes('document') ? current : [...current, 'document'] : current.filter(source => source !== 'document'));
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return; setUploading(true); setError(''); setDocumentError(''); setDocumentStatus('');
    try {
      const remaining = 30 - selectedIds.length;
      if (remaining <= 0 || files.length > remaining) throw new Error(remaining > 0 ? `Select at most ${remaining} more PDF document${remaining === 1 ? '' : 's'}.` : 'You already selected the maximum of 30 PDF documents.');
      for (const file of Array.from(files)) {
        if (!file.name.toLowerCase().endsWith('.pdf')) throw new Error('Only PDF documents can be uploaded.');
        const document = await api.upload(file);
        setDocuments(old => [...old.filter(item => item.id !== document.id), document]);
        setSelectedIds(old => old.includes(document.id) ? old : [...old, document.id]);
        setSources(old => old.includes('document') ? old : [...old, 'document']);
      }
      setDocumentStatus(`${files.length} PDF${files.length === 1 ? '' : 's'} ready for this brief.`);
    } catch (e) { setError((e as Error).message); } finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  }

  function requestDelete(document: UploadedDocument) {
    setDocumentError(''); setDocumentStatus('');
    if (selectedIds.includes(document.id)) { setDocumentError('Remove this document from the research brief before deleting it.'); return; }
    if (documentHasActiveResearch(document)) { setDocumentError('This document is being used by an active investigation and cannot be deleted yet.'); return; }
    setDeleting(document);
  }

  async function removeDocument() {
    if (!deleting) return;
    setDeletingId(deleting.id); setDocumentError('');
    try {
      await api.removeDocument(deleting.id);
      setDocuments(old => old.filter(document => document.id !== deleting.id));
      setDocumentStatus(`${deleting.title || 'Document'} was deleted.`); setDeleting(null);
    } catch (e) { setDocumentError((e as Error).message); }
    finally { setDeletingId(''); }
  }

  async function submit() {
    setError('');
    if (question.trim().length < 10) { setError('Give the agents a research question of at least 10 characters.'); return; }
    if (!sources.length) { setError('Select at least one source type.'); return; }
    if (dateFrom && dateTo && dateFrom > dateTo) { setError('The start date must come before the end date.'); return; }
    if (sources.includes('document') && !selectedIds.length) { setError('Select or upload a PDF to use document sources.'); return; }
    if (selectedIds.length > 30) { setError('Select no more than 30 PDF documents.'); return; }
    setBusy(true);
    try {
      const session = await api.create({ question: question.trim(), depth, source_types: sources, document_ids: selectedIds, ...(context.trim() ? { context: context.trim() } : {}), ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) });
      if (!session.id) throw new Error('The API did not return a session ID.'); onCreated(session.id);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return <div className="new-research">
    <section className="hero"><div className="hero-copy"><span className="eyebrow"><span className="tiny-square" /> THE EVIDENCE-FIRST RESEARCH LAB</span><h1>Go beyond<br />the <span className="pixel-text">first answer<span className="cursor">_</span></span></h1><p>A question starts the swarm. Watch agents investigate, challenge claims, and connect the evidence — all in the open.</p><a className="text-link" href="#research-form">Start an investigation <ArrowDown size={15} /></a></div><div className="hero-visual" aria-hidden="true"><div className="orbital orbit-one" /><div className="orbital orbit-two" /><div className="visual-corner tl">+</div><div className="visual-corner br">+</div><div className="lab-glyph"><i /><i /><i /><i /><i /><i /><i /><i /><i /></div><span className="visual-label label-a">01 / QUESTION</span><span className="visual-label label-b">02 / INVESTIGATE</span><span className="visual-label label-c">03 / VERIFY</span><div className="visual-note">BUILT TO QUESTION.<br />DESIGNED TO SUBSTANTIATE.</div></div></section>
    <section id="research-form" className="research-grid"><form className="research-form panel" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className="panel-top"><span className="eyebrow">01 / RESEARCH BRIEF</span><span className="small mono muted">A good question is a good beginning.</span></div>
      <label htmlFor="question" className="form-heading">What are we investigating?</label><div className="question-box"><textarea id="question" required minLength={10} maxLength={4000} rows={4} value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask a complex question. Look for competing approaches, emerging evidence, or an unsolved problem…" /><div className="question-meta"><span><ScanLine size={13} /> Open-ended questions welcome</span><span>{question.length}/4000</span></div></div>
      <fieldset><legend>Research depth</legend><div className="depth-options">{depthOptions.map(option => <button type="button" key={option.id} className={`depth-card ${depth === option.id ? 'selected' : ''}`} onClick={() => setDepth(option.id)}><span>{depth === option.id ? <Check size={14} /> : <span className="depth-number">{option.id === 'quick' ? '01' : option.id === 'standard' ? '02' : '03'}</span>}</span><strong>{option.name}</strong><span>{option.detail}</span></button>)}</div></fieldset>
      <fieldset><legend>Research sources <span className="small muted">Choose what the swarm should inspect.</span></legend><div className="source-options">{sourceOptions.map(option => { const Icon = option.icon; const selected = sources.includes(option.id); return <button type="button" key={option.id} className={`source-chip ${selected ? 'selected' : ''}`} onClick={() => toggleSource(option.id)}><span className="check-box">{selected && <Check size={13} />}</span><Icon size={16} /><span><strong>{option.name}</strong><small>{option.detail}</small></span></button>; })}</div></fieldset>
      <DocumentLibrary documents={documents} selectedIds={selectedIds} loading={documentsLoading} uploading={uploading} deletingId={deletingId} fileRef={fileRef} documentError={documentError} documentStatus={documentStatus} onRefresh={() => void refreshDocuments()} onToggle={toggleDocument} onUpload={upload} onDelete={requestDelete} />
      <div className="form-tools"><Button type="button" variant="ghost" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}><SlidersHorizontal size={15} />{advanced ? 'Hide advanced options' : 'Show advanced options'}</Button><span className="small muted">You can refine dates and context before the run.</span></div>
      {advanced && <div className="advanced-options"><label>Date from<input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} /></label><label>Date to<input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} /></label><label className="context-field">Additional context<textarea rows={3} maxLength={3000} value={context} onChange={e => setContext(e.target.value)} placeholder="What should the agents know before they begin?" /></label></div>}
      {error && <Notice>{error}</Notice>}<div className="form-submit"><span className="small muted"><ShieldCheck size={14} /> Your brief is sent to the authenticated research API.</span><Button variant="primary" type="submit" busy={busy}>Launch the swarm <ArrowRight size={16} /></Button></div>
    </form><aside className="brief-aside"><div className="aside-note panel"><span className="eyebrow amber-text">THE METHOD</span><h2>Questions first.<br /><em>Evidence always.</em></h2><p>Every investigation is stored as a trail you can revisit, challenge, and share.</p><ol className="method-list"><li><span>01</span><div><h3>Decompose</h3><p>Turn the brief into answerable subquestions.</p></div></li><li><span>02</span><div><h3>Investigate</h3><p>Search, retrieve, and preserve the evidence.</p></div></li><li><span>03</span><div><h3>Verify</h3><p>Audit claims, conflicts, gaps, and citations.</p></div></li></ol></div><div className="aside-footer panel"><Layers size={18} /><span><strong>REAL DATA ONLY</strong><small>No mock sessions. No fabricated sources.</small></span></div></aside></section>
    {deleting && <Modal title="Delete uploaded document?" onClose={() => { if (!deletingId) setDeleting(null); }}><p>This permanently removes <strong>{deleting.title || 'this PDF'}</strong>. Documents selected for a brief or used by an active investigation cannot be deleted.</p>{documentError && <Notice>{documentError}</Notice>}<div className="modal-actions"><Button variant="ghost" disabled={!!deletingId} onClick={() => setDeleting(null)}>Keep document</Button><Button variant="danger" busy={!!deletingId} onClick={() => void removeDocument()}><Trash2 size={15} />Delete document</Button></div></Modal>}
  </div>;
}

function DocumentLibrary({ documents, selectedIds, loading, uploading, deletingId, fileRef, documentError, documentStatus, onRefresh, onToggle, onUpload, onDelete }: { documents: UploadedDocument[]; selectedIds: string[]; loading: boolean; uploading: boolean; deletingId: string; fileRef: RefObject<HTMLInputElement | null>; documentError: string; documentStatus: string; onRefresh: () => void; onToggle: (document: UploadedDocument) => void; onUpload: (files: FileList | null) => void; onDelete: (document: UploadedDocument) => void }) {
  return <fieldset className="document-fieldset"><legend>Uploaded PDF library <span className="small muted">Select documents for this brief or manage saved PDFs.</span></legend><div className="document-library panel" aria-busy={loading || uploading}><div className="panel-top"><span className="eyebrow"><Paperclip size={13} /> DOCUMENTS / {documents.length}</span><div><Button type="button" variant="ghost" busy={loading} onClick={onRefresh} aria-label="Refresh uploaded documents"><RefreshCw size={14} /><span className="hide-small">Refresh</span></Button><Button type="button" variant="ghost" busy={uploading} onClick={() => fileRef.current?.click()}><Paperclip size={14} />Upload PDF</Button><input ref={fileRef} type="file" accept="application/pdf" multiple hidden onChange={e => onUpload(e.target.files)} /></div></div><div className="panel-content">{documentError && <Notice>{documentError}</Notice>}{documentStatus && <Notice kind="success">{documentStatus}</Notice>}{loading ? <p role="status" className="muted small">Loading your saved PDFs…</p> : !documents.length ? <p className="muted small">No uploaded PDFs yet. Add one when the brief needs private evidence.</p> : <div className="document-list" role="list">{documents.map(document => { const selected = selectedIds.includes(document.id); const active = documentHasActiveResearch(document); const unavailable = active || document.deletable === false; return <div className={`document-row ${selected ? 'selected' : ''}`} role="listitem" key={document.id}><label className="document-select"><input type="checkbox" checked={selected} onChange={() => onToggle(document)} /><span><strong>{document.title || 'Untitled PDF'}</strong><small>{document.extraction_status || 'status not reported'}{document.text_chars ? ` · ${document.text_chars.toLocaleString()} extracted characters` : ''}</small></span></label><div className="document-actions">{selected && <Badge tone="green">In this brief</Badge>}{active && <span className="small amber-text" role="status">In use by active research</span>}{!active && document.deletable === false && <span className="small muted" role="status">Deletion unavailable</span>}<Button type="button" variant="ghost" aria-label={`Delete ${document.title || 'uploaded document'}`} disabled={selected || unavailable || !!deletingId} onClick={() => onDelete(document)}><Trash2 size={14} /></Button></div></div>; })}</div>}</div></div></fieldset>;
}
