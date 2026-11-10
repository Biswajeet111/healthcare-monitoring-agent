import { useCallback, useEffect, useState } from 'react';
import { Activity, Bell, CheckCircle2, Clock, RefreshCw } from 'lucide-react';
import {
  acknowledgeEvent, acknowledgeReminder, errorMessage, fmtDateTime, humanize, listMonitoringEvents, listNotifications, listReminders, notificationSummary,
  type MonitoringEvent, type Reminder, type UserProfile,
} from '../api';
import { Alert, Badge, Empty, Spinner } from '../components/ui';

export default function Notifications({ user, onChanged }: { user: UserProfile | null; onChanged: () => void }) {
  const [notifications, setNotifications] = useState<MonitoringEvent[] | null>(null);
  const [events, setEvents] = useState<MonitoringEvent[] | null>(null);
  const [reminders, setReminders] = useState<Reminder[] | null>(null);
  const [summary, setSummary] = useState<{ total_notifications: number; unread: number; acknowledged: number } | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return;
    const [n, e, r, s] = await Promise.allSettled([
      listNotifications(user.id, unreadOnly),
      listMonitoringEvents(user.id),
      listReminders(),
      notificationSummary(user.id),
    ]);
    if (n.status === 'fulfilled') setNotifications(n.value.notifications); else { setNotifications([]); setMsg({ kind: 'error', text: errorMessage(n.reason) }); }
    if (e.status === 'fulfilled') setEvents(e.value.events); else setEvents([]);
    if (r.status === 'fulfilled') setReminders(r.value.reminders); else setReminders([]);
    if (s.status === 'fulfilled') setSummary(s.value);
  }, [user, unreadOnly]);
  useEffect(() => { void load(); }, [load]);

  async function ackEvent(eventId: number) {
    if (!user) return;
    setBusyId(`ev-${eventId}`); setMsg(null);
    try {
      await acknowledgeEvent(user.id, eventId);
      setMsg({ kind: 'success', text: 'Monitoring event acknowledged.' });
      await load();
      onChanged();
    } catch (e) { setMsg({ kind: 'error', text: errorMessage(e) }); }
    finally { setBusyId(null); }
  }

  async function ackReminder(reminderId: number) {
    setBusyId(`rem-${reminderId}`); setMsg(null);
    try {
      await acknowledgeReminder(reminderId);
      setMsg({ kind: 'success', text: 'Medication reminder acknowledged.' });
      await load();
      onChanged();
    } catch (e) { setMsg({ kind: 'error', text: errorMessage(e) }); }
    finally { setBusyId(null); }
  }

  if (!user) return <Alert kind="info">Sign in to the live backend to view notifications and monitoring events.</Alert>;

  return <div className="stack">
    {msg && <Alert kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Alert>}
    {summary && <div className="stats-grid">
      <div className="stat-card"><div className="stat-top"><span>Unread notifications</span><span className="stat-icon pink"><Bell size={20} /></span></div><div className="stat-value">{summary.unread}</div><div className="stat-note"><span className="mini-dot" />Requires review</div></div>
      <div className="stat-card"><div className="stat-top"><span>Acknowledged</span><span className="stat-icon green"><CheckCircle2 size={20} /></span></div><div className="stat-value">{summary.acknowledged}</div><div className="stat-note"><span className="mini-dot" />Reviewed notifications</div></div>
      <div className="stat-card"><div className="stat-top"><span>Monitoring events</span><span className="stat-icon blue"><Activity size={20} /></span></div><div className="stat-value">{events?.length ?? '—'}</div><div className="stat-note"><span className="mini-dot" />Rule-based detections</div></div>
      <div className="stat-card"><div className="stat-top"><span>Medication reminders</span><span className="stat-icon purple"><Clock size={20} /></span></div><div className="stat-value">{reminders?.filter(r => r.status === 'pending').length ?? '—'}</div><div className="stat-note"><span className="mini-dot" />Pending reminders</div></div>
    </div>}

    <div className="two-cols">
      <div className="panel">
        <div className="panel-heading"><div><h3>Delivered notifications</h3><p>Published alerts from your health monitoring pipeline</p></div>
          <div className="row-actions">
            <label className="check-line"><input type="checkbox" checked={unreadOnly} onChange={e => setUnreadOnly(e.target.checked)} /> Unread only</label>
            <button type="button" className="icon-btn" onClick={() => void load()} aria-label="Refresh notifications"><RefreshCw size={16} /></button>
          </div>
        </div>
        {notifications === null ? <Spinner /> : notifications.length === 0 ? <Empty>No notifications to display.</Empty> : <div className="list">
          {notifications.map(n => <div className="list-row" key={n.id}>
            <Badge value={n.event_level} />
            <div>
              <b>{humanize(n.metric_type)} · {humanize(n.event_type)}</b>
              <small>{n.message}</small>
              <small className="muted">{fmtDateTime(n.created_at)}{n.acknowledged_at ? ` · Acknowledged ${fmtDateTime(n.acknowledged_at)}` : ''}</small>
            </div>
            {n.is_acknowledged ? <Badge value="acknowledged" /> : <button type="button" className="btn btn-primary small" disabled={busyId === `ev-${n.id}`} onClick={() => void ackEvent(n.id)}>{busyId === `ev-${n.id}` ? 'Saving…' : 'Acknowledge'}</button>}
          </div>)}
        </div>}
      </div>

      <div className="panel">
        <div className="panel-heading"><div><h3>Medication reminders</h3><p>Generated for overdue or upcoming scheduled doses</p></div></div>
        {reminders === null ? <Spinner /> : reminders.length === 0 ? <Empty>No medication reminders.</Empty> : <div className="list">
          {reminders.map(r => <div className="list-row" key={r.id}>
            <Badge value={r.status} />
            <div>
              <b>{r.message}</b>
              <small className="muted">{fmtDateTime(r.created_at)}{r.acknowledged_at ? ` · Acknowledged ${fmtDateTime(r.acknowledged_at)}` : ''}</small>
            </div>
            {r.status === 'pending' && <button type="button" className="btn btn-primary small" disabled={busyId === `rem-${r.id}`} onClick={() => void ackReminder(r.id)}>{busyId === `rem-${r.id}` ? 'Saving…' : 'Acknowledge'}</button>}
          </div>)}
        </div>}
      </div>
    </div>

    <div className="panel">
      <div className="panel-heading"><div><h3>All monitoring events</h3><p>Complete log of rule-based physiological threshold and trend detections</p></div></div>
      {events === null ? <Spinner /> : events.length === 0 ? <Empty>No monitoring events recorded yet.</Empty> : <div className="table-scroll">
        <table>
          <thead><tr><th>Time</th><th>Metric</th><th>Type</th><th>Level</th><th>Message</th><th>Status</th></tr></thead>
          <tbody>{events.map(ev => <tr key={ev.id}>
            <td>{fmtDateTime(ev.created_at)}</td>
            <td>{humanize(ev.metric_type)}</td>
            <td>{humanize(ev.event_type)}</td>
            <td><Badge value={ev.event_level} /></td>
            <td>{ev.message}</td>
            <td>{ev.is_acknowledged ? <Badge value="acknowledged" /> : <button type="button" className="btn btn-ghost small" disabled={busyId === `ev-${ev.id}`} onClick={() => void ackEvent(ev.id)}>Acknowledge</button>}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>
  </div>;
}

