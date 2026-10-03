'use client';

import { confirmSignUp, getCurrentUser, signIn, signOut, signUp } from 'aws-amplify/auth';
import { createContext, FormEvent, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { configureAmplify, isAwsConfigured } from './amplify-config';
import { api, ApiError } from './api';

type User = { userId: string; username: string };
export type Profile = { user: { displayName: string; accountType: 'recipient' | 'donor' }; memberships: Array<{ organizationId: string; role: string }> };
type AuthContextValue = {
  user: User | null;
  profile: Profile | null;
  loading: boolean;
  configured: boolean;
  openAuth: () => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const configured = isAwsConfigured();

  const refresh = useCallback(async () => {
    if (!configured) { setLoading(false); return; }
    try {
      const current = await getCurrentUser();
      setUser(current);
      try { setProfile(await api<Profile>('/me')); }
      catch (error) { if (error instanceof ApiError && error.status === 404) setSetupOpen(true); }
    } catch { setUser(null); setProfile(null); }
    finally { setLoading(false); }
  }, [configured]);

  useEffect(() => {
    configureAmplify();
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  const value = useMemo<AuthContextValue>(() => ({
    user, profile,
    loading,
    configured,
    openAuth: () => setOpen(true),
    logout: async () => { await signOut(); setUser(null); setProfile(null); },
  }), [user, profile, loading, configured]);

  return <AuthContext.Provider value={value}>
    {children}
    {open && <AuthDialog onClose={() => setOpen(false)} onAuthenticated={async () => { await refresh(); setOpen(false); }} />}
    {setupOpen && user && <ProfileSetup onComplete={result => { setProfile(result); setSetupOpen(false); }} />}
  </AuthContext.Provider>;
}

function ProfileSetup({ onComplete }: { onComplete: (profile: Profile) => void }) {
  const [displayName, setDisplayName] = useState('');
  const [accountType, setAccountType] = useState<'recipient' | 'donor'>('recipient');
  const [organizationName, setOrganizationName] = useState('');
  const [address, setAddress] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      let coordinates: { latitude?: number; longitude?: number } = {};
      if (accountType === 'donor' && navigator.geolocation) {
        coordinates = await new Promise(resolve => navigator.geolocation.getCurrentPosition(position => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }), () => resolve({}), { timeout: 5000 }));
      }
      onComplete(await api<Profile>('/me/bootstrap', { method: 'POST', body: JSON.stringify({ displayName, accountType, organizationName: accountType === 'donor' ? organizationName : undefined, address: accountType === 'donor' ? address : undefined, ...coordinates }) }));
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Profile setup failed.'); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop"><section className="modal-card auth-modal" role="dialog" aria-modal="true">
    <p className="eyebrow">One quick step</p><h2>How will you use Second Serving?</h2>
    <form className="auth-form" onSubmit={submit}>
      <label>Your name<input required value={displayName} onChange={event => setDisplayName(event.target.value)} /></label>
      <div className="account-type"><button type="button" className={accountType === 'recipient' ? 'active' : ''} onClick={() => setAccountType('recipient')}>Find food</button><button type="button" className={accountType === 'donor' ? 'active' : ''} onClick={() => setAccountType('donor')}>Share food</button></div>
      {accountType === 'donor' && <><label>Kitchen or organization<input required value={organizationName} onChange={event => setOrganizationName(event.target.value)} /></label><label>Pickup address<input required autoComplete="street-address" value={address} onChange={event => setAddress(event.target.value)} /></label><p className="setup-note">We’ll ask for location access once to estimate short pickup routes. The exact address stays hidden until food is reserved.</p></>}
      {error && <p className="auth-error" role="alert">{error}</p>}
      <button className="primary-action" disabled={busy}>{busy ? 'Saving…' : 'Continue'}</button>
    </form>
  </section></div>;
}

function AuthDialog({ onClose, onAuthenticated }: { onClose: () => void; onAuthenticated: () => Promise<void> }) {
  const [mode, setMode] = useState<'signin' | 'signup' | 'confirm'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      if (mode === 'signup') {
        const result = await signUp({ username: email, password, options: { userAttributes: { email } } });
        if (result.nextStep.signUpStep === 'DONE') await onAuthenticated();
        else setMode('confirm');
      } else if (mode === 'confirm') {
        await confirmSignUp({ username: email, confirmationCode: code });
        await signIn({ username: email, password });
        await onAuthenticated();
      } else {
        const result = await signIn({ username: email, password });
        if (result.isSignedIn) await onAuthenticated();
        else if (result.nextStep.signInStep === 'CONFIRM_SIGN_UP') setMode('confirm');
        else throw new Error('Another sign-in step is required. Please try again.');
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Authentication failed.'); }
    finally { setBusy(false); }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section className="modal-card auth-modal" role="dialog" aria-modal="true" onMouseDown={event => event.stopPropagation()}>
      <button className="close-button" onClick={onClose}>×</button>
      <p className="eyebrow">Second Serving account</p>
      <h2>{mode === 'signin' ? 'Welcome back.' : mode === 'signup' ? 'Join the network.' : 'Check your email.'}</h2>
      <p className="modal-lede">{mode === 'confirm' ? `Enter the verification code sent to ${email}.` : 'Reserve food or manage donations with a free account.'}</p>
      <form className="auth-form" onSubmit={submit}>
        {mode !== 'confirm' && <><label>Email<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label><label>Password<input type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} minLength={10} required value={password} onChange={event => setPassword(event.target.value)} /></label></>}
        {mode === 'confirm' && <label>Verification code<input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={event => setCode(event.target.value)} /></label>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="primary-action" disabled={busy}>{busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : mode === 'signup' ? 'Create account' : 'Verify & sign in'}</button>
      </form>
      {mode !== 'confirm' && <button className="sample-link" onClick={() => { setError(''); setMode(mode === 'signin' ? 'signup' : 'signin'); }}>{mode === 'signin' ? 'New here? Create an account' : 'Already have an account? Sign in'}</button>}
    </section>
  </div>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider.');
  return value;
}
