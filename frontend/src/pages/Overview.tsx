import { useCallback, useEffect, useState } from 'react';
import { Activity, ArrowRight, ArrowUpRight, Bell, Bot, BrainCircuit, ClipboardList, Heart, HeartPulse, ShieldCheck, Stethoscope, Watch } from 'lucide-react';
import { errorMessage, fmtDateTime, fmtTime, getOrchestrationAlerts, getTodayDoses, humanize, type Metric, type OrchestrationAlerts, type TodayDose, type UserProfile } from '../api';
import { Alert, Badge, ChartCard, Empty, Spinner, Stat, type Range } from '../components/ui';
import type { Page } from '../App';

type Props = { user: UserProfile | null; metrics: Metric[]; chartData: (Metric & { label: string })[]; range: Range; setRange: (r: Range) => void; setPage: (p: Page) => void; refreshKey: number };

export function latestOf(metrics: Metric[], key: keyof Metric): number | undefined {
  for (let i = metrics.length - 1; i >= 0; i--) { const v = metrics[i][key] as number; if (Number.isFinite(v)) return v; }
  return undefined;
}

export function SnapshotStats({ metrics, note }: { metrics: Metric[]; note: string }) {
  const hr = latestOf(metrics, 'heartRate'), gl = latestOf(metrics, 'glucose'), sys = latestOf(metrics, 'systolic'), dia = latestOf(metrics, 'diastolic'), st = latestOf(metrics, 'steps');
  return <div className="stats-grid">
    <Stat label="Heart rate" value={hr} unit="bpm" icon={HeartPulse} color="pink" note={note} />
    <Stat label="Blood glucose" value={gl} unit="mg/dL" icon={Activity} color="blue" note={note} />
    <Stat label="Blood pressure" value={sys !== undefined && dia !== undefined ? `${sys}/${dia}` : undefined} unit="mmHg" icon={Stethoscope} color="purple" note={note} />
    <Stat label="Daily steps" value={st?.toLocaleString()} unit="steps" icon={Watch} color="green" note={note} />
  </div>;
}

export default function Overview({ user, metrics, chartData, range, setRange, setPage, refreshKey }: Props) {
  const [alerts, setAlerts] = useState<OrchestrationAlerts | null>(null);
  const [doses, setDoses] = useState<TodayDose[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true); setError('');
    const [a, d] = await Promise.allSettled([getOrchestrationAlerts(), getTodayDoses(user.id)]);
    if (a.status === 'fulfilled') setAlerts(a.value); else setError(errorMessage(a.reason));
    if (d.status === 'fulfilled') setDoses(d.value.doses); else setError(e => e || errorMessage(d.reason));
    setLoading(false);
  }, [user]);
  useEffect(() => { void load(); }, [load, refreshKey]);

  const alertCount = alerts ? alerts.unread_monitoring_events.length + alerts.pending_medication_reminders.length + alerts.recent_safety_escalations.length : 0;

  return <>
    <div className="welcome"><div><div className="welcome-pill"><Heart size={14} /> PERSONAL HEALTH COMPANION</div><h2>{user ? <>Welcome back, {user.full_name.split(' ')[0]}.<br /><em>Healthier decisions.</em></> : <>Better insights.<br /><em>Healthier decisions.</em></>}</h2><p>Track key measurements, explore health trends, and access evidence-oriented educational support in one place.</p><button onClick={() => setPage('Analytics')}>Explore analytics <ArrowRight size={17} /></button></div><div className="welcome-art"><div className="orb orb-one" /><div className="orb orb-two" /><HeartPulse size={122} strokeWidth={1.05} /></div></div>
    <div className="section-title"><h3>Health snapshot</h3><span>Latest recorded values</span></div>
    <SnapshotStats metrics={metrics} note="Latest measurement" />
    {metrics.length === 0 && user && <Alert kind="info">No measurements recorded yet. <button className="inline-link" onClick={() => setPage('Analytics')}>Add your first measurement</button>.</Alert>}
    <div className="two-cols">
      <ChartCard title="Heart rate trends" subtitle="Measurements over time" data={chartData} dataKey="heartRate" color="#f06a98" range={range} setRange={setRange} />
      <div className="panel agent-preview"><div className="panel-heading"><div><h3>Intelligent assistance</h3><p>Explore connected capabilities</p></div><span className="panel-icon"><BrainCircuit size={20} /></span></div>
        <button className="feature-row as-button" onClick={() => setPage('AI Assistant')}><span className="feature-icon purple"><Bot size={19} /></span><div><b>Medical knowledge assistant</b><small>Ask educational questions with reference context</small></div><ArrowUpRight size={17} /></button>
        <button className="feature-row as-button" onClick={() => setPage('Analytics')}><span className="feature-icon blue"><Activity size={19} /></span><div><b>Health monitoring</b><small>Review trends and structured measurements</small></div><ArrowUpRight size={17} /></button>
        <button className="feature-row as-button" onClick={() => setPage('Agents')}><span className="feature-icon green"><ShieldCheck size={19} /></span><div><b>Safety-oriented workflows</b><small>Run a multi-agent health assessment</small></div><ArrowUpRight size={17} /></button>
        <button className="panel-link" onClick={() => setPage('AI Assistant')}>Open assistant <ArrowRight size={16} /></button></div>
    </div>
    {user && <>
      {error && <Alert>{error}</Alert>}
      <div className="two-cols overview-lower">
        <div className="panel"><div className="panel-heading"><div><h3>Active alerts</h3><p>Unacknowledged monitoring events, reminders and escalations</p></div><span className="panel-icon"><Bell size={20} /></span></div>
          {loading && !alerts ? <Spinner /> : alertCount === 0 ? <Empty>No active alerts. You're all caught up.</Empty> : <div className="list">
            {alerts!.recent_safety_escalations.map(e => <div className="list-row" key={`esc-${e.id}`}><Badge value="escalated" /><div><b>Safety escalation</b><small>{humanize(e.workflow_type)} · {fmtDateTime(e.created_at)}</small></div></div>)}
            {alerts!.unread_monitoring_events.slice(0, 5).map(e => <div className="list-row" key={`ev-${e.id}`}><Badge value={e.event_level} /><div><b>{humanize(e.metric_type)}</b><small>{e.message}</small></div><small className="muted">{fmtDateTime(e.created_at)}</small></div>)}
            {alerts!.pending_medication_reminders.slice(0, 5).map(r => <div className="list-row" key={`rem-${r.id}`}><Badge value="pending" /><div><b>Medication reminder</b><small>{r.message}</small></div></div>)}
          </div>}
          <button className="panel-link" onClick={() => setPage('Notifications')}>View all notifications <ArrowRight size={16} /></button></div>
        <div className="panel"><div className="panel-heading"><div><h3>Today's medications</h3><p>Scheduled doses for today (UTC day)</p></div><span className="panel-icon"><ClipboardList size={20} /></span></div>
          {doses === null ? <Spinner /> : doses.length === 0 ? <Empty>No doses scheduled today.</Empty> : <div className="list">{doses.map(d => <div className="list-row" key={d.occurrence_id}><Badge value={d.status} /><div><b>{d.medication_name}</b><small>{fmtTime(d.scheduled_at)}</small></div></div>)}</div>}
          <button className="panel-link" onClick={() => setPage('Medications')}>Manage medications <ArrowRight size={16} /></button></div>
      </div>
    </>}
  </>;
}

