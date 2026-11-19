# HealthGuard AI — Cloud Deployment Guide

This guide describes how to deploy **HealthGuard AI** publicly for permanent evaluation without running a developer laptop, using:
- **Frontend:** Vercel (React 18 + TypeScript + Vite)
- **LLM Inference:** Groq API (`LLM_PROVIDER=groq`)
- **Database:** Managed PostgreSQL (Neon Free Tier or Render Postgres)
- **Backend API:** Docker-hosted FastAPI (`Dockerfile` / `render.yaml`)

> **Important:** Use **synthetic demonstration data only** (`HG-DEMO-001`). Never upload or migrate real patient data to an academic evaluation deployment.

---

## 1. Resource & Memory Assessment (Render Free Tier vs. Recommended Hosting)

Measured runtime memory of the FastAPI backend on Python 3.10/3.11:

| Stage | Measured Process RSS |
|---|---:|
| Python baseline | `15.6 MB` |
| After importing FastAPI + SQLAlchemy + Scikit-Learn + ChromaDB | `203.7 MB` |
| After loading `SentenceTransformer("all-MiniLM-L6-v2")` | `570.8 MB` |
| Steady-state after ChromaDB similarity query (`3,197` chunks) | `597.4 MB` |
| Peak during PDF upload / chunk indexing | `~650–850 MB` |

Persistent storage footprint:
- Clinical ChromaDB vector index (`data/vector_db`): **44.45 MB**
- Approved clinical reference PDFs (`Document/`): **10.99 MB**
- Experimental ML model (`models/`): **0.28 MB**
- Application relational DB (`healthguard.db` / Postgres): **~3–20 MB**

### Why Render Free Tier Is Insufficient
- **RAM ceiling:** Render Free Web Services are strictly capped at **512 MB RAM**. Loading `all-MiniLM-L6-v2` (PyTorch) exceeds 512 MB immediately (`570.8 MB` RSS) and causes OOM kills (`Exit Code 137`).
- **Ephemeral disk:** Render Free does **not** support persistent disks; ChromaDB vectors and uploaded PDFs are wiped on redeploy or after 15 minutes of inactivity.
- **Database expiry:** Render Free PostgreSQL expires after 30 days.

### Recommended Hosting Options

| Option | Backend Host | Database | Persistent Vector/PDF Storage | Monthly Cost |
|---|---|---|---|---|
| **Option A (Zero-Cost Academic Evaluation)** | **Hugging Face Spaces** (Docker SDK, CPU Basic: **2 vCPU / 16 GB RAM**) | **Neon PostgreSQL** (Free tier, no expiry) | Pre-ingested `medical_knowledge` built into container + `extracted_text` persisted in Neon Postgres (or optional \$5/mo HF `/data` volume for raw PDF binaries & ChromaDB persistence across restarts) | **\$0/mo** (or \$5/mo with persistent `/data`) |
| **Option B (Low-Cost Persistent Volume)** | **Railway Hobby** (up to 8 GB RAM + persistent Volume mounted at `/var/data`) | **Neon PostgreSQL** (Free) or Railway Postgres | Railway Volume mounted at `/var/data` (`VECTOR_DB_PATH=/var/data/vector_db`, `UPLOAD_DIR=/var/data/medical_reports`) | **~\$5/mo** |
| **Option C (Render Production)** | **Render Standard** (`render.yaml`, 2 GB RAM) | **Neon PostgreSQL** (Free) or Render Starter Postgres | Render Persistent Disk (`2 GB` mounted at `/var/data`) | **\$25/mo + \$0.50/mo disk** |

---

## 2. Required Environment Variables

### Backend (Cloud Host Secrets / Environment)

| Variable | Example / Notes | Secret? |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:pass@host/neondb?sslmode=require` | Yes |
| `JWT_SECRET_KEY` | Output of `openssl rand -hex 32` | Yes |
| `GROQ_API_KEY` | Your Groq API key | Yes |
| `DIABETES_V3_SHA256` | 64-char SHA-256 checksum of `models/diabetes_v3_candidate/pipeline.joblib` | No |
| `LLM_PROVIDER` | `groq` | No |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` (or another active chat model on your Groq account) | No |
| `ALLOW_CLOUD_PERSONAL_DATA` | `true` (for synthetic evaluation accounts only; `false` omits personal context from Groq) | No |
| `CORS_ORIGINS` | `https://your-app.vercel.app` (comma-separated, no trailing slash) | No |
| `CORS_ORIGIN_REGEX` | `^https://.*\.vercel\.app$` (optional, enables Vercel preview deployments) | No |
| `VECTOR_DB_PATH` | `/var/data/vector_db` (persistent volume path) | No |
| `UPLOAD_DIR` | `/var/data/medical_reports` (persistent volume path) | No |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | No |
| `EMBEDDING_LOCAL_FILES_ONLY` | `true` (when pre-cached in Docker image) | No |
| `DEBUG` | `false` | No |
| `ENABLE_REMINDER_WORKER` | `true` | No |

### Frontend (Vercel Project Settings → Environment Variables)

| Variable | Value | Secret? |
|---|---|---|
| `VITE_API_BASE_URL` | `https://your-backend-domain` (no trailing slash) | No |
| `VITE_DEMO_MODE` | `false` | No |

> **Security Rule:** Never expose `GROQ_API_KEY`, `JWT_SECRET_KEY`, or `DATABASE_URL` as `VITE_*` variables.

---

## 3. Step-by-Step Deployment Procedure

### Step 1: Provision Persistent PostgreSQL (Neon Free Tier)
1. Create a free project on [neon.tech](https://neon.tech/).
2. Copy the pooled or direct PostgreSQL connection string (`postgresql://...?sslmode=require`).

### Step 2: Deploy the FastAPI Backend
- **Via Render (`render.yaml`):**
  1. Connect the GitHub repository in Render → **Blueprints** (or **New Web Service → Docker**).
  2. Attach a persistent disk mounted at `/var/data` (`2 GB`).
  3. Set all backend environment variables listed above.
  4. Verify `GET https://<backend-url>/health` returns `{"status": "ok", "database": "connected", "llm_provider": "groq", ...}`.
- **Via Hugging Face Spaces (Zero-Cost 16 GB RAM Docker):**
  1. Create a new Space with **Docker** SDK (`Blank` template), port `7860` (`PORT=7860`).
  2. Set the backend environment variables under **Settings → Variables and secrets**.
  3. Push the backend repository to the Space remote.
- **Via Railway:**
  1. Create a new project from the GitHub repo (auto-detects `Dockerfile`).
  2. Add a **Volume** mounted at `/var/data`.
  3. Set the backend environment variables and expose the public domain.

### Step 3: Initialize Global Clinical Knowledge & Synthetic Demo Patient (One-Time)
Run these one-time idempotent commands inside the deployed backend container/shell (do **not** run destructive resets on startup):

```bash
# 1. Verify schema migrations are at head (already run automatically on startup)
python -m alembic upgrade head

# 2. Ingest the 7 approved clinical reference documents into PostgreSQL + ChromaDB
python -m scripts.ingest_approved_docs

# 3. Provision the synthetic evaluation patient (HG-DEMO-001)
python scripts/setup_demo_hg_demo_001.py --setup
```

### Step 4: Deploy React Frontend on Vercel
1. Import the GitHub repository in [vercel.com](https://vercel.com/).
2. Set **Root Directory** to `frontend`.
3. Framework Preset: **Vite** (`npm run build`, output directory `dist`).
4. Add Environment Variables:
   - `VITE_API_BASE_URL=https://<your-deployed-backend-url>`
   - `VITE_DEMO_MODE=false`
5. Deploy and copy the live Vercel URL (`https://<project>.vercel.app`).
6. Set `CORS_ORIGINS=https://<project>.vercel.app` on the backend host and redeploy/restart the backend.

### Step 5: Smoke-Test Production Deployment
1. Open `https://<project>.vercel.app` and sign in with the synthetic evaluation account.
2. Check **Settings → Connection & AI runtime** to confirm `LLM provider (Groq Cloud): available`, `Embedding model: loaded`, and `RAG Q&A readiness: ready`.
3. Ask a medical question in **AI Assistant** and verify numbered citations (`[1]`, `[2]`).
4. Run a dynamic orchestration prompt in **Agent Workspace** and confirm `Mode: Llm Assisted` with step-by-step tool trace.
5. Open an uploaded PDF on **Medical Documents** to verify authenticated file streaming.
