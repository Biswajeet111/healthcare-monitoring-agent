import { useRef, useState, type FormEvent } from 'react';
import { Plus, Upload } from 'lucide-react';
import { createBloodPressure, createMetric, errorMessage, importCsv, METRIC_TYPES, type Metric, type MetricType, type UserProfile } from '../api';
import { Alert, ChartCard, type Range } from '../components/ui';
import { SnapshotStats } from './Overview';

type Props = { user: UserProfile | null; metrics: Metric[]; chartData: (Metric & { label: string })[]; range: Range; setRange: (r: Range) => void; onChanged: () => void };
type EntryType = MetricType | 'blood_pressure';
const ENTRY_TYPES: EntryType[] = ['heart_rate', 'blood_glucose', 'blood_pressure', 'steps', 'weight', 'height', 'sleep_duration'];
const entryLabel = (t: EntryType) => (t === 'blood_pressure' ? 'Blood pressure' : METRIC_TYPES[t].label);

export default function Analytics({ user, metrics, chartData, range, setRange, onChanged }: Props) {
  const [type, setType] = useState<EntryType>('heart_rate');
  const [unit, setUnit] = useState('bpm');
  const [value, setValue] = useState('');
  const [systolic, setSystolic] = useState('');
  const [diastolic, setDiastolic] = useState('');
  const [context, setContext] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'success' | 'error' | 'warn'; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  function changeType(t: EntryType) { setType(t); setUnit(t === 'blood_pressure' ? 'mmHg' : METRIC_TYPES[t].units[0]); }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    setMsg(null);
    const extra = { context: context.trim() || undefined, notes: notes.trim() || undefined };
    try {
      if (type === 'blood_pressure') {
        const s = Number(systolic), d = Number(diastolic);
        if (!(s > 0) || !(d > 0)) { setMsg({ kind: 'error', text: 'Enter positive systolic and diastolic values.' }); return; }
        if (d >= s) { setMsg({ kind: 'error', text: 'Diastolic should be lower than systolic.' }); return; }
        setBusy(true);
        await createBloodPressure(user.id, { systolic: s, diastolic: d, ...extra });
      } else {
        const v = Number(value);
        if (!(v > 0)) { setMsg({ kind: 'error', text: 'Enter a value greater than zero.' }); return; }
        setBusy(true);
        await createMetric(user.id, { metric_type: type, value: v, unit, ...extra });
      }
      setMsg({ kind: 'success', text: `${entryLabel(type)} saved. Monitoring checks ran automatically.` });
      setValue(''); setSystolic(''); setDiastolic(''); setNotes(''); setContext('');
      onChanged();
    } catch (err) { setMsg({ kind: 'error', text: errorMessage(err, 'Could not save measurement') }); }
    finally { setBusy(false); }
  }

  async function onCsv(file: File | undefined) {
    if (!file) return;
    setMsg(null); setImporting(true);
    try {
      const r = await importCsv(file);
      setMsg({ kind: r.failed_count ? 'warn' : 'success', text: `Imported ${r.imported_count} measurement(s)${r.failed_count ? `, ${r.failed_count} row(s) failed validation` : ''}.` });
      onChanged();
    } catch (err) { setMsg({ kind: 'error', text: errorMessage(err, 'CSV import failed') }); }
    finally { setImporting(false); if (fileRef.current) fileRef.current.value = ''; }
  }

  return <>
    <SnapshotStats metrics={metrics} note="Latest" />
    {user && <div className="panel entry-panel">
      <div className="panel-heading"><div><h3>Record a measurement</h3><p>Saved to your account · values are not diagnostic</p></div>
        <div className="row-actions"><input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={e => void onCsv(e.target.files?.[0])} /><button type="button" className="btn btn-ghost" disabled={importing} onClick={() => fileRef.current?.click()}><Upload size={15} />{importing ? 'Importing…' : 'Import CSV'}</button></div></div>
      <form className="form-grid" onSubmit={submit}>
        <label className="field">Type<select value={type} onChange={e => changeType(e.target.value as EntryType)}>{ENTRY_TYPES.map(t => <option key={t} value={t}>{entryLabel(t)}</option>)}</select></label>
        {type === 'blood_pressure' ? <>
          <label className="field">Systolic (mmHg)<input type="number" inputMode="decimal" min="1" step="any" required value={systolic} onChange={e => setSystolic(e.target.value)} /></label>
          <label className="field">Diastolic (mmHg)<input type="number" inputMode="decimal" min="1" step="any" required value={diastolic} onChange={e => setDiastolic(e.target.value)} /></label>
        </> : <>
          <label className="field">Value<input type="number" inputMode="decimal" min="0" step="any" required value={value} onChange={e => setValue(e.target.value)} /></label>
          <label className="field">Unit<select value={unit} onChange={e => setUnit(e.target.value)}>{METRIC_TYPES[type].units.map(u => <option key={u}>{u}</option>)}</select></label>
        </>}
        <label className="field">Context<input placeholder="e.g. fasting, after exercise" value={context} onChange={e => setContext(e.target.value)} /></label>
        <label className="field span-2">Notes<input placeholder="Optional" value={notes} onChange={e => setNotes(e.target.value)} /></label>
        <div className="field form-submit"><button className="btn btn-primary" disabled={busy}><Plus size={16} />{busy ? 'Saving…' : 'Save measurement'}</button></div>
      </form>
      {msg && <Alert kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <p className="fineprint">CSV files are validated by the backend; duplicate files are rejected. Units are normalized by the backend before storage.</p>
    </div>}
    <div className="analytics-grid">
      <ChartCard title="Heart rate" subtitle="Beats per minute" data={chartData} dataKey="heartRate" color="#f06a98" range={range} setRange={setRange} />
      <ChartCard title="Blood glucose" subtitle="mg/dL · Values are not diagnostic" data={chartData} dataKey="glucose" color="#7a8ef9" range={range} setRange={setRange} />
      <ChartCard title="Systolic blood pressure" subtitle="mmHg · Review measurements with a clinician" data={chartData} dataKey="systolic" color="#a78bfa" range={range} setRange={setRange} />
      <ChartCard title="Daily activity" subtitle="Steps per day" data={chartData} dataKey="steps" color="#45cda5" range={range} setRange={setRange} />
    </div>
    <div className="panel table-panel"><h3>Recent measurements</h3><div className="table-scroll"><table><thead><tr><th>Date</th><th>Heart rate</th><th>Glucose</th><th>Blood pressure</th><th>Steps</th></tr></thead><tbody>{[...chartData].reverse().map(m => <tr key={m.id}><td>{m.label}</td><td>{Number.isFinite(m.heartRate) ? `${m.heartRate} bpm` : '—'}</td><td>{Number.isFinite(m.glucose) ? `${m.glucose} mg/dL` : '—'}</td><td>{Number.isFinite(m.systolic) && Number.isFinite(m.diastolic) ? `${m.systolic}/${m.diastolic}` : '—'}</td><td>{Number.isFinite(m.steps) ? m.steps.toLocaleString() : '—'}</td></tr>)}</tbody></table></div>{chartData.length === 0 && <p className="muted">No measurements in the selected period.</p>}</div>
  </>;
}
