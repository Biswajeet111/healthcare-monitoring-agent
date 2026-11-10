import { useState, type FormEvent } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { errorMessage, login, register, type UserProfile } from '../api';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function AuthScreen({ onAuthenticated }: { onAuthenticated: (u: UserProfile) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [busy, setBusy] = useState(false);

  function validate(): string | null {
    if (!EMAIL_RE.test(email.trim())) return 'Enter a valid email address.';
    if (mode === 'register') {
      if (fullName.trim().length < 2) return 'Full name must be at least 2 characters.';
      if (password.length < 8) return 'Password must be at least 8 characters.';
      if (password.length > 128) return 'Password must be at most 128 characters.';
      if (password !== confirm) return 'Passwords do not match.';
    } else if (!password) return 'Enter your password.';
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(''); setInfo('');
    const v = validate();
    if (v) { setError(v); return; }
    setBusy(true);
    try {
      if (mode === 'register') {
        await register(fullName, email, password);
        setInfo('Account created. Signing you in…');
      }
      const user = await login(email, password);
      setPassword(''); setConfirm('');
      onAuthenticated(user);
    } catch (err) {
      setError(errorMessage(err, mode === 'login' ? 'Sign in failed' : 'Registration failed'));
    } finally { setBusy(false); }
  }

  const switchMode = () => { setMode(m => (m === 'login' ? 'register' : 'login')); setError(''); setInfo(''); setPassword(''); setConfirm(''); };

  return <div className="login-screen"><form className="login-card" onSubmit={submit} noValidate>
    <img src="/healthguard-logo.png" alt="HealthGuard AI" width="90" />
    <h1>HealthGuard AI</h1>
    <p>{mode === 'login' ? 'Sign in to view your private health records.' : 'Create an account to start tracking your health.'}</p>
    {mode === 'register' && <label>Full name<input required autoComplete="name" value={fullName} onChange={e => setFullName(e.target.value)} /></label>}
    <label>Email<input type="email" required autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} /></label>
    <label>Password<span className="pw-wrap"><input type={show ? 'text' : 'password'} required minLength={mode === 'register' ? 8 : undefined} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={e => setPassword(e.target.value)} /><button type="button" className="pw-toggle" onClick={() => setShow(s => !s)} aria-label={show ? 'Hide password' : 'Show password'}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button></span></label>
    {mode === 'register' && <label>Confirm password<input type={show ? 'text' : 'password'} required autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label>}
    {error && <p role="alert" className="login-error">{error}</p>}
    {info && <p role="status" className="login-info">{info}</p>}
    <button disabled={busy}>{busy ? (mode === 'login' ? 'Signing in…' : 'Creating account…') : mode === 'login' ? 'Sign in' : 'Create account'}</button>
    <button type="button" className="link-btn" onClick={switchMode}>{mode === 'login' ? "Don't have an account? Create one" : 'Already registered? Sign in'}</button>
    <small>Educational software · Not medical advice</small>
  </form></div>;
}

