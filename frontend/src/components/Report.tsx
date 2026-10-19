import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowRight, BookOpen, Download, FileCheck2, List, ShieldAlert } from 'lucide-react';
import type { ResearchState } from '../types';
import { reportToc, remarkResearch } from '../lib/report';
import { safeUrl, text } from '../lib/model';
import { Badge, Button, CopyButton, Empty, Notice } from './ui';

export function Markdown({ children, onSource }: { children: string; onSource: (id: string) => void }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm, remarkResearch]} skipHtml components={{
    a: ({ href, children }) => {
      if (href?.startsWith('#evidence-')) return <button className="citation" onClick={() => onSource(href.slice(10))} aria-label={`Inspect source ${href.slice(10)}`}>{children}</button>;
      const url = safeUrl(href); return url ? <a href={url} target="_blank" rel="noreferrer noopener">{children}</a> : <span>{children}</span>;
    },
    img: ({ alt }) => <span className="muted small">[External image: {alt || 'not loaded'}]</span>,
  }}>{children}</ReactMarkdown>;
}

export function ReportView({ state, onSource, onClaim, onExport, exporting }: { state: ResearchState; onSource: (id: string) => void; onClaim: (id: string) => void; onExport: (format: 'markdown' | 'pdf') => void; exporting: string }) {
  const report = state.report || {}; const sections = Array.isArray(report.sections) ? report.sections : [];
  const markdown = typeof report.markdown === 'string' && report.markdown ? report.markdown : sections.map(section => `## ${section.title || 'Untitled section'}\n\n${section.content || ''}`).join('\n\n');
  const toc = useMemo(() => reportToc(markdown), [markdown]); const audit = report.citation_audit; const warnings = Array.isArray(audit?.warnings) ? audit.warnings : [];
  if (!markdown) return <Empty icon={<BookOpen size={26} />} title="The report will take shape here">A report appears when the backend has synthesized the investigation. Meanwhile, inspect the live plan, sources, and claims.</Empty>;
  return <div className="report-layout"><aside className="report-toc"><span className="eyebrow"><List size={13} /> ON THIS PAGE</span><nav aria-label="Report table of contents">{toc.length ? toc.map(item => <a key={item.id} href={`#${item.id}`} className={item.depth > 2 ? 'nested' : ''}>{item.title}</a>) : <a href="#report-content">Report overview</a>}</nav><div className="toc-note"><FileCheck2 size={18} /><p>Click a <span className="lime-text">[source]</span> to inspect its evidence. Select a claim below to see support and contradictions.</p></div></aside><article className="report-article" id="report-content"><div className="report-title-row"><span className="eyebrow lime-text">RESEARCH OUTPUT / REPORT</span><div className="report-export"><CopyButton value={markdown} label="Copy Markdown" /><Button variant="ghost" busy={exporting === 'markdown'} disabled={!!exporting} onClick={() => onExport('markdown')}><Download size={14} />.md</Button><Button variant="ghost" busy={exporting === 'pdf'} disabled={!!exporting} onClick={() => onExport('pdf')}><Download size={14} />PDF</Button></div></div><h1>{typeof report.title === 'string' ? report.title : state.question || 'Research report'}</h1><div className="report-audit"><Badge tone={audit?.passed ? 'green' : 'amber'}>{audit?.passed ? 'Citation audit passed' : audit ? 'Citation audit needs review' : 'Citation audit not reported'}</Badge><span className="small muted">{state.sources.length} sources · {state.claims.length} assessed claims</span></div>{warnings.length ? <Notice kind="info"><ShieldAlert size={14} />{warnings.join(' · ')}</Notice> : null}<div className="prose prose-invert report-prose max-w-none"><Markdown onSource={onSource}>{markdown}</Markdown></div><section className="claim-register"><span className="eyebrow">AUDIT THE CONCLUSIONS</span><h2>Claim register</h2><p className="muted small">Inspect the exact passages supporting or challenging a conclusion.</p>{state.claims.length ? <div className="claims-list">{state.claims.map(claim => { const status = text(claim.status) || 'UNVERIFIABLE'; return <button className="claim-card panel" key={claim.id} onClick={() => onClaim(claim.id)}><div><span className="mono">{text(claim.id)}</span><Badge>{status.replaceAll('_', ' ')}</Badge></div><h3>{text(claim.text)}</h3><span className="text-link">Inspect evidence <ArrowRight size={12} /></span></button>; })}</div> : <Empty title="No claims have been stored">The verifier has not recorded claims for this report yet.</Empty>}</section></article></div>;
}
