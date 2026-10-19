import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { createClient } from '@supabase/supabase-js';
import type { SupabaseClient, Session as AuthSession } from '@supabase/supabase-js';
import { ArrowRight, KeyRound, LoaderCircle, Mail } from 'lucide-react';
import { api, setAuthInvalidatedHandler, setTokenProvider } from './lib/api';
import { text } from './lib/model';
import type { Settings } from './types';
import { Button, Notice } from './components/ui';

interface AuthValue { settings: Settings | null; settingsError: string; reloadSettings: () => Promise<void>; client: SupabaseClient | null; auth: AuthSession | null }
interface Bootstrap { auth_mode?: string; supabase_url?: string; supabase_anon_key?: string }
const AuthContext = createContext<AuthValue>(null!);
export const useAuth = () => useContext(AuthContext);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings | null>(null); const [settingsError, setSettingsError] = useState('');
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null); const [bootstrapError, setBootstrapError] = useState('');
  const [loading, setLoading] = useState(true); const [authLoading, setAuthLoading] = useState(true); const [auth, setAuth] = useState<AuthSession | null>(null);
  const reloadSettings = useCallback(async () => { try { setSettings(await api.settings()); setSettingsError(''); } catch (e) { setSettingsError((e as Error).message); } finally { setLoading(false); } }, []);
  useEffect(() => { let mounted = true; void api.bootstrap().then(value => { if (mounted) setBootstrap(value); }).catch(e => { if (mounted) { setBootstrapError((e as Error).message); setLoading(false); } }); return () => { mounted = false; }; }, []);
  const mode = text(import.meta.env.VITE_AUTH_MODE || bootstrap?.auth_mode);
  const url = text(import.meta.env.VITE_SUPABASE_URL || bootstrap?.supabase_url);
  const key = text(import.meta.env.VITE_SUPABASE_ANON_KEY || bootstrap?.supabase_anon_key);
  const client = useMemo(() => { if (!url || !key) return null; try { return createClient(url, key); } catch { return null; } }, [url, key]);
  useEffect(() => {
    if (!client) { setAuthLoading(false); setTokenProvider(async () => null); return; }
    let mounted = true;
    setTokenProvider(async () => { const { data } = await client.auth.getSession(); return data.session?.access_token ?? null; });
    void client.auth.getSession().then(({ data }) => { if (mounted) { setAuth(data.session); setAuthLoading(false); } });
    const { data: listener } = client.auth.onAuthStateChange((_event, session) => { setAuth(session); setAuthLoading(false); });
    return () => { mounted = false; listener.subscription.unsubscribe(); setTokenProvider(async () => null); };
  }, [client]);
  useEffect(() => {
    setAuthInvalidatedHandler(() => { setSettings(null); setSettingsError('Your session expired. Sign in again to continue.'); if (client) void client.auth.signOut(); });
    return () => setAuthInvalidatedHandler(() => {});
  }, [client]);
  useEffect(() => {
    if (!bootstrap) return;
    if (mode === 'supabase') {
      if (authLoading) return;
      if (!auth) { setSettings(null); setSettingsError(''); setLoading(false); return; }
      void reloadSettings();
      return;
    }
    void reloadSettings();
  }, [bootstrap, mode, auth, authLoading, reloadSettings]);
  const value = { settings, settingsError, reloadSettings, client, auth };
  if ((!bootstrap && !bootstrapError) || loading || (client && authLoading)) return <div className="boot"><span className="brand-mark" /><LoaderCircle className="animate-spin" size={19} /><p>Connecting to the research lab…</p></div>;
  if (bootstrapError && !bootstrap) return <div className="boot"><Notice>{bootstrapError}</Notice></div>;
  return <AuthContext.Provider value={value}>{mode === 'supabase' && !auth ? <Login client={client} /> : children}</AuthContext.Provider>;
}
function Login({ client }: { client: SupabaseClient | null }) {
  const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [message, setMessage] = useState('');
  async function login(magic: boolean) {
    if (!client) return; setBusy(true); setError(''); setMessage('');
    try { const result = magic ? await client.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } }) : await client.auth.signInWithPassword({ email, password });
      if (result.error) throw result.error; if (magic) setMessage('Sign-in link sent. Open the email on this device to continue.');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <main className="login grid-bg"><div className="login-art"><span className="eyebrow">AGENTSWARM / RESEARCH LAB</span><h1>Good questions.<br /><em>Verifiable answers.</em></h1><p>Your evidence, sources, and investigations in one private workspace.</p><div className="login-cross">+</div></div><form className="login-form panel" onSubmit={e => { e.preventDefault(); void login(false); }}><span className="eyebrow lime-text"><KeyRound size={14} /> AUTHENTICATED ACCESS</span><h2>Enter the lab.</h2><p className="muted">Sign in with your Supabase account.</p>{!client && <Notice>Supabase authentication is enabled. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env.local, then restart Vite. Use the public project key.</Notice>}{error && <Notice>{error}</Notice>}{message && <Notice kind="success">{message}</Notice>}<label>Email<input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="you@organization.com" /></label><label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required minLength={6} /></label><Button variant="primary" type="submit" busy={busy} disabled={!client}>Sign in <ArrowRight size={16} /></Button><Button type="button" busy={busy} disabled={!client || !email.includes('@')} onClick={() => void login(true)}><Mail size={16} />Email a sign-in link</Button><span className="small muted">Session tokens authenticate research, streaming, and downloads.</span></form></main>;
}
