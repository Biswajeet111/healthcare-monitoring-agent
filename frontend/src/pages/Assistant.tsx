import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, ExternalLink, RefreshCw, Send, ShieldCheck, Trash2 } from 'lucide-react';
import {
  askAssistant, askDemoAssistant, demoAssistantStatus, errorMessage, listDocuments, ragStatus,
  type ChatMessage, type DemoAssistantStatus, type MedicalDocument, type RagStatus, type UserProfile,
} from '../api';

const LIVE_GREETING: ChatMessage = {
  role: 'assistant',
  text: 'Hello! I can help explain general health concepts using clinical reference material and your indexed documents. I cannot diagnose conditions or recommend treatment changes.',
};
const DEMO_GREETING: ChatMessage = {
  role: 'assistant',
  text: 'Hello! In this Vercel educational demo, I answer general health questions using a secure server-side Groq model. Responses here use general educational knowledge and are NOT RAG-grounded against clinical PDFs or personal records. I cannot diagnose conditions or prescribe treatments.',
  ragGrounded: false,
};
const EXAMPLES = ['What is HbA1c?', 'What is blood pressure?', 'How does regular physical activity affect health?'];

export default function Assistant({ user, demo }: { user: UserProfile | null; demo: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>([demo ? DEMO_GREETING : LIVE_GREETING]);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [demoStatus, setDemoStatus] = useState<DemoAssistantStatus | null>(null);
  const [statusErr, setStatusErr] = useState('');
  const [docs, setDocs] = useState<MedicalDocument[]>([]);
  const [useDocs, setUseDocs] = useState(true);
  const [docId, setDocId] = useState<number | ''>('');
  const endRef = useRef<HTMLDivElement>(null);

  const checkStatus = useCallback(async () => {
    setStatusErr('');
    if (demo) {
      try { setDemoStatus(await demoAssistantStatus()); }
      catch (e) { setDemoStatus(null); setStatusErr(errorMessage(e)); }
      return;
    }
    if (!user) return;
    try { setStatus(await ragStatus()); } catch (e) { setStatus(null); setStatusErr(errorMessage(e)); }
  }, [user, demo]);

  useEffect(() => {
    void checkStatus();
    if (!demo && user) listDocuments().then(r => setDocs(r.documents.filter(d => d.index_status === 'indexed'))).catch(() => setDocs([]));
  }, [checkStatus, user, demo]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages, sending]);

  const maxQuestionLen = demo ? 600 : 2000;

  async function send(text?: string) {
    const q = (text ?? question).trim();
    if (!q || sending) return;
    if (q.length < 3) { setMessages(v => [...v, { role: 'assistant', text: 'Please ask a slightly longer question (at least 3 characters).', error: true }]); return; }
    setQuestion('');
    setMessages(v => [...v, { role: 'user', text: q }]);
    setSending(true);
    try {
      if (demo) {
        const r = await askDemoAssistant(q.slice(0, maxQuestionLen));
        setMessages(v => [...v, r.answer
          ? { role: 'assistant', text: r.answer, sources: [], limitations: r.limitations, model: r.model_used, ragGrounded: false }
          : { role: 'assistant', text: r.error || 'The assistant returned no answer.', error: true }]);
      } else if (!user) {
        setMessages(v => [...v, { role: 'assistant', text: 'Please sign in against the live backend to use the clinical RAG assistant.', error: true }]);
      } else {
        const r = await askAssistant(q.slice(0, maxQuestionLen), { include_user_documents: useDocs, document_id: useDocs && docId !== '' ? docId : null });
        setMessages(v => [...v, r.answer
          ? { role: 'assistant', text: r.answer, sources: r.sources, limitations: r.limitations, model: r.model_used, ragGrounded: true }
          : { role: 'assistant', text: r.error || 'The assistant returned no answer.', error: true }]);
      }
    } catch (e) {
      setMessages(v => [...v, { role: 'assistant', text: `Unable to get an answer: ${errorMessage(e, 'Unknown error')}`, error: true }]);
      void checkStatus();
    } finally { setSending(false); }
  }

  const isReady = demo ? Boolean(demoStatus?.available) : Boolean(status?.ready_for_qa);
  const statusLabel = demo
    ? (demoStatus ? (demoStatus.available ? 'Groq Ready (General)' : 'Unavailable') : statusErr ? 'Status unknown' : 'Checking…')
    : (status ? (status.ready_for_qa ? 'Ready' : 'Unavailable') : statusErr ? 'Status unknown' : 'Checking…');
  const statusClass = isReady ? 'ok' : (demo ? (demoStatus ? 'down' : '') : (status ? 'down' : ''));

  return <div className="chat-layout">
    <div className="panel chat-panel">
      <div className="chat-head"><div className="chat-icon"><Bot size={22} /></div>
        <div>
          <h3>HealthGuard Assistant</h3>
          <p>{demo ? 'Educational Groq AI (General Knowledge · Not RAG-Grounded) · Not a clinician' : 'Educational medical information · Not a clinician'}</p>
        </div>
        <span className={`assistant-status ${statusClass}`} title={demo ? demoStatus?.limitation : status?.limitation}>{statusLabel}</span>
        <button className="icon-btn" onClick={() => setMessages([demo ? DEMO_GREETING : LIVE_GREETING])} aria-label="Clear conversation" title="Clear conversation"><Trash2 size={17} /></button></div>
      {demo && demoStatus && !demoStatus.available && (
        <div className="chat-warning">The server-side Groq API key (<code>GROQ_API_KEY</code>) is not configured on this Vercel deployment.</div>
      )}
      {!demo && status && !status.ready_for_qa && (
        <div className="chat-warning">{!(status.llm_available ?? status.ollama_available) ? (status.llm_provider === 'groq' ? 'The cloud language model (Groq) is not configured or unreachable on the backend.' : 'The local language model (Ollama) is not reachable. Start Ollama to enable answers.') : 'The embedding model is not available on the backend.'}</div>
      )}
      <div className="chat-messages" aria-live="polite">
        {messages.map((m, i) => <div className={`bubble-row ${m.role}`} key={i}><div className={`bubble ${m.error ? 'bubble-error' : ''}`}>{m.text}
          {m.sources?.length ? <div className="sources"><b>Retrieved references</b>{m.sources.map(s => <small key={s.reference_number}>[{s.reference_number}] {s.document_title}{s.source_organization ? ` — ${s.source_organization}` : ''}{s.source_url && /^https?:\/\//.test(s.source_url) ? <> · <a href={s.source_url} target="_blank" rel="noreferrer noopener">source <ExternalLink size={10} /></a></> : null}</small>)}</div> : null}
          {m.limitations?.length ? <div className="sources"><b>Limitations</b>{m.limitations.map((l, j) => <small key={j}>{l}</small>)}</div> : null}
          {m.model ? <div className="model-tag">Generated by {m.model}{m.ragGrounded === false ? ' · General educational AI (not RAG-grounded)' : ''}</div> : null}
        </div></div>)}
        {sending && <div className="typing">{demo ? 'Preparing educational response via Groq…' : 'Retrieving references and preparing response…'}</div>}
        <div ref={endRef} />
      </div>
      <form className="chat-input" onSubmit={e => { e.preventDefault(); void send(); }}><input aria-label="Ask a health question" maxLength={maxQuestionLen} value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask a general health question..." /><button disabled={sending || !question.trim()} aria-label="Send"><Send size={19} /></button></form>
    </div>
    <div className="panel assistant-sidebar"><div className="panel-icon"><ShieldCheck size={22} /></div><h3>Designed with care</h3><p>Responses may be incomplete or inaccurate. Always consult a qualified healthcare professional for medical decisions.</p>
      {demo && (
        <div className="assistant-tip">
          <b>Demo AI runtime</b>
          <span>Powered by a secure Vercel serverless endpoint (<code>/api/assistant</code>) calling Groq.</span>
          <span>General educational answers only — ChromaDB clinical RAG and private PDF retrieval require the full backend.</span>
          {demoStatus && <span>Model: <b>{demoStatus.active_model}</b></span>}
          <button type="button" className="btn btn-ghost small" onClick={() => void checkStatus()}><RefreshCw size={13} /> Recheck AI status</button>
        </div>
      )}
      {!demo && user && <div className="assistant-tip"><b>Knowledge sources</b>
        <label className="check-line"><input type="checkbox" checked={useDocs} onChange={e => setUseDocs(e.target.checked)} /> Include my indexed documents</label>
        {useDocs && <select aria-label="Limit to a document" value={docId} onChange={e => setDocId(e.target.value ? Number(e.target.value) : '')}><option value="">All my documents ({docs.length})</option>{docs.map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}</select>}
        <button type="button" className="btn btn-ghost small" onClick={() => void checkStatus()}><RefreshCw size={13} /> Recheck AI status</button>
        {status && <span>Models: {status.available_models.length ? status.available_models.join(', ') : 'none detected'}</span>}
      </div>}
      <div className="assistant-tip"><b>What can I ask?</b>{EXAMPLES.map(x => <button type="button" key={x} className="example-q" disabled={sending} onClick={() => void send(x)}>“{x}”</button>)}</div>
      <div className="emergency-note"><b>Medical emergency?</b><p>Call local emergency services. Do not wait for an AI response.</p></div></div>
  </div>;
}
