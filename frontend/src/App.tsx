import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight, Bell, BrainCircuit, ChevronDown, ClipboardList, FileText, HeartPulse, LayoutDashboard, Menu, MessageCircle, RefreshCw, Settings2, ShieldCheck, TrendingUp, UserRound, X,
} from 'lucide-react';
import {
  currentUser, DEMO, DEMO_BANNER_TITLE, demoMetrics, errorMessage, getMetrics, getToken, logout, notificationSummary, onUnauthorized, pivotDaily,
  type Metric, type UserProfile,
} from './api';
import { rangeDays, type Range } from './components/ui';
import AuthScreen from './pages/AuthScreen';
import Overview from './pages/Overview';
import Analytics from './pages/Analytics';
import Assistant from './pages/Assistant';
import Medications from './pages/Medications';
import Agents from './pages/Agents';
import Documents from './pages/Documents';
import Notifications from './pages/Notifications';
import Settings from './pages/Settings';

export type Page = 'Overview' | 'Analytics' | 'AI Assistant' | 'Medications' | 'Agents' | 'Documents' | 'Notifications' | 'Settings';

const nav: [Page, typeof LayoutDashboard][] = [
  ['Overview', LayoutDashboard],
  ['Analytics', TrendingUp],
  ['AI Assistant', MessageCircle],
  ['Medications', ClipboardList],
  ['Agents', BrainCircuit],
  ['Documents', FileText],
  ['Notifications', Bell],
  ['Settings', Settings2],
];

const heading: Record<Page, string> = {
  Overview: 'Your health, at a glance',
  Analytics: 'Health analytics',
  'AI Assistant': 'Medical knowledge assistant',
  Medications: 'Medication tracker',
  Agents: 'AI agent workspace',
  Documents: 'Medical documents',
  Notifications: 'Notifications & monitoring',
  Settings: 'Workspace settings',
};

const subheading: Record<Page, string> = {
  Overview: 'A clearer picture of your health and wellbeing.',
  Analytics: 'Explore measurements, import CSV records, and understand patterns over time.',
  'AI Assistant': 'Ask educational questions. Clinical sources appear when available.',
  Medications: 'Organize medication schedules, daily dose confirmations, and adherence.',
  Agents: 'Coordinate specialized health agents and inspect execution audit history.',
  Documents: 'Upload PDF medical reports and index them for private RAG retrieval.',
  Notifications: 'Review delivered notifications, monitoring events, and reminders.',
  Settings: 'Configure your environment and review data privacy guidance.',
};

const PAGE_PATHS: Record<Page, string> = {
  Overview: '/',
  Analytics: '/analytics',
  'AI Assistant': '/assistant',
  Medications: '/medications',
  Agents: '/agents',
  Documents: '/documents',
  Notifications: '/notifications',
  Settings: '/settings',
};

function pageFromPathname(pathname: string): Page {
  const clean = pathname.replace(/\/+$/, '') || '/';
  const match = (Object.entries(PAGE_PATHS) as [Page, string][]).find(([, p]) => p === clean);
  return match ? match[0] : 'Overview';
}

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean>(DEMO || !!getToken());
  const [user, setUser] = useState<UserProfile | null>(null);
  const [page, setPageState] = useState<Page>(() => pageFromPathname(window.location.pathname));
  const [menu, setMenu] = useState(false);
  const [metrics, setMetrics] = useState<Metric[]>(DEMO ? demoMetrics : []);
  const [loading, setLoading] = useState(!DEMO);
  const [error, setError] = useState('');
  const [range, setRange] = useState<Range>('14 days');
  const [unreadCount, setUnreadCount] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const setPage = useCallback((next: Page) => {
    setPageState(next);
    const targetPath = PAGE_PATHS[next] || '/';
    if (window.location.pathname !== targetPath) {
      window.history.replaceState(null, '', targetPath);
    }
  }, []);

  useEffect(() => {
    document.title = DEMO ? DEMO_BANNER_TITLE : 'HealthGuard AI | Health Intelligence';
  }, []);

  const handleSignOut = useCallback(() => {
    logout();
    setAuthenticated(false);
    setUser(null);
    setMetrics([]);
    setUnreadCount(0);
  }, []);

  useEffect(() => onUnauthorized(handleSignOut), [handleSignOut]);

  const refresh = useCallback(async (u?: UserProfile | null) => {
    if (DEMO) return;
    const activeUser = u ?? user;
    if (!activeUser) return;
    setLoading(true); setError('');
    try {
      const [raw, notif] = await Promise.all([
        getMetrics(activeUser.id, { limit: 500 }),
        notificationSummary(activeUser.id).catch(() => ({ unread: 0, total_notifications: 0, acknowledged: 0 })),
      ]);
      setMetrics(pivotDaily(raw));
      setUnreadCount(notif.unread);
      setRefreshKey(k => k + 1);
    } catch (e) {
      setError(errorMessage(e, 'Could not load health metrics'));
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!DEMO && authenticated && !user) {
      setLoading(true);
      currentUser()
        .then(u => { setUser(u); return refresh(u); })
        .catch(() => handleSignOut());
    }
  }, [authenticated, user, refresh, handleSignOut]);

  const chartData = useMemo(() => {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - rangeDays(range));
    const cutoffIso = cutoff.toISOString().slice(0, 10);
    const filtered = metrics.filter(m => m.date >= cutoffIso);
    const source = filtered.length ? filtered : metrics.slice(-rangeDays(range));
    return source.map(m => ({
      ...m,
      label: new Date(m.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    }));
  }, [metrics, range]);

  if (!authenticated) {
    return <AuthScreen onAuthenticated={u => { setUser(u); setAuthenticated(true); void refresh(u); }} />;
  }

  return (
    <div className="shell">
      <aside className={`sidebar ${menu ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-icon">
            <img src="/healthguard-logo.png" alt="" onError={e => { e.currentTarget.style.display = 'none'; }} />
            <HeartPulse size={24} />
          </div>
          <div>
            <strong>HealthGuard <span>AI</span></strong>
            <small>INTELLIGENT HEALTHCARE</small>
          </div>
          <button className="mobile-close" onClick={() => setMenu(false)} aria-label="Close menu"><X size={19} /></button>
        </div>
        <div className="side-caption">WORKSPACE</div>
        <nav>
          {nav.map(([name, Icon]) => (
            <button key={name} className={`nav-item ${page === name ? 'selected' : ''}`} onClick={() => { setPage(name); setMenu(false); }}>
              <Icon size={19} />
              <span>{name}</span>
              {name === 'Notifications' && unreadCount > 0 && <span className="nav-count">{unreadCount}</span>}
              {page === name && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card">
            <ShieldCheck size={21} />
            <strong>{DEMO ? 'Educational Demo Mode' : 'Privacy-conscious design'}</strong>
            <p>{DEMO ? 'All measurements and medications shown are synthetic. Never rely on AI for medical decisions.' : 'Local AI available with Ollama. Never rely on AI for urgent medical decisions.'}</p>
          </div>
          <button type="button" className="side-user as-button" onClick={() => setPage('Settings')}>
            <div className="avatar"><UserRound size={20} /></div>
            <div>
              <b>{user?.full_name || (DEMO ? 'Synthetic Demo Visitor' : 'HealthGuard workspace')}</b>
              <small>{DEMO ? 'No login required · Synthetic data' : user?.email || 'Connected environment'}</small>
            </div>
            <ChevronDown size={16} />
          </button>
        </div>
      </aside>

      <div className="main-wrap">
        <header className="topbar">
          <div className="top-left">
            <button className="hamburger" onClick={() => setMenu(true)} aria-label="Open menu"><Menu size={22} /></button>
            <span>Workspace</span>
            <ArrowRight size={14} />
            <b>{page}</b>
          </div>
          <div className="top-actions">
            <span className={`mode-badge ${DEMO ? 'demo' : ''}`}>
              <span className="status-dot" />
              {DEMO ? 'EDUCATIONAL DEMO' : 'LIVE API'}
            </span>
            <button className="icon-btn bell-btn" aria-label="Notifications" onClick={() => setPage('Notifications')}>
              <Bell size={19} />
              {unreadCount > 0 && <span className="bell-dot">{unreadCount > 9 ? '9+' : unreadCount}</span>}
            </button>
            <button type="button" className="avatar small as-button" aria-label="Account settings" onClick={() => setPage('Settings')}>
              <UserRound size={18} />
            </button>
          </div>
        </header>

        <main className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">HEALTH INTELLIGENCE PLATFORM</div>
              <h1>{heading[page]}</h1>
              <p>{subheading[page]}</p>
            </div>
            <div className="heading-actions">
              {!DEMO && (page === 'Overview' || page === 'Analytics') && (
                <button className="outline-btn" onClick={() => void refresh()} disabled={loading}>
                  <RefreshCw size={16} />
                  {loading ? 'Loading' : 'Refresh data'}
                </button>
              )}
            </div>
          </div>

          {DEMO && (
            <div className="notice">
              <ShieldCheck size={17} />
              <span><b>{DEMO_BANNER_TITLE}.</b> Displayed measurements and medications are synthetic for evaluation. No real patient records are loaded; features requiring the full FastAPI backend are marked unavailable.</span>
            </div>
          )}

          {error && (
            <div className="error">
              <b>Backend connection:</b> {error} <button onClick={() => void refresh()}>Retry</button>
            </div>
          )}

          {page === 'Overview' && (
            <Overview user={user} metrics={metrics} chartData={chartData} range={range} setRange={setRange} setPage={setPage} refreshKey={refreshKey} />
          )}
          {page === 'Analytics' && (
            <Analytics user={user} metrics={metrics} chartData={chartData} range={range} setRange={setRange} onChanged={() => void refresh()} />
          )}
          {page === 'AI Assistant' && <Assistant user={user} demo={DEMO} />}
          {page === 'Medications' && <Medications user={user} onChanged={() => void refresh()} />}
          {page === 'Agents' && <Agents user={user} />}
          {page === 'Documents' && <Documents user={user} />}
          {page === 'Notifications' && <Notifications user={user} onChanged={() => void refresh()} />}
          {page === 'Settings' && <Settings user={user} onSignOut={handleSignOut} />}

          <footer className="footer">
            <span>© HealthGuard AI · Health intelligence, responsibly designed</span>
            <span>Educational software · Not medical advice</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
