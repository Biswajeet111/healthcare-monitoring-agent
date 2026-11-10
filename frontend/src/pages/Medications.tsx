import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { CalendarClock, CheckCircle2, ChevronDown, ChevronUp, ClipboardList, Pencil, Plus, ShieldCheck, SkipForward } from 'lucide-react';
import {
  confirmDose, createMedication, deactivateMedication, errorMessage, fmtTime, getAdherence, getSchedule, getTodayDoses, listMedications, saveSchedule, updateMedication,
  type Medication, type MedicationSchedule, type TodayDose, type UserProfile,
} from '../api';
import { Alert, Badge, ConfirmButton, Empty, Spinner } from '../components/ui';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const today = () => new Date().toISOString().slice(0, 10);

/**
 * The backend scheduler generates occurrences from HH:MM values interpreted as UTC.
 * We let users enter local times and convert them to UTC (and back for display).
 */
const tzOffsetMin = () => -new Date().getTimezoneOffset(); // local = UTC + offset
function shiftTime(hhmm: string, deltaMin: number): { time: string; dayShift: number } {
  const [h, m] = hhmm.split(':').map(Number);
  const total = h * 60 + m + deltaMin;
  const dayShift = Math.floor(total / 1440);
  const t = ((total % 1440) + 1440) % 1440;
  return { time: `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`, dayShift };
}
const shiftWeekdays = (days: number[], shift: number) => [...new Set(days.map(d => (((d + shift) % 7) + 7) % 7))].sort();

function describeSchedule(s: MedicationSchedule | null): string {
  if (!s) return 'No schedule';
  if (s.schedule_type === 'as_needed') return 'As needed';
  const local = s.times.map(t => shiftTime(t, tzOffsetMin()));
  const times = local.map(l => l.time).join(', ') || 'no times';
  if (s.schedule_type === 'daily') return `Daily at ${times}`;
  return `Weekly (${shiftWeekdays(s.weekdays, local[0]?.dayShift ?? 0).map(d => WEEKDAYS[d]).join(', ')}) at ${times}`;
}

type MedForm = { name: string; dosage: string; frequency: string; instructions: string; start_date: string; end_date: string };
const emptyForm = (): MedForm => ({ name: '', dosage: '', frequency: '', instructions: '', start_date: today(), end_date: '' });

export default function Medications({ user, onChanged }: { user: UserProfile | null; onChanged: () => void }) {
  const [meds, setMeds] = useState<Medication[] | null>(null);
  const [doses, setDoses] = useState<TodayDose[] | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [form, setForm] = useState<MedForm>(emptyForm());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!user) return;
    const [m, d] = await Promise.allSettled([listMedications(user.id, showInactive), getTodayDoses(user.id)]);
    if (m.status === 'fulfilled') setMeds(m.value); else { setMeds([]); setMsg({ kind: 'error', text: errorMessage(m.reason) }); }
    if (d.status === 'fulfilled') setDoses(d.value.doses); else setDoses([]);
  }, [user, showInactive]);
  useEffect(() => { void load(); }, [load]);

  const done = (text: string) => { setMsg({ kind: 'success', text }); void load(); onChanged(); };
  const fail = (e: unknown) => setMsg({ kind: 'error', text: errorMessage(e) });

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (!form.name.trim() || !form.dosage.trim() || !form.frequency.trim()) { setMsg({ kind: 'error', text: 'Name, dosage and frequency are required.' }); return; }
    if (form.end_date && form.end_date < form.start_date) { setMsg({ kind: 'error', text: 'End date cannot be before start date.' }); return; }
    setBusy(true); setMsg(null);
    try {
      const created = await createMedication(user.id, { name: form.name.trim(), dosage: form.dosage.trim(), frequency: form.frequency.trim(), instructions: form.instructions.trim() || null, start_date: form.start_date, end_date: form.end_date || null });
      setForm(emptyForm());
      setExpanded(created.id);
      done(`${created.name} added. Add a schedule to generate dose reminders.`);
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function dose(d: TodayDose, status: 'taken' | 'skipped') {
    try { await confirmDose(d.occurrence_id, status); done(`${d.medication_name} marked as ${status}.`); } catch (e) { fail(e); }
  }

  if (!user) return <Alert kind="info">Medication management requires signing in to the live backend.</Alert>;

  return <div className="two-cols medication-layout">
    <div className="stack">
      {msg && <Alert kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <div className="panel"><div className="panel-heading"><div><h3>Today's doses</h3><p>Confirm doses as you take them</p></div><span className="panel-icon"><CalendarClock size={20} /></span></div>
        {doses === null ? <Spinner /> : doses.length === 0 ? <Empty>No doses scheduled for today.</Empty> : <div className="med-list compact">{doses.map(d => <div className="med-item" key={d.occurrence_id}>
          <span className={`check ${d.status === 'taken' ? 'checked' : ''}`}><CheckCircle2 size={20} /></span>
          <div><b>{d.medication_name}</b><small>Scheduled {fmtTime(d.scheduled_at)}{d.taken_at ? ` · taken ${fmtTime(d.taken_at)}` : ''}</small></div>
          <Badge value={d.status} />
          {d.status !== 'taken' && <button className="btn btn-primary small" onClick={() => void dose(d, 'taken')}>Taken</button>}
          {d.status !== 'taken' && d.status !== 'skipped' && <button className="btn btn-ghost small" onClick={() => void dose(d, 'skipped')} aria-label={`Skip ${d.medication_name}`}><SkipForward size={14} /></button>}
        </div>)}</div>}
      </div>
      <div className="panel med-panel"><div className="panel-heading"><div><h3>Medication records</h3><p>Personal organization only · Not prescription advice</p></div><label className="check-line"><input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} /> Show inactive</label></div>
        {meds === null ? <Spinner /> : meds.length === 0 ? <Empty>No medications yet. Add one below.</Empty> : <div className="med-list">{meds.map(m => <MedRow key={m.id} med={m} open={expanded === m.id} toggle={() => setExpanded(x => (x === m.id ? null : m.id))} onDone={done} onError={fail} />)}</div>}
        <form className="form-grid med-add" onSubmit={add}>
          <h4 className="span-all">Add medication</h4>
          <label className="field">Name<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
          <label className="field">Dosage<input required placeholder="e.g. 500 mg" value={form.dosage} onChange={e => setForm({ ...form, dosage: e.target.value })} /></label>
          <label className="field">Frequency<input required placeholder="e.g. twice daily" value={form.frequency} onChange={e => setForm({ ...form, frequency: e.target.value })} /></label>
          <label className="field">Start date<input type="date" required value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} /></label>
          <label className="field">End date<input type="date" value={form.end_date} min={form.start_date} onChange={e => setForm({ ...form, end_date: e.target.value })} /></label>
          <label className="field span-2">Instructions<input placeholder="Optional, e.g. with food" value={form.instructions} onChange={e => setForm({ ...form, instructions: e.target.value })} /></label>
          <div className="field form-submit"><button className="btn btn-primary" disabled={busy}><Plus size={16} />{busy ? 'Adding…' : 'Add medication'}</button></div>
        </form>
      </div>
    </div>
    <div className="panel info-panel"><ShieldCheck size={28} /><h3>Medication safety</h3><p>Never start, stop, skip, or change a prescribed medication based on AI-generated content. Consult your prescriber or pharmacist.</p><div className="info-line"><CheckCircle2 size={17} /> Personal organization</div><div className="info-line"><CheckCircle2 size={17} /> Adherence visibility</div><div className="info-line"><CheckCircle2 size={17} /> No automated prescribing</div><p className="fineprint">Schedule times are entered in your local time and stored in UTC by the backend. "Today" follows the UTC calendar day.</p></div>
  </div>;
}

function MedRow({ med, open, toggle, onDone, onError }: { med: Medication; open: boolean; toggle: () => void; onDone: (t: string) => void; onError: (e: unknown) => void }) {
  const [schedule, setSchedule] = useState<MedicationSchedule | null | undefined>(undefined);
  const [adherence, setAdherence] = useState<Record<string, any> | null>(null);
  const [mode, setMode] = useState<'view' | 'edit' | 'schedule'>('view');

  const loadDetail = useCallback(async () => {
    const [s, a] = await Promise.allSettled([getSchedule(med.id), getAdherence(med.id)]);
    setSchedule(s.status === 'fulfilled' ? s.value.schedule : null);
    setAdherence(a.status === 'fulfilled' ? a.value : null);
  }, [med.id]);
  useEffect(() => { if (open) void loadDetail(); else setMode('view'); }, [open, loadDetail]);

  const pct = (k: string) => { const v = adherence?.[k]?.adherence_percentage; return typeof v === 'number' ? `${v}%` : '—'; };

  return <div className={`med-row ${med.is_active ? '' : 'inactive'}`}>
    <div className="med-item">
      <span className="feature-icon purple"><ClipboardList size={18} /></span>
      <div><b>{med.name}</b><small>{med.dosage} · {med.frequency}{med.instructions ? ` · ${med.instructions}` : ''}</small></div>
      {!med.is_active && <Badge value="inactive" tone="muted" />}
      <button className="icon-btn" onClick={toggle} aria-expanded={open} aria-label={`${open ? 'Collapse' : 'Expand'} ${med.name}`}>{open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</button>
    </div>
    {open && <div className="med-detail">
      {schedule === undefined ? <Spinner /> : <>
        <div className="detail-grid">
          <div><span>Schedule</span><b>{describeSchedule(schedule)}</b></div>
          <div><span>Adherence (7 days)</span><b>{pct('last_7_days')}</b></div>
          <div><span>Adherence (30 days)</span><b>{pct('last_30_days')}</b></div>
          <div><span>Overall</span><b>{pct('overall')}</b></div>
        </div>
        {adherence?.overall && <p className="fineprint">Taken {adherence.overall.taken} · Missed {adherence.overall.missed} · Skipped {adherence.overall.skipped} · Unconfirmed {adherence.overall.overdue_unconfirmed}. {adherence.disclaimer}</p>}
      </>}
      {mode === 'edit' && <EditForm med={med} onCancel={() => setMode('view')} onSaved={() => { setMode('view'); onDone(`${med.name} updated.`); }} onError={onError} />}
      {mode === 'schedule' && <ScheduleForm med={med} current={schedule ?? null} onCancel={() => setMode('view')} onSaved={() => { setMode('view'); void loadDetail(); onDone(`Schedule saved for ${med.name}.`); }} onError={onError} />}
      {mode === 'view' && <div className="row-actions">
        {med.is_active && <button className="btn btn-ghost small" onClick={() => setMode('edit')}><Pencil size={14} /> Edit</button>}
        {med.is_active && <button className="btn btn-ghost small" onClick={() => setMode('schedule')}><CalendarClock size={14} /> {schedule ? 'Change schedule' : 'Add schedule'}</button>}
        {med.is_active
          ? <ConfirmButton className="btn btn-danger small" label="Deactivate" confirmLabel="Yes, deactivate" onConfirm={async () => { try { await deactivateMedication(med.id); onDone(`${med.name} deactivated. History is preserved.`); } catch (e) { onError(e); } }} />
          : <button className="btn btn-ghost small" onClick={async () => { try { await updateMedication(med.id, { is_active: true }); onDone(`${med.name} reactivated. Add a new schedule to resume reminders.`); } catch (e) { onError(e); } }}>Reactivate</button>}
      </div>}
    </div>}
  </div>;
}

function EditForm({ med, onCancel, onSaved, onError }: { med: Medication; onCancel: () => void; onSaved: () => void; onError: (e: unknown) => void }) {
  const [f, setF] = useState({ name: med.name, dosage: med.dosage, frequency: med.frequency, instructions: med.instructions ?? '', end_date: med.end_date?.slice(0, 10) ?? '' });
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!f.name.trim() || !f.dosage.trim() || !f.frequency.trim()) { onError(new Error('Name, dosage and frequency are required.')); return; }
    setBusy(true);
    try {
      await updateMedication(med.id, { name: f.name, dosage: f.dosage, frequency: f.frequency, instructions: f.instructions, ...(f.end_date ? { end_date: `${f.end_date}T00:00:00` } : {}) });
      onSaved();
    } catch (err) { onError(err); } finally { setBusy(false); }
  }
  return <form className="form-grid inline-form" onSubmit={save}>
    <label className="field">Name<input required value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></label>
    <label className="field">Dosage<input required value={f.dosage} onChange={e => setF({ ...f, dosage: e.target.value })} /></label>
    <label className="field">Frequency<input required value={f.frequency} onChange={e => setF({ ...f, frequency: e.target.value })} /></label>
    <label className="field">End date<input type="date" value={f.end_date} onChange={e => setF({ ...f, end_date: e.target.value })} /></label>
    <label className="field span-2">Instructions<input value={f.instructions} onChange={e => setF({ ...f, instructions: e.target.value })} /></label>
    <div className="row-actions span-all"><button className="btn btn-primary small" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button><button type="button" className="btn btn-ghost small" onClick={onCancel}>Cancel</button></div>
  </form>;
}

function ScheduleForm({ med, current, onCancel, onSaved, onError }: { med: Medication; current: MedicationSchedule | null; onCancel: () => void; onSaved: () => void; onError: (e: unknown) => void }) {
  const initialLocal = current?.times.map(t => shiftTime(t, tzOffsetMin())) ?? [];
  const [type, setType] = useState<'daily' | 'weekly' | 'as_needed'>(current?.schedule_type ?? 'daily');
  const [times, setTimes] = useState<string[]>(initialLocal.length ? initialLocal.map(l => l.time) : ['09:00']);
  const [days, setDays] = useState<number[]>(current ? shiftWeekdays(current.weekdays, initialLocal[0]?.dayShift ?? 0) : []);
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    const clean = [...new Set(times.filter(Boolean))];
    if (type !== 'as_needed' && clean.length === 0) { onError(new Error('Add at least one dose time.')); return; }
    if (type === 'weekly' && days.length === 0) { onError(new Error('Choose at least one weekday.')); return; }
    const utc = clean.map(t => shiftTime(t, -tzOffsetMin()));
    let weekdays: number[] = [];
    if (type === 'weekly') {
      const shifts = new Set(utc.map(u => u.dayShift));
      if (shifts.size > 1) { onError(new Error('These times fall on different UTC days for the selected weekdays. Create separate medications or use times that stay on the same day.')); return; }
      weekdays = shiftWeekdays(days, utc[0]?.dayShift ?? 0);
    }
    setBusy(true);
    try { await saveSchedule(med.id, { schedule_type: type, times: type === 'as_needed' ? [] : utc.map(u => u.time), weekdays, timezone: 'UTC' }); onSaved(); }
    catch (err) { onError(err); } finally { setBusy(false); }
  }

  return <form className="inline-form" onSubmit={save}>
    <div className="form-grid">
      <label className="field">Schedule type<select value={type} onChange={e => setType(e.target.value as typeof type)}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="as_needed">As needed</option></select></label>
      {type !== 'as_needed' && <div className="field span-2"><span>Dose times (local)</span><div className="chip-row">{times.map((t, i) => <span className="time-chip" key={i}><input type="time" required value={t} aria-label={`Dose time ${i + 1}`} onChange={e => setTimes(v => v.map((x, j) => (j === i ? e.target.value : x)))} />{times.length > 1 && <button type="button" aria-label="Remove time" onClick={() => setTimes(v => v.filter((_, j) => j !== i))}>×</button>}</span>)}<button type="button" className="btn btn-ghost small" onClick={() => setTimes(v => [...v, '21:00'])}><Plus size={13} /> Time</button></div></div>}
    </div>
    {type === 'weekly' && <div className="chip-row" role="group" aria-label="Weekdays">{WEEKDAYS.map((d, i) => <button type="button" key={d} className={`day-chip ${days.includes(i) ? 'on' : ''}`} aria-pressed={days.includes(i)} onClick={() => setDays(v => (v.includes(i) ? v.filter(x => x !== i) : [...v, i].sort()))}>{d}</button>)}</div>}
    <p className="fineprint">Saving replaces the current schedule. Past dose history is preserved.</p>
    <div className="row-actions"><button className="btn btn-primary small" disabled={busy}>{busy ? 'Saving…' : 'Save schedule'}</button><button type="button" className="btn btn-ghost small" onClick={onCancel}>Cancel</button></div>
  </form>;
}

