/**
 * HealthGuard AI — typed API client.
 *
 * Every function here maps 1:1 to a FastAPI route verified in the backend source
 * (healthguard/main.py and healthguard/api/*.py). The JWT is kept in
 * sessionStorage (cleared when the tab closes) and attached as a Bearer token.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export const DEMO = import.meta.env.VITE_DEMO_MODE === 'true';
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const TOKEN_KEY = 'healthguard_token';

export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
const setToken = (t: string) => sessionStorage.setItem(TOKEN_KEY, t);
export function logout() { sessionStorage.removeItem(TOKEN_KEY); }

/** Error carrying the HTTP status so callers can react (e.g. 401 → sign out). */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = 'ApiError'; }
}

/** Listeners notified when the backend rejects the token (401). */
const unauthorizedListeners = new Set<() => void>();
export function onUnauthorized(fn: () => void) { unauthorizedListeners.add(fn); return () => { unauthorizedListeners.delete(fn); }; }

function formatDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors: [{loc:[...], msg:'...'}]
    return detail.map(d => {
      if (d && typeof d === 'object') {
        const r = d as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(r.loc) ? r.loc.filter(x => x !== 'body').join('.') : '';
        return field ? `${field}: ${r.msg}` : r.msg;
      }
      return String(d);
    }).join('; ');
  }
  return null;
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query) {
  const url = new URL(API_BASE + path);
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  return url.toString();
}

export async function request<T>(
  path: string,
  opts: { method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'; body?: unknown; query?: Query; form?: FormData; auth?: boolean } = {},
): Promise<T> {
  const { method = 'GET', body, query, form, auth = true } = opts;
  const headers: Record<string, string> = {};
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined && !form) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, `Cannot reach the HealthGuard API at ${API_BASE}. Is the backend running?`);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message = formatDetail((data as { detail?: unknown }).detail) ?? message;
    } catch { /* non-JSON error body */ }
    if (response.status === 401 && auth) {
      logout();
      unauthorizedListeners.forEach(fn => fn());
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const errorMessage = (e: unknown, fallback = 'Something went wrong') => (e instanceof Error ? e.message : fallback);

// ---------------------------------------------------------------------------
// Authentication  (/auth/*)
// ---------------------------------------------------------------------------

export type UserProfile = { id: number; full_name: string; email: string | null; created_at: string };

export async function login(email: string, password: string): Promise<UserProfile> {
  const data = await request<{ access_token: string; token_type: string }>('/auth/login', {
    method: 'POST', auth: false, body: { email: email.trim(), password },
  });
  if (!data?.access_token) throw new Error('Login response did not contain an access token.');
  setToken(data.access_token);
  return currentUser();
}

export const register = (full_name: string, email: string, password: string) =>
  request<UserProfile>('/auth/register', { method: 'POST', auth: false, body: { full_name: full_name.trim(), email: email.trim(), password } });

export const currentUser = () => request<UserProfile>('/auth/me');

// ---------------------------------------------------------------------------
// Health metrics
// ---------------------------------------------------------------------------

export const METRIC_TYPES = {
  heart_rate: { label: 'Heart rate', units: ['bpm'] },
  blood_glucose: { label: 'Blood glucose', units: ['mg/dL', 'mmol/L'] },
  steps: { label: 'Steps', units: ['steps'] },
  weight: { label: 'Weight', units: ['kg'] },
  height: { label: 'Height', units: ['cm'] },
  sleep_duration: { label: 'Sleep duration', units: ['hours'] },
  blood_pressure_systolic: { label: 'Systolic BP', units: ['mmHg'] },
  blood_pressure_diastolic: { label: 'Diastolic BP', units: ['mmHg'] },
} as const;
export type MetricType = keyof typeof METRIC_TYPES;

export type HealthMetric = {
  id: number; user_id: number; metric_type: string; value: number; unit: string; recorded_at: string;
  source: string; context: string | null; measurement_group_id: string | null; notes: string | null;
  original_value?: number | null; original_unit?: string | null;
};

/** Daily pivot used by the dashboard charts. */
export type Metric = { id: string; date: string; heartRate: number; glucose: number; systolic: number; diastolic: number; steps: number };

export const getMetrics = (userId: number, q: { metric_type?: string; start_date?: string; end_date?: string; limit?: number } = {}) =>
  request<HealthMetric[]>(`/users/${userId}/metrics`, { query: { limit: 500, ...q } });

/** Pivot raw readings (returned newest-first) into one row per day, keeping the latest reading of each type. */
export function pivotDaily(raw: HealthMetric[]): Metric[] {
  const days = new Map<string, Metric>();
  const seen = new Set<string>();
  for (const r of raw) {
    const date = String(r.recorded_at ?? '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(r.value)) continue;
    const key = `${date}|${r.metric_type}`;
    if (seen.has(key)) continue; // newest-first: first hit is the latest reading of the day
    seen.add(key);
    const m = days.get(date) ?? { id: date, date, heartRate: NaN, glucose: NaN, systolic: NaN, diastolic: NaN, steps: NaN };
    switch (r.metric_type) {
      case 'heart_rate': m.heartRate = r.value; break;
      case 'blood_glucose': m.glucose = r.value; break;
      case 'blood_pressure_systolic': m.systolic = r.value; break;
      case 'blood_pressure_diastolic': m.diastolic = r.value; break;
      case 'steps': m.steps = r.value; break;
    }
    days.set(date, m);
  }
  return [...days.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export const createMetric = (userId: number, m: { metric_type: MetricType; value: number; unit: string; context?: string; notes?: string }) =>
  request<HealthMetric>('/metrics', { method: 'POST', query: { user_id: userId }, body: { source: 'manual', ...m } });

export const createBloodPressure = (userId: number, r: { systolic: number; diastolic: number; context?: string; notes?: string }) =>
  request<{ message: string; measurement_group_id: string }>(`/users/${userId}/metrics/blood-pressure`, { method: 'POST', body: { unit: 'mmHg', source: 'manual', ...r } });

export type CsvImportResult = { message: string; imported_count: number; failed_count: number; import_hash: string; errors: unknown[] };
export function importCsv(file: File) {
  const form = new FormData(); form.append('file', file);
  return request<CsvImportResult>('/metrics/import-csv', { method: 'POST', form });
}

export const getMetricSummary = (userId: number) => request<Record<string, unknown>>(`/users/${userId}/metrics/summary`);

// ---------------------------------------------------------------------------
// Medications  (/medications/*, /users/{id}/medications)
// ---------------------------------------------------------------------------

export type Medication = {
  id: number; name: string; dosage: string; frequency: string; instructions: string | null;
  start_date: string; end_date: string | null; is_active: boolean; created_at: string;
};
export type MedicationSchedule = { id: number; schedule_type: 'daily' | 'weekly' | 'as_needed'; times: string[]; weekdays: number[]; timezone: string; effective_from: string };
export type TodayDose = { occurrence_id: number; medication_id: number; medication_name: string; scheduled_at: string; status: string; taken_at: string | null; notes: string | null };

export const listMedications = (userId: number, includeInactive = false) =>
  request<Medication[]>(`/medications/user/${userId}/all`, { query: { include_inactive: includeInactive } });

export const createMedication = (userId: number, m: { name: string; dosage: string; frequency: string; instructions?: string | null; start_date: string; end_date?: string | null }) =>
  request<Medication>('/medications', { method: 'POST', query: { user_id: userId }, body: m });

export const updateMedication = (id: number, m: Partial<{ name: string; dosage: string; frequency: string; instructions: string; end_date: string; is_active: boolean }>) =>
  request<{ message: string }>(`/medications/${id}`, { method: 'PATCH', body: m });

export const deactivateMedication = (id: number) => request<{ message: string }>(`/medications/${id}/deactivate`, { method: 'DELETE' });

export const getSchedule = (id: number) => request<{ medication_id: number; schedule: MedicationSchedule | null }>(`/medications/${id}/schedule`);

export const saveSchedule = (id: number, s: { schedule_type: 'daily' | 'weekly' | 'as_needed'; times: string[]; weekdays: number[]; timezone: string }) =>
  request<{ message: string }>(`/medications/${id}/schedule`, { method: 'POST', body: s });

export const getTodayDoses = (userId: number) => request<{ date: string; doses: TodayDose[]; total: number }>(`/medications/user/${userId}/today`);

export const confirmDose = (occurrenceId: number, status: 'taken' | 'skipped' | 'missed', notes?: string) =>
  request<{ occurrence_id: number; status: string }>(`/medications/occurrences/${occurrenceId}`, { method: 'PATCH', body: { status, notes: notes ?? null } });

export const getAdherence = (id: number) => request<Record<string, unknown>>(`/medications/${id}/adherence-v2`);

// ---------------------------------------------------------------------------
// Medical RAG  (/rag/*)
// ---------------------------------------------------------------------------

export type RagSource = { reference_number: number; document_title: string; source_organization: string; source_url: string; chunk_id: string; relevance_distance: number };
export type RagAnswer = { answer: string | null; sources: RagSource[]; limitations: string[]; disclaimer: string; model_used?: string; error?: string };
export type RagStatus = { ollama_available: boolean; available_models: string[]; embedding_model_available: boolean; ready_for_qa: boolean; limitation: string };

export const ragStatus = () => request<RagStatus>('/rag/status');

export const askAssistant = (question: string, opts: { include_user_documents?: boolean; include_global_knowledge?: boolean; document_id?: number | null } = {}) =>
  request<RagAnswer>('/rag/ask', {
    method: 'POST',
    body: { question, include_global_knowledge: opts.include_global_knowledge ?? true, include_user_documents: opts.include_user_documents ?? true, document_id: opts.document_id ?? null, n_results: 5 },
  });

// ---------------------------------------------------------------------------
// Medical documents  (/documents/*, /rag/documents/*)
// ---------------------------------------------------------------------------

export type MedicalDocument = {
  id: number; filename: string; content_type: string; file_size: number; uploaded_at: string;
  has_extracted_text: boolean; extracted_text?: string | null; index_status: string; chunk_count: number | null; indexed_at: string | null;
};

const uploadedFileCache = new Map<number, Blob>();

export const listDocuments = () => request<{ total: number; documents: MedicalDocument[] }>('/rag/documents');

export async function uploadDocument(file: File) {
  const form = new FormData(); form.append('file', file);
  const res = await request<{ id: number; filename: string }>('/documents/upload', { method: 'POST', form });
  uploadedFileCache.set(res.id, new Blob([file], { type: 'application/pdf' }));
  return res;
}

export const indexDocument = (id: number) => request<Record<string, unknown>>(`/rag/documents/${id}/index`, { method: 'POST' });
export const deleteDocument = (id: number) => {
  uploadedFileCache.delete(id);
  return request<{ message: string }>(`/documents/${id}`, { method: 'DELETE' });
};

function buildClientPdfBlob(title: string, bodyText: string): Blob {
  const esc = (s: string) =>
    s
      .replace(/[^\x20-\x7E]/g, ' ')
      .replace(/\\/g, '\\\\')
      .replace(/\(/g, '\\(')
      .replace(/\)/g, '\\)');

  const rawLines = [
    `HealthGuard AI — Medical Document Viewer`,
    `File: ${title}`,
    '-'.repeat(76),
    ...bodyText.split(/\r?\n/),
  ];
  const wrapped: string[] = [];
  for (const line of rawLines) {
    if (!line) {
      wrapped.push('');
      continue;
    }
    let rem = line;
    while (rem.length > 88) {
      wrapped.push(rem.slice(0, 88));
      rem = rem.slice(88);
    }
    wrapped.push(rem);
  }

  const lines = wrapped.slice(0, 48);
  const ops = ['BT', '/F1 10 Tf', '45 755 Td', '14 TL'];
  lines.forEach((ln, idx) => {
    ops.push(idx === 0 ? `(${esc(ln)}) Tj` : `T* (${esc(ln)}) Tj`);
  });
  ops.push('ET');
  const stream = ops.join('\n');

  const objs = [
    `1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n`,
    `2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n`,
    `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n`,
    `4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n`,
    `5 0 obj\n<< /Length ${stream.length} >>\nstream\n${stream}\nendstream\nendobj\n`,
  ];

  let pdf = '%PDF-1.4\n';
  const offsets: number[] = [];
  for (const obj of objs) {
    offsets.push(pdf.length);
    pdf += obj;
  }
  const xrefPos = pdf.length;
  pdf += `xref\n0 ${objs.length + 1}\n`;
  pdf += '0000000000 65535 f \n';
  for (const off of offsets) {
    pdf += `${String(off).padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF\n`;
  return new Blob([pdf], { type: 'application/pdf' });
}

function presentPdfBlob(pdfBlob: Blob, filename: string, popupWin: Window | null): void {
  const blobUrl = URL.createObjectURL(pdfBlob);
  if (popupWin && !popupWin.closed) {
    popupWin.location.href = blobUrl;
  } else {
    const win = window.open(blobUrl, '_blank');
    if (!win) {
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  }
  setTimeout(() => URL.revokeObjectURL(blobUrl), 120_000);
}

export async function openDocumentFile(doc: MedicalDocument | number, filenameArg?: string): Promise<void> {
  const id = typeof doc === 'number' ? doc : doc.id;
  const filename = (typeof doc === 'number' ? filenameArg : doc.filename) || `document_${id}.pdf`;
  const extractedText = typeof doc === 'number' ? null : doc.extracted_text;

  // Open blank tab synchronously during user click gesture to prevent popup blocking
  const popupWin = window.open('', '_blank');

  const cached = uploadedFileCache.get(id);
  if (cached) {
    presentPdfBlob(cached, filename, popupWin);
    return;
  }

  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  for (const route of [`/documents/${id}/file`, `/rag/documents/${id}/file`]) {
    try {
      const response = await fetch(buildUrl(route), { method: 'GET', headers });
      if (response.status === 401) {
        if (popupWin && !popupWin.closed) popupWin.close();
        logout();
        unauthorizedListeners.forEach(fn => fn());
        throw new ApiError(401, 'Session expired. Please sign in again.');
      }
      if (response.ok) {
        const blob = await response.blob();
        const pdfBlob = new Blob([blob], { type: 'application/pdf' });
        uploadedFileCache.set(id, pdfBlob);
        presentPdfBlob(pdfBlob, filename, popupWin);
        return;
      }
      if (response.status !== 404) {
        const raw = await response.text();
        let parsed: unknown = null;
        if (raw) { try { parsed = JSON.parse(raw); } catch { parsed = raw; } }
        const detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? formatDetail((parsed as { detail: unknown }).detail) : null;
        if (popupWin && !popupWin.closed) popupWin.close();
        throw new ApiError(response.status, detail || `Could not open document (${response.status})`);
      }
    } catch (e) {
      if (e instanceof ApiError) throw e;
    }
  }

  // Fallback when running against a backend server that has not yet reloaded the /file endpoint:
  // Reconstruct a viewable PDF from extracted_text or indexed RAG chunks for this document.
  let fallbackText = extractedText || '';
  if (!fallbackText) {
    try {
      const searchTerms = filename.replace(/\.pdf$/i, '').replace(/[_\-.]+/g, ' ').trim() || 'medical report laboratory';
      const searchRes = await request<{
        results: {
          text?: string;
          excerpt?: string;
          metadata?: { document_id?: number | string; filename?: string; chunk_index?: number };
        }[];
      }>('/rag/search', {
        query: { query: `${searchTerms} clinical laboratory report patient`, source: 'user', n_results: 20 },
      });
      const allResults = searchRes.results || [];
      const matchingChunks = allResults.filter(r => {
        const metaDocId = r.metadata?.document_id !== undefined ? Number(r.metadata.document_id) : undefined;
        return metaDocId === id || r.metadata?.filename === filename;
      });
      const chunksToUse = (matchingChunks.length > 0 ? matchingChunks : allResults).slice().sort(
        (a, b) => Number(a.metadata?.chunk_index ?? 0) - Number(b.metadata?.chunk_index ?? 0),
      );
      fallbackText = chunksToUse.map(c => c.text || c.excerpt || '').filter(Boolean).join('\n\n');
    } catch {
      // Ignore search fallback error
    }
  }

  if (!fallbackText && typeof doc !== 'number') {
    fallbackText = [
      `Document ID: ${doc.id}`,
      `Filename: ${doc.filename}`,
      `Content Type: ${doc.content_type}`,
      `Size: ${doc.file_size} bytes`,
      `Uploaded At: ${doc.uploaded_at}`,
      `RAG Index Status: ${doc.index_status}${doc.chunk_count != null ? ` (${doc.chunk_count} chunks)` : ''}`,
      '',
      'Note: Restart the FastAPI backend server (uvicorn) so the newly added',
      'GET /documents/{id}/file endpoint streams the original stored PDF binary.',
    ].join('\n');
  }

  if (fallbackText) {
    const pdfBlob = buildClientPdfBlob(filename, fallbackText);
    presentPdfBlob(pdfBlob, filename, popupWin);
    return;
  }

  if (popupWin && !popupWin.closed) popupWin.close();
  throw new ApiError(
    404,
    'Document file route not active yet. Please restart the FastAPI backend (uvicorn) to stream stored PDF files directly.',
  );
}

// ---------------------------------------------------------------------------
// Notifications & monitoring events
// ---------------------------------------------------------------------------

export type MonitoringEvent = {
  id: number; user_id: number; metric_type: string; unit: string | null; event_type: string; event_level: string;
  monitoring_priority: string | null; statistical_status?: string | null; message: string; notification_status: string;
  is_acknowledged: boolean; created_at: string; notified_at: string | null; acknowledged_at: string | null; disclaimer?: string;
};

export const listNotifications = (userId: number, unreadOnly = false) =>
  request<{ total: number; notifications: MonitoringEvent[] }>(`/users/${userId}/notifications`, { query: { limit: 100, unread_only: unreadOnly } });

export const notificationSummary = (userId: number) =>
  request<{ total_notifications: number; unread: number; acknowledged: number }>(`/users/${userId}/notifications/summary`);

export const listMonitoringEvents = (userId: number) =>
  request<{ total: number; events: MonitoringEvent[] }>(`/users/${userId}/monitoring/events`, { query: { limit: 100 } });

export const acknowledgeEvent = (userId: number, eventId: number) =>
  request<{ message: string; event: MonitoringEvent }>(`/users/${userId}/monitoring/events/${eventId}/acknowledge`, { method: 'PATCH' });

export type Reminder = { id: number; medication_id: number; occurrence_id: number | null; message: string; status: string; created_at: string; acknowledged_at: string | null };
export const listReminders = (status?: 'pending' | 'acknowledged' | 'dismissed') =>
  request<{ reminders: Reminder[]; total: number }>('/reminders/medications', { query: { status, limit: 50 } });
export const acknowledgeReminder = (id: number) => request<{ reminder_id: number; status: string }>(`/reminders/medications/${id}/acknowledge`, { method: 'PATCH' });

// ---------------------------------------------------------------------------
// Agentic orchestration  (/orchestration/*)
// ---------------------------------------------------------------------------

export type ExecutionStep = {
  agent_name: string; started_at: string; completed_at: string; duration_ms: number; status: string; details?: string | null;
  step_order?: number | null; tool_name?: string | null; selection_reason?: string | null;
  intermediate_output?: Record<string, unknown> | null; error_recovery?: string | null;
};
export type HealthSummary = {
  user_id: number; workflow_type: string; orchestration_state: string; generated_at: string; summary_text: string;
  user_request?: string | null; detected_intent?: string | null; planner_mode?: string | null;
  selected_agents?: string[]; termination_reason?: string | null;
  monitoring?: { status: string; metric_type: string; latest_value: number | null; unit: string; summary: string; is_urgent: boolean; urgent_reason?: string | null; recent_readings_count: number } | null;
  risk_assessment?: { risk_level: string; summary: string; is_experimental: boolean; rule_based_findings: Record<string, unknown>[]; experimental_ml_estimates: Record<string, unknown>[]; disclaimer: string } | null;
  medication?: { active_medications_count: number; overall_adherence_percentage: number | null; overdue_doses_count: number; missed_doses_count: number; taken_doses_count: number; summary: string; recommendations: string[] } | null;
  medical_knowledge?: { status: string; explanation: string; citations: { title: string; source_organization?: string | null; source_url?: string | null; excerpt: string }[]; is_emergency: boolean; emergency_guidance?: string | null } | null;
  notifications?: { notifications_created: Record<string, unknown>[]; suppressed_count: number; summary: string } | null;
  safety_escalation?: Record<string, unknown> | null;
  execution_steps: ExecutionStep[]; duration_ms: number; disclaimer: string;
};
export type AuditEntry = {
  id: number; user_id: number; workflow_type: string; status: string; created_at: string; completed_at: string | null;
  duration_ms: number | null; summary: string | null; error_message: string | null;
  user_request?: string | null; planner_mode?: string | null; selected_agents?: string[]; execution_steps?: ExecutionStep[];
};
export type OrchestrationAlerts = {
  user_id: number;
  unread_monitoring_events: { id: number; metric_type: string; event_type: string; event_level: string; message: string; created_at: string }[];
  pending_medication_reminders: { id: number; occurrence_id: number | null; medication_id: number; message: string; created_at: string }[];
  recent_safety_escalations: { id: number; workflow_type: string; created_at: string; details: string | null }[];
};

export type DiabetesFeatures = {
  Pregnancies: number; Glucose: number; BloodPressure: number; SkinThickness: number;
  Insulin: number; BMI: number; DiabetesPedigreeFunction: number; Age: number;
};
export type DiabetesPredictionV3 = {
  prediction: number; model_score: number; screening_result: string;
  model: string; model_version: string; threshold: number; disclaimer: string;
};

export const predictDiabetesV3 = (features: DiabetesFeatures) =>
  request<DiabetesPredictionV3>('/ml/diabetes/predict-v3', { method: 'POST', body: features });

export const runAssessment = (body: { metric_type: string; include_knowledge: boolean; include_adherence?: boolean; experimental_ml?: boolean; ml_features?: DiabetesFeatures | null }) =>
  request<HealthSummary>('/orchestration/assess', { method: 'POST', body: { include_adherence: true, experimental_ml: false, ...body } });
export const runDynamicWorkflow = (body: {
  query: string;
  metric_type?: string | null;
  max_steps?: number;
  experimental_ml?: boolean;
  ml_features?: DiabetesFeatures | null;
  allow_notification_delivery?: boolean;
}) => request<HealthSummary>('/orchestration/execute', { method: 'POST', body });
export const getHealthSummary = (primaryMetric = 'blood_glucose') => request<HealthSummary>('/orchestration/summary', { query: { primary_metric: primaryMetric } });
export const runMedicationCheck = () => request<HealthSummary>('/orchestration/medication-check', { method: 'POST', body: { force_refresh: true } });
export const getOrchestrationHistory = (limit = 20) => request<AuditEntry[]>('/orchestration/history', { query: { limit } });
export const getOrchestrationAlerts = () => request<OrchestrationAlerts>('/orchestration/alerts');

// ---------------------------------------------------------------------------
// Demo data (only used when VITE_DEMO_MODE=true)
// ---------------------------------------------------------------------------

export type ChatMessage = { role: 'user' | 'assistant'; text: string; sources?: RagSource[]; limitations?: string[]; model?: string; error?: boolean };

export const demoMetrics: Metric[] = Array.from({ length: 14 }, (_, i) => {
  const d = new Date(2026, 9, 28 + i);
  return { id: String(i), date: d.toISOString().slice(0, 10), heartRate: 69 + (i * 7) % 14, glucose: 92 + (i * 11) % 26, systolic: 112 + (i * 5) % 17, diastolic: 72 + (i * 3) % 13, steps: 4300 + (i * 1237) % 6500 };
});

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/** Backend timestamps are naive UTC; treat them as UTC when displaying. */
export function parseUtc(s: string | null | undefined): Date | null {
  if (!s) return null;
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : s + 'Z');
  return Number.isNaN(d.getTime()) ? null : d;
}
export const fmtDateTime = (s: string | null | undefined) => parseUtc(s)?.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) ?? '—';
export const fmtTime = (s: string | null | undefined) => parseUtc(s)?.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) ?? '—';
export const humanize = (s: string | null | undefined) => (s ?? '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
