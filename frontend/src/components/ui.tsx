import { useEffect, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { AlertCircle, ArrowUpRight, Check, Copy, LoaderCircle, X } from 'lucide-react';
import { safeUrl } from '../lib/model';

export function Button({ children, busy, variant = 'default', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: 'default' | 'primary' | 'ghost' | 'danger'; children: ReactNode }) {
  const { disabled, type = 'button', ...rest } = props;
  return <button {...rest} type={type} className={`btn btn-${variant} ${className}`} disabled={busy || disabled}>{busy && <LoaderCircle size={15} className="animate-spin" />}{children}</button>;
}
export function Notice({ children, kind = 'error' }: { children: ReactNode; kind?: 'error' | 'info' | 'success' }) {
  return <div className={`notice notice-${kind}`} role={kind === 'error' ? 'alert' : 'status'}><AlertCircle size={16} /><div>{children}</div></div>;
}
export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state">{icon && <div className="empty-icon">{icon}</div>}<h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) { return <span className={`badge ${tone}`}>{children}</span>; }
export function Status({ value }: { value: string }) { return <Badge tone={['completed', 'SUPPORTED'].includes(value) ? 'green' : ['failed', 'CONTRADICTED'].includes(value) ? 'red' : ['running', 'queued', 'PARTIALLY_SUPPORTED'].includes(value) ? 'amber' : ''}><span className="status-dot" />{value.replaceAll('_', ' ').toLowerCase()}</Badge>; }
export function ExternalLink({ url, children }: { url?: string; children: ReactNode }) { const href = safeUrl(url); return href ? <a href={href} target="_blank" rel="noreferrer noopener" className="external-link">{children}<ArrowUpRight size={13} aria-hidden /></a> : <span className="muted">{children} · no public link</span>; }
export function Modal({ title, children, onClose, wide = false, drawer = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean; drawer?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; const previous = document.activeElement as HTMLElement | null; dialog?.showModal(); const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; return () => { dialog?.close(); document.body.style.overflow = overflow; previous?.focus(); }; }, []);
  return <dialog ref={ref} className={`modal ${wide ? 'wide' : ''} ${drawer ? 'drawer' : ''}`} aria-label={title} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}><div className="modal-inner"><header><h2>{title}</h2><Button variant="ghost" aria-label="Close dialog" onClick={onClose}><X size={19} /></Button></header><div className="modal-body">{children}</div></div></dialog>;
}
export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false); const [error, setError] = useState('');
  return <><Button variant="ghost" onClick={async () => { try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { setError('Clipboard unavailable. Select the text to copy it.'); } }}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Copied' : label}</Button>{error && <span role="status" className="small muted">{error}</span>}</>;
}
