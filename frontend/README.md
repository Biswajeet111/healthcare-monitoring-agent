# HealthGuard AI — React Frontend

Responsive React + TypeScript + Vite dashboard integrated with the HealthGuard AI FastAPI backend.

## Features Integrated with FastAPI

- **Authentication (`/auth/*`)**: User registration, email/password sign-in, JWT `sessionStorage` management, `/auth/me` profile hydration, and automatic sign-out on `401 Unauthorized`.
- **Overview (`Overview`)**: Latest physiological snapshot, heart rate trend chart, active monitoring/orchestration alerts (`/orchestration/alerts`), and today's scheduled doses (`/medications/user/{id}/today`).
- **Health Analytics (`Analytics`)**: Multi-range interactive Recharts area charts (`7`, `14`, `30`, `90` days), manual measurement entry (`POST /metrics`, `POST /users/{id}/metrics/blood-pressure`), and bulk CSV import (`POST /metrics/import-csv`).
- **AI Medical Assistant (`AI Assistant`)**: Grounded medical Q&A (`POST /rag/ask`) with source citations, limitation notices, user document filtering, and live Ollama/embedding readiness checks (`GET /rag/status`).
- **Medication Tracker (`Medications`)**: Full medication CRUD (`POST /medications`, `PATCH /medications/{id}`, `DELETE /medications/{id}/deactivate`), schedule configuration (`POST/GET /medications/{id}/schedule`), daily dose confirmation (`PATCH /medications/occurrences/{id}`), and adherence analytics (`GET /medications/{id}/adherence-v2`).
- **Agentic AI Workspace (`Agents`)**: Trigger Workflow A (`POST /orchestration/assess`), Workflow B (`POST /orchestration/medication-check`), and Workflow C (`GET /orchestration/summary`), run standalone or integrated **Experimental Diabetes Screening Model v3** (`POST /ml/diabetes/predict-v3`), inspect per-agent execution steps and latency, and review audit logs (`GET /orchestration/history`) and alerts (`GET /orchestration/alerts`).
- **Medical Documents (`Documents`)**: Upload PDF medical reports (`POST /documents/upload`), open and view uploaded PDFs inline (`GET /documents/{id}/file`), view indexing status and chunk counts (`GET /rag/documents`), trigger re-indexing (`POST /rag/documents/{id}/index`), and delete documents (`DELETE /documents/{id}`).
- **Notifications & Monitoring (`Notifications`)**: View delivered notifications (`GET /users/{id}/notifications`), summary counts (`GET /users/{id}/notifications/summary`), monitoring events (`GET /users/{id}/monitoring/events`), and medication reminders (`GET /reminders/medications`), with one-click acknowledgment (`PATCH /users/{id}/monitoring/events/{event_id}/acknowledge`, `PATCH /reminders/medications/{id}/acknowledge`).
- **Workspace Settings (`Settings`)**: View authenticated user profile, live RAG/Ollama status, environment configuration, and privacy/clinical disclaimers.

## Setup & Run (Windows PowerShell / CMD)

### 1. Start the FastAPI Backend

From `F:\healthcare-ai-agent`:

```powershell
.\venv\Scripts\python.exe -m uvicorn healthguard.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Start the React Frontend

From `F:\healthcare-ai-agent\frontend`:

```powershell
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Production Build

```powershell
cd F:\healthcare-ai-agent\frontend
npm run build
```

## Security Note

Never store secret API keys in `VITE_` environment variables. Those values are embedded into browser bundles. Configure LLM and provider keys exclusively in the FastAPI backend.
