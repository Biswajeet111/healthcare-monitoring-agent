import { useState, type ReactNode } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react';
import type { Heart } from 'lucide-react';
import type { Metric } from '../api';

export function Stat({ label, value, unit, icon: Icon, color, note }: { label: string; value: string | number | undefined; unit: string; icon: typeof Heart; color: string; note: string }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><span className={`stat-icon ${color}`}><Icon size={20} /></span></div><div className="stat-value">{value ?? '—'} <small>{unit}</small></div><div className="stat-note"><span className="mini-dot" />{note}</div></div>;
}

export const RANGES = ['7 days', '14 days', '30 days', '90 days'] as const;
export type Range = typeof RANGES[number];
export const rangeDays = (r: Range) => parseInt(r, 10);

export function ChartCard({ title, subtitle, data, dataKey, color, range, setRange }: { title: string; subtitle: string; data: (Metric & { label?: string })[]; dataKey: keyof Metric; color: string; range: Range; setRange: (s: Range) => void }) {
  const points = data.filter(d => Number.isFinite(d[dataKey] as number));
  return <div className="panel chart-panel"><div className="panel-heading"><div><h3>{title}</h3><p>{subtitle}</p></div><select aria-label={`${title} time range`} value={range} onChange={e => setRange(e.target.value as Range)}>{RANGES.map(r => <option key={r}>{r}</option>)}</select></div>
    <div className="chart-area">{points.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={points} margin={{ top: 14, right: 10, left: -28, bottom: 0 }}><defs><linearGradient id={`fill-${dataKey}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.22} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#e9edf4" vertical={false} strokeDasharray="4 5" /><XAxis dataKey="label" tick={{ fontSize: 11, fill: '#9ba4b4' }} tickLine={false} axisLine={false} interval="preserveStartEnd" /><YAxis tick={{ fontSize: 11, fill: '#9ba4b4' }} tickLine={false} axisLine={false} domain={['auto', 'auto']} /><Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e9edf4', boxShadow: '0 12px 30px #17263b18' }} /><Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2.5} fill={`url(#fill-${dataKey})`} activeDot={{ r: 5 }} /></AreaChart></ResponsiveContainer> : <div className="empty-chart">No measurements in this period</div>}</div></div>;
}

const levelTone: Record<string, string> = {
  // event levels / statuses → badge tone
  critical: 'danger', urgent: 'danger', urgent_review: 'danger', high: 'danger', escalated: 'danger', failed: 'danger', error: 'danger', missed: 'danger', overdue: 'danger',
  warning: 'warn', moderate: 'warn', deviation: 'warn', degraded: 'warn', pending: 'warn', skipped: 'warn', in_progress: 'warn', not_indexed: 'warn', insufficient_data: 'muted',
  info: 'info', routine: 'info', scheduled: 'info', upcoming: 'info',
  low: 'ok', normal: 'ok', completed: 'ok', success: 'ok', taken: 'ok', indexed: 'ok', acknowledged: 'ok', delivered: 'ok', ready: 'ok',
};
export function Badge({ value, tone }: { value: string; tone?: string }) {
  const t = tone ?? levelTone[value?.toLowerCase()] ?? 'muted';
  return <span className={`badge badge-${t}`}>{(value ?? '').replace(/_/g, ' ')}</span>;
}

export function Alert({ kind = 'error', children, onClose }: { kind?: 'error' | 'success' | 'info' | 'warn'; children: ReactNode; onClose?: () => void }) {
  const Icon = kind === 'success' ? CheckCircle2 : kind === 'info' ? Info : AlertTriangle;
  return <div className={`alert alert-${kind}`} role={kind === 'error' ? 'alert' : 'status'}><Icon size={17} /><span>{children}</span>{onClose && <button type="button" onClick={onClose} aria-label="Dismiss"><X size={15} /></button>}</div>;
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return <div className="loading-row" role="status"><Loader2 size={17} className="spin" />{label}</div>;
}

export function Empty({ children }: { children: ReactNode }) { return <div className="empty-state">{children}</div>; }

/** Two-step destructive button: first click asks for confirmation inline. */
export function ConfirmButton({ label, confirmLabel = 'Confirm', onConfirm, disabled, className = 'btn btn-danger' }: { label: ReactNode; confirmLabel?: string; onConfirm: () => void | Promise<void>; disabled?: boolean; className?: string }) {
  const [asking, setAsking] = useState(false);
  if (!asking) return <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>{label}</button>;
  return <span className="confirm-group"><button type="button" className="btn btn-danger" disabled={disabled} onClick={async () => { setAsking(false); await onConfirm(); }}>{confirmLabel}</button><button type="button" className="btn btn-ghost" onClick={() => setAsking(false)}>Cancel</button></span>;
}

