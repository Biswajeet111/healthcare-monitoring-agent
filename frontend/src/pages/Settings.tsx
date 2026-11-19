import { useCallback, useEffect, useState } from 'react';
import { LogOut, RefreshCw, ShieldCheck, UserRound } from 'lucide-react';
import {
  API_BASE, DEMO, DEMO_BANNER_TITLE, demoAssistantStatus, errorMessage, fmtDateTime, ragStatus,
  type DemoAssistantStatus, type RagStatus, type UserProfile,
} from '../api';
import { Alert, Badge, Spinner } from '../components/ui';

export default function Settings({ user, onSignOut }: { user: UserProfile | null; onSignOut: () => void }) {
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [demoStatus, setDemoStatus] = useState<DemoAssistantStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const loadStatus = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      if (DEMO) {
        setDemoStatus(await demoAssistantStatus());
      } else if (user) {
        setStatus(await ragStatus());
      }
    } catch (e) { setErr(errorMessage(e)); }
    finally { setLoading(false); }
  }, [user]);
  useEffect(() => { void loadStatus(); }, [loadStatus]);

  return <div className="settings-grid">
    <div className="panel settings-card">
      <div className="panel-heading"><div><h3>Account profile</h3><p>{DEMO ? DEMO_BANNER_TITLE : 'Authenticated HealthGuard AI user'}</p></div><span className="panel-icon"><UserRound size={20} /></span></div>
      {user ? <>
        <div className="settings-row"><span>User ID</span><b>#{user.id}</b></div>
        <div className="settings-row"><span>Full name</span><b>{user.full_name}</b></div>
        <div className="settings-row"><span>Email</span><b>{user.email ?? '—'}</b></div>
        <div className="settings-row"><span>Member since</span><b>{fmtDateTime(user.created_at)}</b></div>
      </> : <>
        <div className="settings-row"><span>Mode</span><Badge value="educational demo" tone="info" /></div>
        <div className="settings-row"><span>Visitor profile</span><b>Synthetic Demo Visitor (No account required)</b></div>
        <div className="settings-row"><span>Data source</span><b>Client-side synthetic health &amp; medication records</b></div>
      </>}
      {!DEMO && <div className="row-actions" style={{ marginTop: 16 }}>
        <button type="button" className="btn btn-danger" onClick={onSignOut}><LogOut size={15} /> Sign out</button>
      </div>}
    </div>

    <div className="panel settings-card">
      <div className="panel-heading"><div><h3>Connection &amp; AI runtime</h3><p>{DEMO ? 'Vercel serverless Groq assistant status' : 'Backend API and RAG pipeline health'}</p></div>
        {(DEMO || user) && <button type="button" className="icon-btn" onClick={() => void loadStatus()} aria-label="Refresh AI status"><RefreshCw size={16} /></button>}
      </div>
      <div className="settings-row"><span>Environment</span><b>{DEMO ? 'Vercel Lightweight Demo (Synthetic Data)' : 'Live Full-Stack API'}</b></div>
      <div className="settings-row"><span>Endpoint</span><code>{DEMO ? '/api/assistant (Vercel Serverless)' : (API_BASE || 'Not configured')}</code></div>
      {loading && <Spinner />}
      {err && <Alert>{err}</Alert>}
      {DEMO && demoStatus && <>
        <div className="settings-row"><span>Groq educational AI</span><Badge value={demoStatus.available ? 'available' : 'unavailable'} tone={demoStatus.available ? 'ok' : 'danger'} /></div>
        <div className="settings-row"><span>Active Groq model</span><b>{demoStatus.active_model}</b></div>
        <div className="settings-row"><span>Clinical RAG grounding</span><Badge value="not enabled in demo" tone="warn" /></div>
      </>}
      {!DEMO && status && <>
        <div className="settings-row"><span>RAG Q&amp;A readiness</span><Badge value={status.ready_for_qa ? 'ready' : 'unavailable'} tone={status.ready_for_qa ? 'ok' : 'warn'} /></div>
        <div className="settings-row"><span>LLM provider ({status.llm_provider === 'groq' ? 'Groq Cloud' : 'Ollama Local'})</span><Badge value={(status.llm_available ?? status.ollama_available) ? 'available' : 'offline'} tone={(status.llm_available ?? status.ollama_available) ? 'ok' : 'danger'} /></div>
        {status.active_model && <div className="settings-row"><span>Active LLM model</span><b>{status.active_model}</b></div>}
        <div className="settings-row"><span>Embedding model</span><Badge value={status.embedding_model_available ? 'loaded' : 'unavailable'} tone={status.embedding_model_available ? 'ok' : 'danger'} /></div>
        <div className="settings-row"><span>Available models</span><b>{status.available_models.length ? status.available_models.slice(0, 6).join(', ') : 'None'}</b></div>
      </>}
    </div>

    <div className="panel settings-card span-all">
      <h3>Privacy, security &amp; clinical disclaimer</h3>
      <p>HealthGuard AI is an educational and personal health monitoring tool. It is not a medical device and never provides clinical diagnoses, treatment recommendations, or emergency dispatch services. Always consult a qualified healthcare professional before making medical decisions.</p>
      {DEMO ? <>
        <div className="info-line"><ShieldCheck size={17} /> All dashboard metrics, trend charts, and medication entries in this Vercel demo are synthetic</div>
        <div className="info-line"><ShieldCheck size={17} /> AI Assistant calls <code>/api/assistant</code> on the server; <code>GROQ_API_KEY</code> is never bundled into frontend code</div>
        <div className="info-line"><ShieldCheck size={17} /> Full RAG document retrieval, PDF uploads, dynamic multi-agent orchestration, and experimental ML screening run in the full backend</div>
      </> : <>
        <div className="info-line"><ShieldCheck size={17} /> Session tokens are stored in browser <code>sessionStorage</code> and cleared on sign-out or tab close</div>
        <div className="info-line"><ShieldCheck size={17} /> Configurable LLM runtime supports local Ollama or cloud Groq inference with strict non-diagnostic safety guardrails</div>
        <div className="info-line"><ShieldCheck size={17} /> Experimental ML estimates and rule-based findings are non-diagnostic</div>
      </>}
    </div>
  </div>;
}
