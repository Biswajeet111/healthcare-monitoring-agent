import { useCallback, useEffect, useState } from 'react';
import { LogOut, RefreshCw, ShieldCheck, UserRound } from 'lucide-react';
import { API_BASE, DEMO, errorMessage, fmtDateTime, ragStatus, type RagStatus, type UserProfile } from '../api';
import { Alert, Badge, Spinner } from '../components/ui';

export default function Settings({ user, onSignOut }: { user: UserProfile | null; onSignOut: () => void }) {
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const loadStatus = useCallback(async () => {
    if (!user) return;
    setLoading(true); setErr('');
    try { setStatus(await ragStatus()); }
    catch (e) { setErr(errorMessage(e)); }
    finally { setLoading(false); }
  }, [user]);
  useEffect(() => { void loadStatus(); }, [loadStatus]);

  return <div className="settings-grid">
    <div className="panel settings-card">
      <div className="panel-heading"><div><h3>Account profile</h3><p>Authenticated HealthGuard AI user</p></div><span className="panel-icon"><UserRound size={20} /></span></div>
      {user ? <>
        <div className="settings-row"><span>User ID</span><b>#{user.id}</b></div>
        <div className="settings-row"><span>Full name</span><b>{user.full_name}</b></div>
        <div className="settings-row"><span>Email</span><b>{user.email ?? '—'}</b></div>
        <div className="settings-row"><span>Member since</span><b>{fmtDateTime(user.created_at)}</b></div>
      </> : <p>Running in demonstration mode without an authenticated user profile.</p>}
      {!DEMO && <div className="row-actions" style={{ marginTop: 16 }}>
        <button type="button" className="btn btn-danger" onClick={onSignOut}><LogOut size={15} /> Sign out</button>
      </div>}
    </div>

    <div className="panel settings-card">
      <div className="panel-heading"><div><h3>Connection & AI runtime</h3><p>Backend API and local RAG pipeline health</p></div>
        {user && <button type="button" className="icon-btn" onClick={() => void loadStatus()} aria-label="Refresh RAG status"><RefreshCw size={16} /></button>}
      </div>
      <div className="settings-row"><span>Environment</span><b>{DEMO ? 'Demonstration' : 'Live API'}</b></div>
      <div className="settings-row"><span>API base URL</span><code>{API_BASE}</code></div>
      {loading && <Spinner />}
      {err && <Alert>{err}</Alert>}
      {status && <>
        <div className="settings-row"><span>RAG Q&A readiness</span><Badge value={status.ready_for_qa ? 'ready' : 'unavailable'} tone={status.ready_for_qa ? 'ok' : 'warn'} /></div>
        <div className="settings-row"><span>Ollama LLM service</span><Badge value={status.ollama_available ? 'available' : 'offline'} tone={status.ollama_available ? 'ok' : 'danger'} /></div>
        <div className="settings-row"><span>Embedding model</span><Badge value={status.embedding_model_available ? 'loaded' : 'unavailable'} tone={status.embedding_model_available ? 'ok' : 'danger'} /></div>
        <div className="settings-row"><span>Detected Ollama models</span><b>{status.available_models.length ? status.available_models.join(', ') : 'None'}</b></div>
      </>}
    </div>

    <div className="panel settings-card span-all">
      <h3>Privacy, security & clinical disclaimer</h3>
      <p>HealthGuard AI is an educational and personal health monitoring tool. It is not a medical device and never provides clinical diagnoses, treatment recommendations, or emergency dispatch services. Always consult a qualified healthcare professional before making medical decisions.</p>
      <div className="info-line"><ShieldCheck size={17} /> Session tokens are stored in browser <code>sessionStorage</code> and cleared on sign-out or tab close</div>
      <div className="info-line"><ShieldCheck size={17} /> Local LLM inference via Ollama keeps private health questions on your machine</div>
      <div className="info-line"><ShieldCheck size={17} /> Experimental ML estimates and rule-based findings are non-diagnostic</div>
    </div>
  </div>;
}

