# HealthGuard AI

**Agentic AI-Powered Personal Healthcare Intelligence Platform**

HealthGuard AI is a healthcare monitoring platform designed to help users track personal health metrics, manage medications, import medical records, and understand health trends through structured analytics.

The platform is being developed with a local-first architecture, combining backend APIs, machine learning, medical knowledge retrieval (RAG), and agentic AI workflows.

> **Current Status:** Phase 1 — Core Healthcare Platform implemented. Phase 2 — Machine Learning and Agentic AI integration planned.

---

## Key Features

### 1. Health Metrics Monitoring

* Record blood glucose levels.
* Track systolic and diastolic blood pressure.
* Monitor heart rate, weight, and height.
* Track steps and sleep duration.
* Filter records by metric type and date.
* View metric summaries and analytics.
* Preserve original measurements alongside normalized values.
* Support manual and imported health data.

### 2. User Authentication and Security

* User registration and login.
* Password hashing using Argon2.
* JWT-based authentication.
* Protected API endpoints.
* User-specific data access restrictions.
* Cross-user access protection.

### 3. Blood Pressure Monitoring

* Record systolic and diastolic readings together.
* Group related measurements.
* Retrieve blood pressure history.
* Preserve original measurement values.

### 4. Medication Management

* Add and manage medications.
* Store dosage and frequency information.
* Record medication activity.
* Track scheduled and completed doses.
* Calculate medication adherence.

### 5. Medical Document Management

* Upload medical reports in PDF format.
* Extract text from supported PDFs.
* Store document metadata and SHA-256 hashes.
* List uploaded medical documents.
* Delete documents securely.
* Reject unsupported, encrypted, oversized, or invalid PDFs.

Scanned PDFs requiring OCR are not yet supported.

### 6. CSV Health Data Import

* Import health measurements through CSV files.
* Validate required columns and measurement units.
* Normalize compatible measurements.
* Preserve original values and units.
* Report row-level validation errors.
* Prevent duplicate imports for the same user.

Required CSV columns:

```csv
metric_type,value,unit
blood_glucose,5.5,mmol/L
heart_rate,75,bpm
weight,68,kg
```

Optional column:

```csv
recorded_at
```

### 7. Healthcare Dashboard

A Streamlit dashboard provides:

* Secure login.
* Automatic user profile retrieval.
* Health metric summaries.
* Blood glucose analytics.
* Heart rate analytics.
* Blood pressure history.
* Medication adherence information.
* Account logout.

---

## System Architecture

```text
                 USER
                   |
                   v
          STREAMLIT DASHBOARD
                   |
                   v
             FASTAPI BACKEND
                   |
          JWT AUTHENTICATION
                   |
                   v
          APPLICATION SERVICES
                   |
       +-----------+-----------+
       |           |           |
       v           v           v
   HEALTH       MEDICATION   DOCUMENT
   METRICS      MANAGEMENT   MANAGEMENT
       |           |           |
       +-----------+-----------+
                   |
                   v
             SQLITE DATABASE
                   |
                   v
          ANALYTICS & NORMALIZATION
                   |
                   v
          FUTURE AI INTEGRATION
                   |
       +-----------+-----------+
       |           |           |
       v           v           v
      ML          RAG       LANGGRAPH
   SCREENING    KNOWLEDGE     AGENT
               RETRIEVAL
```

---

## Technology Stack

| Component            | Technology                     |
| -------------------- | ------------------------------ |
| Programming Language | Python 3.10                    |
| Backend              | FastAPI                        |
| Database             | SQLite                         |
| ORM                  | SQLAlchemy                     |
| Database Migrations  | Alembic                        |
| Authentication       | JWT                            |
| Password Security    | Argon2                         |
| Validation           | Pydantic                       |
| Dashboard            | Streamlit                      |
| Data Processing      | Pandas, NumPy                  |
| Machine Learning     | Scikit-learn, XGBoost, PyTorch |
| AI Frameworks        | LangChain, LangGraph           |
| Vector Database      | ChromaDB                       |
| Embeddings           | Sentence Transformers          |
| PDF Processing       | pypdf                          |
| Testing              | Pytest, HTTPX                  |

---

## Project Structure

```text
healthcare-monitoring-agent/
│
├── healthguard/
│   ├── agents/
│   │   └── __init__.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── dependencies.py
│   │
│   ├── database/
│   │   ├── base.py
│   │   ├── models.py
│   │   └── session.py
│   │
│   ├── dashboard/
│   │   └── app.py
│   │
│   ├── ml/
│   │   └── __init__.py
│   │
│   ├── rag/
│   │   └── __init__.py
│   │
│   ├── services/
│   │   ├── normalization.py
│   │   ├── csv_service.py
│   │   └── document_service.py
│   │
│   ├── schemas.py
│   └── main.py
│
├── migrations/
│   ├── versions/
│   └── env.py
│
├── tests/
│   ├── conftest.py
│   └── test_api.py
│
├── storage/
│   └── medical_reports/
│
├── .env
├── .gitignore
├── alembic.ini
├── requirements.txt
└── README.md
```

---

## Installation and Setup

### 1. Clone the repository

```cmd
git clone https://github.com/Biswajeet111/healthcare-monitoring-agent.git
```

```cmd
cd healthcare-monitoring-agent
```

### 2. Create a virtual environment

```cmd
py -3.10 -m venv venv
```

Activate it:

```cmd
venv\Scripts\activate
```

### 3. Install dependencies

```cmd
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root.

Configure the required database and authentication settings:

```env
DATABASE_URL=sqlite:///./healthguard.db
JWT_SECRET_KEY=replace_with_a_secure_random_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Use a securely generated secret in your local environment. Never commit `.env` to GitHub.

### 5. Apply database migrations

```cmd
venv\Scripts\python.exe -m alembic upgrade head
```

### 6. Start the FastAPI backend

```cmd
venv\Scripts\python.exe -m uvicorn healthguard.main:app --reload
```

Backend:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

### 7. Start the Streamlit dashboard

Open another terminal in the project directory:

```cmd
venv\Scripts\python.exe -m streamlit run healthguard/dashboard/app.py
```

---

## API Endpoints

### Authentication

| Method | Endpoint         | Description                 |
| ------ | ---------------- | --------------------------- |
| POST   | `/auth/register` | Register a user             |
| POST   | `/auth/login`    | Authenticate and obtain JWT |
| GET    | `/auth/me`       | Retrieve authenticated user |

### Health Metrics

| Method | Endpoint                                          | Description                |
| ------ | ------------------------------------------------- | -------------------------- |
| POST   | `/metrics`                                        | Record a health metric     |
| GET    | `/users/{user_id}/metrics`                        | Retrieve health records    |
| GET    | `/users/{user_id}/metrics/analytics`              | Retrieve metric analytics  |
| GET    | `/users/{user_id}/metrics/summary`                | Retrieve health summary    |
| POST   | `/users/{user_id}/metrics/blood-pressure`         | Record blood pressure      |
| GET    | `/users/{user_id}/metrics/blood-pressure/history` | Retrieve BP history        |
| POST   | `/metrics/import-csv`                             | Import health measurements |

### Medication Management

| Method | Endpoint                                 | Description                |
| ------ | ---------------------------------------- | -------------------------- |
| POST   | `/medications`                           | Add medication             |
| GET    | `/users/{user_id}/medications`           | List medications           |
| POST   | `/medications/{medication_id}/logs`      | Record medication activity |
| GET    | `/medications/{medication_id}/logs`      | Retrieve medication logs   |
| GET    | `/medications/{medication_id}/adherence` | Calculate adherence        |

### Medical Documents

| Method | Endpoint                   | Description             |
| ------ | -------------------------- | ----------------------- |
| POST   | `/documents/upload`        | Upload medical PDF      |
| GET    | `/documents`               | List uploaded documents |
| DELETE | `/documents/{document_id}` | Delete a document       |

Protected endpoints require a valid JWT access token.

---

## Measurement Normalization

HealthGuard AI uses canonical measurement units to maintain consistency in health analytics.

| Metric         | Accepted Unit | Canonical Unit |
| -------------- | ------------- | -------------- |
| Blood Pressure | mmHg          | mmHg           |
| Blood Glucose  | mg/dL, mmol/L | mg/dL          |
| Heart Rate     | bpm           | bpm            |
| Weight         | kg            | kg             |
| Height         | cm            | cm             |
| Steps          | steps         | steps          |
| Sleep Duration | hours         | hours          |

For example:

```text
Original glucose: 5.5 mmol/L
Normalized glucose: approximately 99.1 mg/dL
```

Original values and units are retained for traceability.

---

## Database Management

The application uses SQLite with SQLAlchemy ORM and Alembic migrations.

Database entities include:

* UserProfile
* HealthMetric
* Medication
* MedicationLog
* MedicalDocument
* CSVImport

Apply new migrations:

```cmd
venv\Scripts\python.exe -m alembic upgrade head
```

Check the current migration:

```cmd
venv\Scripts\python.exe -m alembic current
```

---

## Testing

The project uses Pytest and HTTPX for automated API testing.

Run the complete test suite:

```cmd
venv\Scripts\python.exe -m pytest tests/ -v
```

Tests cover:

* User registration and authentication.
* JWT-protected routes.
* Invalid authentication tokens.
* Cross-user access restrictions.
* Health metric creation and validation.
* Measurement normalization.
* Blood pressure recording.
* CSV import and validation.
* Duplicate import protection.
* Medical document access and deletion.

---

## Development Roadmap

### Phase 1 — Core Healthcare Platform

* [x] FastAPI backend.
* [x] SQLite database and migrations.
* [x] JWT authentication.
* [x] Health metric tracking.
* [x] Measurement normalization.
* [x] Blood pressure monitoring.
* [x] Medication management.
* [x] Medication adherence tracking.
* [x] PDF medical document ingestion.
* [x] CSV health data ingestion.
* [x] Streamlit dashboard.
* [x] Automated API and security tests.

### Phase 2 — Machine Learning Intelligence

* [ ] Health risk screening models.
* [ ] Diabetes risk screening.
* [ ] Hypertension risk screening.
* [ ] Personalized health trend analysis.
* [ ] Model evaluation and explainability.
* [ ] Integration of ML predictions with the backend.

### Phase 3 — Medical Knowledge and RAG

* [ ] Medical document indexing.
* [ ] Clinical guideline retrieval.
* [ ] ChromaDB integration.
* [ ] Evidence-grounded responses.
* [ ] Source citations for medical explanations.
* [ ] PDF report understanding.

### Phase 4 — Agentic Healthcare Intelligence

* [ ] LangGraph-based healthcare agent.
* [ ] Dynamic tool selection.
* [ ] Health trend interpretation.
* [ ] Context-aware health summaries.
* [ ] Safe escalation workflows.
* [ ] Local LLM integration.

### Phase 5 — Platform Expansion

* [ ] Android Health Connect integration.
* [ ] Advanced dashboard analytics.
* [ ] FHIR-compatible data exchange.
* [ ] Additional medical data connectors.
* [ ] Deployment and production hardening.

---

## Safety and Disclaimer

HealthGuard AI is an educational and research-oriented healthcare monitoring project.

Its intended purpose is to support health tracking, risk screening, and evidence-based health information retrieval.

* Risk predictions are not medical diagnoses.
* AI-generated explanations are not prescriptions.
* Users should consult qualified healthcare professionals for medical decisions.
* Emergency symptoms require immediate professional medical attention.

The platform is not intended to replace professional medical care.

---

## Author

**Biswajeet Kumar**

B.Tech Computer Science Engineering

GitHub: https://github.com/Biswajeet111

Project: https://github.com/Biswajeet111/healthcare-monitoring-agent

---

## License

This project is developed for educational and research purposes.
