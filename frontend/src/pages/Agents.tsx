import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Activity, Bell, BrainCircuit, ClipboardList, Database, FileText, FlaskConical, History, Pill, Play, RefreshCw, ShieldCheck } from 'lucide-react';
import {
  errorMessage, fmtDateTime, getHealthSummary, getOrchestrationAlerts, getOrchestrationHistory, humanize, predictDiabetesV3, runAssessment, runMedicationCheck,
  type AuditEntry, type DiabetesFeatures, type DiabetesPredictionV3, type HealthSummary, type OrchestrationAlerts, type UserProfile,
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
type Action = 'assess' | 'summary' | 'medication';

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

export default function Agents({ user }: { user: UserProfile | null }) {
  const [metric, setMetric] = useState<string>('blood_glucose');
  const [includeKnowledge, setIncludeKnowledge] = useState(true);
  const [experimentalMl, setExperimentalMl] = useState(true);
  const [features, setFeatures] = useState<DiabetesFeatures>(DEFAULT_ML_FEATURES);
  const [running, setRunning] = useState<Action | null>(null);
  const [result, setResult] = useState<HealthSummary | null>(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<AuditEntry[] | null>(null);
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

  async function run(action: Action) {
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
    <div className="agent-banner"><BrainCircuit size={32} /><div><h3>Coordinated AI architecture</h3><p>Five specialized backend agents support structured health-information workflows. Run a workflow to see each agent's live execution status. Outputs are informational and never a diagnosis.</p></div></div>
    {!user ? <Alert kind="info">Sign in to the live backend to run agent workflows.</Alert> : <div className="panel run-panel">
      <div className="form-grid">
        <label className="field">Primary metric<select value={metric} onChange={e => setMetric(e.target.value)}>{METRICS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="check-line field-inline"><input type="checkbox" checked={includeKnowledge} onChange={e => setIncludeKnowledge(e.target.checked)} /> Include medical knowledge (uses local LLM)</label>
        <label className="check-line field-inline"><input type="checkbox" checked={experimentalMl} onChange={e => setExperimentalMl(e.target.checked)} /> Include experimental ML diabetes screening (v3)</label>
      </div>
      <div className="row-actions" style={{ marginTop: 12 }}>
        <button className="btn btn-primary" disabled={!!running} onClick={() => void run('assess')}><Play size={15} />{running === 'assess' ? 'Running assessment…' : 'Run health assessment'}</button>
        <button className="btn btn-ghost" disabled={!!running} onClick={() => void run('summary')}><FileText size={15} />{running === 'summary' ? 'Generating…' : 'Health summary'}</button>
        <button className="btn btn-ghost" disabled={!!running} onClick={() => void run('medication')}><Pill size={15} />{running === 'medication' ? 'Checking…' : 'Medication check'}</button>
      </div>
      {running && <Spinner label="Agents are working. Knowledge retrieval with a local model can take up to a minute…" />}
      {error && <Alert>{error}</Alert>}
    </div>}

    <div className="agent-grid">{AGENTS.map(({ key, match, name, desc, icon: Icon, tone }) => {
      const step = stepFor(match);
      return <div className="panel agent-tile" key={key}><div className="agent-top"><span className={`feature-icon ${tone}`}><Icon size={21} /></span>{step ? <Badge value={step.status} /> : <span className="architecture-badge">{result ? 'NOT USED' : 'IDLE'}</span>}</div><h3>{name} Agent</h3><p>{desc}</p><div className="agent-foot"><span>{step ? `${step.duration_ms} ms${step.details ? ` · ${step.details}` : ''}` : 'Orchestrated service'}</span></div></div>;
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
      <div className="panel"><div className="panel-heading"><div><h3>Execution history</h3><p>Audit log of agent workflows</p></div><button className="icon-btn" onClick={() => void loadSide()} aria-label="Refresh history"><RefreshCw size={16} /></button></div>
        {history === null ? <Spinner /> : history.length === 0 ? <Empty>No workflows run yet.</Empty> : <div className="list">{history.map(h => <div className="list-row" key={h.id}><History size={16} className="muted" /><div><b>{humanize(h.workflow_type.replace(/^workflow_[a-d]_/, ''))}</b><small>{h.error_message || h.summary || '—'}</small></div><div className="row-meta"><Badge value={h.status} /><small className="muted">{fmtDateTime(h.created_at)}{h.duration_ms != null ? ` · ${h.duration_ms} ms` : ''}</small></div></div>)}</div>}
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

function AssessmentResult({ r }: { r: HealthSummary }) {
  const mlEst = r.risk_assessment?.experimental_ml_estimates?.[0] as Record<string, unknown> | undefined;
  return <div className="panel result-panel">
    <div className="panel-heading"><div><h3>{humanize(r.workflow_type.replace(/^workflow_[a-d]_/, ''))}</h3><p>Generated {fmtDateTime(r.generated_at)} · {r.duration_ms} ms</p></div><Badge value={r.orchestration_state} /></div>
    {r.safety_escalation && <Alert kind="error"><b>Safety notice:</b> {String((r.safety_escalation as Record<string, unknown>).message ?? (r.safety_escalation as Record<string, unknown>).guidance ?? 'A potentially urgent reading was detected. If you feel unwell, contact a healthcare professional or emergency services.')}</Alert>}
    {r.medical_knowledge?.is_emergency && r.medical_knowledge.emergency_guidance && <Alert kind="error">{r.medical_knowledge.emergency_guidance}</Alert>}
    <p className="summary-text">{r.summary_text}</p>
    <div className="result-grid">
      {r.monitoring && <div className="result-card"><h4>Monitoring <Badge value={r.monitoring.status} /></h4><p>{r.monitoring.summary}</p><small>Latest: {r.monitoring.latest_value ?? '—'} {r.monitoring.unit} · {r.monitoring.recent_readings_count} recent readings</small>{r.monitoring.is_urgent && r.monitoring.urgent_reason && <small className="text-danger">{r.monitoring.urgent_reason}</small>}</div>}
      {r.risk_assessment && <div className="result-card"><h4>Risk assessment <Badge value={r.risk_assessment.risk_level} /></h4><p>{r.risk_assessment.summary}</p>
        {mlEst && (
          <small style={{ marginTop: 6 }}>
            <b>Experimental ML ({String(mlEst.model_version ?? 'v3')}):</b> {String(mlEst.screening_result ?? mlEst.status ?? '—')}
            {typeof mlEst.model_score === 'number' ? ` · score ${(mlEst.model_score * 100).toFixed(1)}% (threshold ${Number(mlEst.decision_threshold ?? 0.3) * 100}%)` : ''}
          </small>
        )}
      </div>}
      {r.medication && <div className="result-card"><h4>Medication</h4><p>{r.medication.summary}</p><small>{r.medication.active_medications_count} active · adherence {r.medication.overall_adherence_percentage ?? '—'}% · {r.medication.overdue_doses_count} overdue · {r.medication.missed_doses_count} missed</small>{r.medication.recommendations.length > 0 && <ul>{r.medication.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul>}</div>}
      {r.medical_knowledge && <div className="result-card"><h4>Medical knowledge <Badge value={r.medical_knowledge.status} /></h4><p>{r.medical_knowledge.explanation}</p>{r.medical_knowledge.citations.length > 0 && <div className="sources"><b>References</b>{r.medical_knowledge.citations.map((c, i) => <small key={i}>[{i + 1}] {c.title}{c.source_organization ? ` — ${c.source_organization}` : ''}</small>)}</div>}</div>}
      {r.notifications && <div className="result-card"><h4>Notifications</h4><p>{r.notifications.summary}</p><small>{r.notifications.notifications_created.length} created · {r.notifications.suppressed_count} suppressed</small></div>}
    </div>
    {r.execution_steps.length > 0 && <div className="table-scroll"><table><thead><tr><th>Agent</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead><tbody>{r.execution_steps.map((s, i) => <tr key={i}><td>{humanize(s.agent_name)}</td><td><Badge value={s.status} /></td><td>{s.duration_ms} ms</td><td>{s.details ?? '—'}</td></tr>)}</tbody></table></div>}
    <p className="fineprint">{r.disclaimer}</p>
  </div>;
}
