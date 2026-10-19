import { useEffect, useState } from 'react';
import { ArrowRight, Clock3, FolderOpen, Search, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import { formatDate } from '../lib/model';
import type { Session } from '../types';
import { Badge, Button, Empty, Modal, Notice, Status } from './ui';

export function History({ open, create }: { open: (id: string) => void; create: () => void }) {
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('newest');
  const [items, setItems] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [deleting, setDeleting] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      void api.sessions(search, sort, controller.signal)
        .then(data => { if (!controller.signal.aborted) { setItems(data); setError(''); } })
        .catch(e => { if (!controller.signal.aborted) setError((e as Error).message); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [search, sort, revision]);

  async function remove() {
    if (!deleting) return;
    setBusy(true);
    setDeleteError('');
    try {
      await api.remove(deleting.id);
      setItems(old => old.filter(item => item.id !== deleting.id));
      setDeleting(null);
    } catch (e) {
      setDeleteError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="page-container">
    <header className="page-heading"><div><span className="eyebrow">PERSISTED INVESTIGATIONS</span><h1>Research archive<span className="lime-text">.</span></h1><p>Pick up a question. Follow its evidence again.</p></div><Button variant="primary" onClick={create}>New research <ArrowRight size={16} /></Button></header>
    <div className="toolbar panel"><label className="search-input"><Search size={17} /><input aria-label="Search research history" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search your investigations…" /></label><label className="sort-label">Sort<select value={sort} onChange={e => setSort(e.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="updated">Recently updated</option></select></label><Button variant="ghost" onClick={() => setRevision(v => v + 1)} busy={loading}>Refresh</Button></div>
    {error && <Notice>{error}</Notice>}
    {loading ? <div className="loading-state" role="status">Loading saved investigations…</div> : !items.length ? <Empty icon={<FolderOpen size={28} />} title={search ? 'No matching investigations' : 'Your archive starts here'} action={!search && <Button onClick={create}>Start a research brief <ArrowRight size={15} /></Button>}>{search ? 'Try a different search term.' : 'Research sessions are saved by the backend. Your first investigation will appear here.'}</Empty> : <div className="history-list">{items.map((item, index) => <article key={item.id} className="history-card panel"><span className="history-index mono">{String(index + 1).padStart(2, '0')}</span><button className="history-main" onClick={() => open(item.id)}><div><Status value={item.status} /><span className="mono small muted">{item.id.slice(0, 8)}</span></div><h2>{item.question || 'Untitled investigation'}</h2><div className="history-meta"><span><Clock3 size={13} />{formatDate(item.created_at)}</span>{item.state.request?.depth && <Badge>{item.state.request.depth}</Badge>}{item.summary?.source_count ? <span>{item.summary.source_count} source{item.summary.source_count === 1 ? '' : 's'}</span> : null}{item.summary?.claim_count ? <span>{item.summary.claim_count} assessed claim{item.summary.claim_count === 1 ? '' : 's'}</span> : null}</div></button><Button variant="ghost" aria-label={`Delete ${item.question || 'investigation'}`} onClick={() => { setDeleteError(''); setDeleting(item); }}><Trash2 size={15} /></Button></article>)}</div>}
    {deleting && <Modal title="Delete investigation?" onClose={() => { if (!busy) setDeleting(null); }}><p>This permanently removes the saved session, events, report, and evidence relationships. Uploaded PDFs are kept separately.</p>{deleteError && <Notice>{deleteError}</Notice>}<div className="modal-actions"><Button variant="ghost" disabled={busy} onClick={() => setDeleting(null)}>Keep it</Button><Button variant="danger" busy={busy} onClick={() => void remove()}>Delete investigation</Button></div></Modal>}
  </div>;
}
