import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Activity, Bell, BrainCircuit, ChevronDown, ChevronUp, ClipboardList, Database, FileText, FlaskConical, History, Pill, Play, RefreshCw, Send, ShieldCheck, Sparkles } from 'lucide-react';
import {
  DEMO, errorMessage, fmtDateTime, getHealthSummary, getOrchestrationAlerts, getOrchestrationHistory, humanize, predictDiabetesV3, runAssessment, runDynamicWorkflow, runMedicationCheck,
  type AuditEntry, type DiabetesFeatures, type DiabetesPredictionV3, type ExecutionStep, type HealthSummary, type OrchestrationAlerts, type UserProfile,
} from '../api';
import { Alert, Badge, Empty, Spinner } from '../components/ui';

const AGENTS = [
  { key: 'knowledge', match: /^MedicalKnowledgeAgent$/i, name: 'Medical Knowledge', desc: 'Evidence retrieval and educational summaries', icon: Database, tone: 'purple' },
  { key: 'monitoring', match: /^MonitoringAgent$/i, name: 'Monitoring', desc: 'Health metric interpretation and trends', icon: Activity, tone: 'blue' },
  { key: 'medication', match: /^MedicationAgent$/i, name: 'Medication', desc: 'Medication information and adherence context', icon: ClipboardList, tone: 'pink' },
  { key: 'risk', match: /^RiskAssessmentAgent$/i, name: 'Risk Assessment', desc: 'Structured informational & experimental ML screening', icon: ShieldCheck, tone: 'green' },
  { key: 'notification', match: /^NotificationAgent$/i, name: 'Notification', desc: 'Health monitoring notification workflows', icon: Bell, tone: 'purple' },
];
const METRICS = [['blood_glucose', 'Blood glucose'], ['heart_rate', 'Heart rate'], ['blood_pressure_systolic', 'Systolic BP'], ['blood_pressure_diastolic', 'Diastolic BP'], ['weight', 'Weight'], ['steps', 'Steps'], ['sleep_duration', 'Sleep']] as const;
type Action = 'dynamic' | 'assess' | 'summary' | 'medication';

const DYNAMIC_PRESETS: { label: string; query: string }[] = [
  {
    label: '1. Uploaded Report Q&A',
    query: 'What does my uploaded clinical laboratory report say about my fasting glucose and HbA1c?',
  },
  {
    label: '2. Adaptive Glucose Assessment',
    query: 'Assess my recent blood glucose measurements and explain if there is any statistical deviation.',
  },
  {
    label: '3. Medication Adherence Check',
    query: 'How is my medication adherence and do I have any overdue or missed doses?',
  },
  {
    label: '4. Comprehensive Health Summary',
    query: 'Give me a comprehensive personalized health summary across my measurements, medications, and alerts.',
  },
  {
    label: '5. Insufficient Data (Sleep)',
    query: 'Assess my recent sleep duration measurements over the past week.',
  },
];

const DEFAULT_ML_FEATURES: DiabetesFeatures = {
  Pregnancies: 0,
  Glucose: 158,
  BloodPressure: 85,
  SkinThickness: 26,
  Insulin: 115,
  BMI: 28.4,
  DiabetesPedigreeFunction: 0.52,
  Age: 48,
};

function formatIntermediateOutput(out: Record<string, unknown> | null | undefined): string {
  if (!out) return '';
  return Object.entries(out)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ');
}

export default function Agents({ user }: { user: UserProfile | null }) {
  const [dynamicQuery, setDynamicQuery] = useState<string>(DYNAMIC_PRESETS[1].query);
  const [maxSteps, setMaxSteps] = useState<number>(6);
  const [allowNotifDelivery, setAllowNotifDelivery] = useState<boolean>(false);

  const [metric, setMetric] = useState<string>('blood_glucose');
  const [includeKnowledge, setIncludeKnowledge] = useState(true);
  const [experimentalMl, setExperimentalMl] = useState(true);
  const [features, setFeatures] = useState<DiabetesFeatures>(DEFAULT_ML_FEATURES);
  const [running, setRunning] = useState<Action | null>(null);
  const [result, setResult] = useState<HealthSummary | null>(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<AuditEntry[] | null>(null);
  const [expandedAuditId, setExpandedAuditId] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<OrchestrationAlerts | null>(null);

  // Direct standalone Experimental ML Screening (/ml/diabetes/predict-v3)
  const [mlBusy, setMlBusy] = useState(false);
  const [mlResult, setMlResult] = useState<DiabetesPredictionV3 | null>(null);
  const [mlError, setMlError] = useState('');

  const loadSide = useCallback(async () => {
    if (!user) return;
    const [h, a] = await Promise.allSettled([getOrchestrationHistory(15), getOrchestrationAlerts()]);
    setHistory(h.status === 'fulfilled' ? h.value : []);
    if (a.status === 'fulfilled') setAlerts(a.value);
  }, [user]);
  useEffect(() => { void loadSide(); }, [loadSide]);

  function updateFeature<K extends keyof DiabetesFeatures>(key: K, raw: string) {
    const num = Number(raw);
    setFeatures(f => ({ ...f, [key]: Number.isFinite(num) ? num : 0 }));
  }

  async function onRunDynamic(e?: FormEvent, overrideQuery?: string) {
    if (e) e.preventDefault();
    const q = (overrideQuery ?? dynamicQuery).trim();
    if (!q) {
      setError('Please enter a health-related question or request for the dynamic orchestrator.');
      return;
    }
    if (overrideQuery) setDynamicQuery(overrideQuery);
    setRunning('dynamic'); setError('');
    try {
      const r = await runDynamicWorkflow({
        query: q,
        metric_type: metric,
        max_steps: maxSteps,
        experimental_ml: experimentalMl,
        ml_features: experimentalMl ? features : null,
        allow_notification_delivery: allowNotifDelivery,
      });
      setResult(r);
      void loadSide();
    } catch (err) {
      setError(errorMessage(err, 'Dynamic agentic workflow failed'));
    } finally {
      setRunning(null);
    }
  }

  async function run(action: Exclude<Action, 'dynamic'>) {
    setRunning(action); setError('');
    try {
      const r = action === 'assess'
        ? await runAssessment({
            metric_type: metric,
            include_knowledge: includeKnowledge,
            experimental_ml: experimentalMl,
            ml_features: experimentalMl ? features : null,
          })
        : action === 'summary' ? await getHealthSummary(metric)
          : await runMedicationCheck();
      setResult(r);
      void loadSide();
    } catch (e) { setError(errorMessage(e, 'Agent workflow failed')); }
    finally { setRunning(null); }
  }

  async function runDirectScreening(e: FormEvent) {
    e.preventDefault();
    setMlBusy(true); setMlError('');
    try {
      const res = await predictDiabetesV3(features);
      setMlResult(res);
    } catch (err) {
      setMlError(errorMessage(err, 'Experimental diabetes screening failed'));
    } finally {
      setMlBusy(false);
    }
  }

  const stepFor = (re: RegExp) => result?.execution_steps.find(s => re.test(s.agent_name));

  return <>
    <div className="agent-banner"><BrainCircuit size={32} /><div><h3>Dynamic Agentic Orchestration</h3><p>Submit a natural-language health request or run a structured workflow. The orchestrator iteratively selects only the needed allowlisted tools, evaluates intermediate observations, and records a verifiable execution trace.</p></div></div>
    {!user ? (
      <Alert kind="info">
        {DEMO
          ? 'Dynamic Multi-Agent Orchestration (POST /orchestration/execute), persisted execution audit history, and the Experimental Diabetes Screening Model (v3) require the full FastAPI + SQLAlchemy + ChromaDB + Scikit-Learn backend and are unavailable in this lightweight Vercel demo. Agent executions are never simulated here. Use the AI Assistant tab to test live Groq educational Q&A.'
          : 'Sign in to the live backend to run agent workflows.'}
      </Alert>
    ) : <div className="panel run-panel">
      <div className="panel-heading">
        <div>
          <h3>Dynamic agentic request (Decision → Execution → Observation loop)</h3>
          <p>Bounded iterative planner via <code>POST /orchestration/execute</code> · Selects tools dynamically based on context & intermediate results</p>
        </div>
        <span className="panel-icon"><Sparkles size={20} /></span>
      </div>

      <form onSubmit={e => void onRunDynamic(e)}>
        <label className="field">
          Your health, document, or medication request
          <input
            type="text"
            value={dynamicQuery}
            onChange={e => setDynamicQuery(e.target.value)}
            placeholder="e.g., Assess my recent blood glucose measurements and explain any deviation, or ask about an uploaded lab report…"
            required
          />
        </label>

        <div className="row-actions" style={{ marginTop: 8, flexWrap: 'wrap', gap: 6 }}>
          <small className="muted" style={{ marginRight: 4 }}>Try scenario:</small>
          {DYNAMIC_PRESETS.map((p, idx) => (
            <button
              key={idx}
              type="button"
              className="btn btn-ghost small"
              disabled={!!running}
              onClick={() => void onRunDynamic(undefined, p.query)}
              title={p.query}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="field">Primary metric context<select value={metric} onChange={e => setMetric(e.target.value)}>{METRICS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="field">Max tool executions (1–8)<input type="number" min={1} max={8} value={maxSteps} onChange={e => setMaxSteps(Math.max(1, Math.min(8, Number(e.target.value) || 6)))} /></label>
          <label className="check-line field-inline"><input type="checkbox" checked={experimentalMl} onChange={e => setExperimentalMl(e.target.checked)} /> Allow experimental ML diabetes screening (v3)</label>
          <label className="check-line field-inline"><input type="checkbox" checked={allowNotifDelivery} onChange={e => setAllowNotifDelivery(e.target.checked)} /> Authorize pending notification delivery</label>
        </div>

        <div className="row-actions" style={{ marginTop: 12, flexWrap: 'wrap' }}>
          <button type="submit" className="btn btn-primary" disabled={!!running}><Send size={15} />{running === 'dynamic' ? 'Orchestrating dynamically…' : 'Run dynamic orchestrator'}</button>
          <button type="button" className="btn btn-ghost" disabled={!!running} onClick={() => void run('assess')}><Play size={15} />{running === 'assess' ? 'Running assessment…' : 'Static: Assessment (Workflow A)'}</button>
          <button type="button" className="btn btn-ghost" disabled={!!running} onClick={() => void run('medication')}><Pill size={15} />{running === 'medication' ? 'Checking…' : 'Static: Medication check (Workflow B)'}</button>
          <button type="button" className="btn btn-ghost" disabled={!!running} onClick={() => void run('summary')}><FileText size={15} />{running === 'summary' ? 'Generating…' : 'Static: Full summary (Workflow C)'}</button>
          <label className="check-line" style={{ marginLeft: 'auto', fontSize: 13 }}><input type="checkbox" checked={includeKnowledge} onChange={e => setIncludeKnowledge(e.target.checked)} /> Include RAG in Workflow A</label>
        </div>
      </form>
      {running && <Spinner label="Iterative orchestrator is evaluating context and executing selected agent tools…" />}
      {error && <Alert onClose={() => setError('')}>{error}</Alert>}
    </div>}

    <div className="agent-grid">{AGENTS.map(({ key, match, name, desc, icon: Icon, tone }) => {
      const step = stepFor(match);
      const stepOrder = step?.step_order ?? (step && result ? result.execution_steps.indexOf(step) + 1 : null);
      return <div className="panel agent-tile" key={key}>
        <div className="agent-top">
          <span className={`feature-icon ${tone}`}><Icon size={21} /></span>
          {step ? <Badge value={`Step ${stepOrder} · ${step.status}`} /> : <span className="architecture-badge">{result ? 'SKIPPED' : DEMO && !user ? 'FULL BACKEND' : 'IDLE'}</span>}
        </div>
        <h3>{name} Agent</h3>
        <p>{step?.selection_reason || desc}</p>
        <div className="agent-foot">
          <span>{step ? `${step.tool_name ? `${step.tool_name} · ` : ''}${step.duration_ms} ms` : result ? 'Not needed for this request' : DEMO && !user ? 'Requires full FastAPI backend' : 'Allowlisted agent service'}</span>
        </div>
      </div>;
    })}</div>

    {result && <AssessmentResult r={result} />}

    {user && <div className="panel run-panel">
      <div className="panel-heading">
        <div>
          <h3>Experimental Diabetes Screening Model (v3)</h3>
          <p>Direct inference via <code>POST /ml/diabetes/predict-v3</code> & shared parameters for the Risk Assessment Agent · Non-diagnostic research demonstration</p>
        </div>
        <span className="panel-icon"><FlaskConical size={20} /></span>
      </div>
      <form className="form-grid" onSubmit={runDirectScreening}>
        <label className="field">Glucose (mg/dL)<input type="number" min="1" max="600" step="any" required value={features.Glucose} onChange={e => updateFeature('Glucose', e.target.value)} /></label>
        <label className="field">Diastolic BP (mmHg)<input type="number" min="1" max="250" step="any" required value={features.BloodPressure} onChange={e => updateFeature('BloodPressure', e.target.value)} /></label>
        <label className="field">BMI (kg/m²)<input type="number" min="1" max="100" step="any" required value={features.BMI} onChange={e => updateFeature('BMI', e.target.value)} /></label>
        <label className="field">Age (years)<input type="number" min="1" max="120" step="1" required value={features.Age} onChange={e => updateFeature('Age', e.target.value)} /></label>
        <label className="field">Insulin (µU/mL)<input type="number" min="1" max="1000" step="any" required value={features.Insulin} onChange={e => updateFeature('Insulin', e.target.value)} /></label>
        <label className="field">Skin Thickness (mm)<input type="number" min="1" max="100" step="any" required value={features.SkinThickness} onChange={e => updateFeature('SkinThickness', e.target.value)} /></label>
        <label className="field">Pedigree Function<input type="number" min="0" max="5" step="0.01" required value={features.DiabetesPedigreeFunction} onChange={e => updateFeature('DiabetesPedigreeFunction', e.target.value)} /></label>
        <label className="field">Pregnancies<input type="number" min="0" max="25" step="1" required value={features.Pregnancies} onChange={e => updateFeature('Pregnancies', e.target.value)} /></label>
        <div className="field form-submit">
          <button className="btn btn-primary" disabled={mlBusy}><FlaskConical size={15} />{mlBusy ? 'Evaluating…' : 'Run v3 screening'}</button>
        </div>
      </form>
      {mlError && <Alert onClose={() => setMlError('')}>{mlError}</Alert>}
      {mlResult && (
        <div className="detail-grid" style={{ marginTop: 14 }}>
          <div><span>Screening classification</span><b><Badge value={mlResult.prediction === 1 ? 'elevated_score' : 'below_threshold'} tone={mlResult.prediction === 1 ? 'warn' : 'ok'} /> {mlResult.screening_result}</b></div>
          <div><span>Model score</span><b>{(mlResult.model_score * 100).toFixed(1)}% (raw {mlResult.model_score})</b></div>
          <div><span>Decision threshold</span><b>{(mlResult.threshold * 100).toFixed(0)}% ({mlResult.threshold})</b></div>
          <div><span>Model artifact</span><b>{mlResult.model} · {mlResult.model_version}</b></div>
          <div className="span-all"><small className="muted">{mlResult.disclaimer}</small></div>
        </div>
      )}
    </div>}

    {user && <div className="two-cols agents-lower">
      <div className="panel"><div className="panel-heading"><div><h3>Execution history</h3><p>Click any audit entry to expand its agent selection trace</p></div><button className="icon-btn" onClick={() => void loadSide()} aria-label="Refresh history"><RefreshCw size={16} /></button></div>
        {history === null ? <Spinner /> : history.length === 0 ? <Empty>No workflows run yet.</Empty> : <div className="list">{history.map(h => {
          const isOpen = expandedAuditId === h.id;
          return <div key={h.id} style={{ borderBottom: '1px solid rgba(148,163,184,0.14)', paddingBottom: isOpen ? 10 : 0 }}>
            <div className="list-row" style={{ cursor: 'pointer' }} onClick={() => setExpandedAuditId(prev => prev === h.id ? null : h.id)}>
              <History size={16} className="muted" />
              <div>
                <b>{humanize(h.workflow_type.replace(/^workflow_[a-d]_/, ''))}</b>
                {h.user_request && <small style={{ display: 'block', fontWeight: 500 }}>Request: "{h.user_request}"</small>}
                <small>{h.error_message || h.summary || '—'}</small>
              </div>
              <div className="row-meta">
                <Badge value={h.status} />
                {h.planner_mode && <Badge value={h.planner_mode} tone="muted" />}
                <small className="muted">{fmtDateTime(h.created_at)}{h.duration_ms != null ? ` · ${h.duration_ms} ms` : ''}</small>
                {isOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              </div>
            </div>
            {isOpen && (
              <div style={{ padding: '8px 12px', fontSize: 13 }}>
                {h.selected_agents && h.selected_agents.length > 0 && (
                  <p style={{ margin: '0 0 6px' }}><b>Selected agents:</b> {h.selected_agents.join(' → ')}</p>
                )}
                {h.execution_steps && h.execution_steps.length > 0 ? (
                  <TraceTable steps={h.execution_steps} />
                ) : (
                  <small className="muted">No step-level trace details recorded for this entry.</small>
                )}
              </div>
            )}
          </div>;
        })}</div>}
      </div>
      <div className="panel"><div className="panel-heading"><div><h3>Agent alerts</h3><p>Open monitoring events, reminders and escalations</p></div></div>
        {!alerts ? <Spinner /> : (alerts.unread_monitoring_events.length + alerts.pending_medication_reminders.length + alerts.recent_safety_escalations.length) === 0 ? <Empty>No open alerts.</Empty> : <div className="list">
          {alerts.recent_safety_escalations.map(e => <div className="list-row" key={`e${e.id}`}><Badge value="escalated" /><div><b>{humanize(e.workflow_type)}</b><small>{fmtDateTime(e.created_at)}</small></div></div>)}
          {alerts.unread_monitoring_events.map(e => <div className="list-row" key={`m${e.id}`}><Badge value={e.event_level} /><div><b>{humanize(e.metric_type)}</b><small>{e.message}</small></div></div>)}
          {alerts.pending_medication_reminders.map(r => <div className="list-row" key={`r${r.id}`}><Badge value="pending" /><div><b>Reminder</b><small>{r.message}</small></div></div>)}
        </div>}
      </div>
    </div>}
  </>;
}

function TraceTable({ steps }: { steps: ExecutionStep[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Agent / Tool</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Why Selected</th>
            <th>Observation & Output</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s, i) => {
            const interStr = formatIntermediateOutput(s.intermediate_output);
            return (
              <tr key={i}>
                <td>{s.step_order ?? i + 1}</td>
                <td>
                  <b>{humanize(s.agent_name)}</b>
                  {s.tool_name && <small style={{ display: 'block', opacity: 0.8 }}><code>{s.tool_name}</code></small>}
                </td>
                <td><Badge value={s.status} /></td>
                <td>{s.duration_ms} ms</td>
                <td>{s.selection_reason ?? 'Part of workflow'}</td>
                <td>
                  <div>{s.details ?? '—'}</div>
                  {interStr && <small className="muted" style={{ display: 'block', marginTop: 2 }}>{interStr}</small>}
                  {s.error_recovery && <small className="text-danger" style={{ display: 'block', marginTop: 2 }}>Recovery/Note: {s.error_recovery}</small>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AssessmentResult({ r }: { r: HealthSummary }) {
  const mlEst = r.risk_assessment?.experimental_ml_estimates?.[0] as Record<string, unknown> | undefined;
  return <div className="panel result-panel">
    <div className="panel-heading">
      <div>
        <h3>{humanize(r.workflow_type.replace(/^workflow_[a-d]_/, ''))}</h3>
        <p>
          Generated {fmtDateTime(r.generated_at)} · {r.duration_ms} ms
          {r.detected_intent ? ` · Intent: ${humanize(r.detected_intent)}` : ''}
          {r.planner_mode ? ` · Mode: ${humanize(r.planner_mode)}` : ''}
        </p>
        {r.user_request && <p style={{ marginTop: 4 }}><b>Request:</b> "{r.user_request}"</p>}
        {r.selected_agents && r.selected_agents.length > 0 && (
          <p style={{ marginTop: 2 }}><b>Execution path:</b> {r.selected_agents.join(' → ')}</p>
        )}
        {r.termination_reason && (
          <p style={{ marginTop: 2 }}><small className="muted"><b>Termination condition:</b> {r.termination_reason}</small></p>
        )}
      </div>
      <Badge value={r.orchestration_state} />
    </div>
    {r.safety_escalation && <Alert kind="error"><b>Safety notice:</b> {String((r.safety_escalation as Record<string, unknown>).message ?? (r.safety_escalation as Record<string, unknown>).guidance ?? 'A potentially urgent reading was detected. If you feel unwell, contact a healthcare professional or emergency services.')}</Alert>}
    {r.medical_knowledge?.is_emergency && r.medical_knowledge.emergency_guidance && <Alert kind="error">{r.medical_knowledge.emergency_guidance}</Alert>}
    <p className="summary-text">{r.summary_text}</p>
    <div className="result-grid">
      {r.monitoring && <div className="result-card"><h4>Monitoring <Badge value={r.monitoring.status} /></h4><p>{r.monitoring.summary}</p><small>Latest: {r.monitoring.latest_value ?? '—'} {r.monitoring.unit} · {r.monitoring.recent_readings_count} recent readings</small>{r.monitoring.is_urgent && r.monitoring.urgent_reason && <small className="text-danger">{r.monitoring.urgent_reason}</small>}</div>}
      {r.risk_assessment && <div className="result-card"><h4>Risk assessment <Badge value={r.risk_assessment.risk_level} /></h4><p>{r.risk_assessment.summary}</p>
        {mlEst && (
          <small style={{ marginTop: 6 }}>
            <b>Experimental ML ({String(mlEst.model_version ?? 'v3')}):</b> {String(mlEst.screening_result ?? mlEst.status ?? '—')}
            {typeof mlEst.model_score === 'number' ? ` · score ${(mlEst.model_score * 100).toFixed(1)}% (threshold ${Number(mlEst.decision_threshold ?? 0.4) * 100}%)` : ''}
          </small>
        )}
      </div>}
      {r.medication && <div className="result-card"><h4>Medication</h4><p>{r.medication.summary}</p><small>{r.medication.active_medications_count} active · adherence {r.medication.overall_adherence_percentage ?? '—'}% · {r.medication.overdue_doses_count} overdue · {r.medication.missed_doses_count} missed</small>{r.medication.recommendations.length > 0 && <ul>{r.medication.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul>}</div>}
      {r.medical_knowledge && <div className="result-card"><h4>Medical knowledge <Badge value={r.medical_knowledge.status} /></h4><p>{r.medical_knowledge.explanation}</p>{r.medical_knowledge.citations.length > 0 && <div className="sources"><b>References</b>{r.medical_knowledge.citations.map((c, i) => <small key={i}>[{i + 1}] {c.title}{c.source_organization ? ` — ${c.source_organization}` : ''}</small>)}</div>}</div>}
      {r.notifications && <div className="result-card"><h4>Notifications</h4><p>{r.notifications.summary}</p><small>{r.notifications.notifications_created.length} listed/created · {r.notifications.suppressed_count} suppressed</small></div>}
    </div>
    {r.execution_steps.length > 0 && <TraceTable steps={r.execution_steps} />}
    <p className="fineprint">{r.disclaimer}</p>
  </div>;
}
