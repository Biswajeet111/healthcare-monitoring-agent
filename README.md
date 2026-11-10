<div align="center">

<img src="assets/HealthGuard%20AI_%20Neon%20Heart%20Companion.png" alt="HealthGuard AI Logo" width="240"/>

# HealthGuard AI

### An Agentic AI-Powered Personal Healthcare Intelligence Platform

**Intelligent Health Monitoring • Clinical Knowledge Retrieval • Medication Management • Multi-Agent Reasoning**

An AI-assisted healthcare platform that combines structured health monitoring, retrieval-augmented generation (RAG), autonomous agent orchestration, and explainable health insights to help users better understand and manage their health information.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-111111)](https://ollama.com/)
[![Groq](https://img.shields.io/badge/Groq-Optional%20Inference-F55036)](https://groq.com/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20Database-FF6B35)](https://www.trychroma.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-D71F00)](https://www.sqlalchemy.org/)

</div>

---

## Overview

HealthGuard AI is a modular, AI-powered healthcare intelligence system designed to transform fragmented health information into structured, understandable, and actionable insights.

Traditional health-tracking applications often focus on recording measurements or displaying historical trends. HealthGuard AI extends this approach by combining health records, clinical reference documents, medication adherence information, and specialized AI agents within a unified backend.

The platform supports health monitoring and educational medical question answering while maintaining a separation between deterministic application logic and generative AI.

Its architecture emphasizes:

- **Agentic orchestration:** Specialized agents coordinate health-related analysis and recommendations.
- **Evidence-grounded AI:** Retrieval-augmented generation incorporates indexed clinical reference documents.
- **Privacy-aware processing:** Local language-model inference is supported through Ollama.
- **Structured health intelligence:** Health measurements, medication records, and monitoring events are managed through persistent application services.
- **Explainability and traceability:** Retrieved sources, execution information, and agent activity support inspection of AI-assisted outputs.
- **Safety-oriented design:** Medical request screening, response validation, and escalation mechanisms reduce reliance on unrestricted LLM generation.

HealthGuard AI is intended for educational, personal health-information management, and technical demonstration purposes. It is not a medical device or a substitute for professional healthcare.

---

## Core Capabilities

### Intelligent Health Monitoring

HealthGuard AI provides a structured environment for recording and reviewing personal health measurements.

Capabilities include:

- Health metric recording and historical tracking.
- Measurement validation and unit normalization.
- Trend analysis and monitoring summaries.
- Threshold-based monitoring logic.
- Health-related notifications and alerts.
- User-specific data access.

The monitoring system combines database-backed records with application-level validation to maintain consistent measurement handling.

### AI Medical Assistant

The integrated medical assistant helps users understand medical concepts and interpret educational healthcare information.

It supports:

- Natural-language medical questions.
- Explanations of common medical terminology.
- Educational information about prevention and disease management.
- Summaries of retrieved clinical reference passages.
- Source-linked responses using numbered citations.
- Context-aware explanations when relevant user information is available.
- Explicit limitations when supporting reference material is unavailable.

The assistant is designed to provide clear, accessible explanations rather than simply reproducing research papers.

### Clinical Retrieval-Augmented Generation

HealthGuard AI uses a local vector database to retrieve relevant medical reference passages before generating answers.

The clinical knowledge pipeline includes:

1. Document ingestion and text extraction.
2. Text chunking and metadata preservation.
3. Semantic embedding generation.
4. Persistent vector storage.
5. Similarity-based retrieval.
6. Context preparation with source identifiers.
7. Language-model response generation.
8. Source metadata presentation.

The current local knowledge index contains **3,197 text chunks derived from seven clinical reference documents**.

Indexed topics include:

- Diabetes prevention and monitoring.
- Diabetes diagnosis and classification.
- Pharmacologic approaches to glycemic treatment.
- Cardiovascular disease management.
- Hypertension management.
- Noncommunicable disease guidance.

Source titles, organizations, chunk identifiers, and retrieval distances are retained to support traceability.

**Important:** Retrieval metadata confirms which passages were supplied to the model. It does not independently establish the clinical accuracy of every generated statement.

### Multi-Agent Health Intelligence

HealthGuard AI incorporates a specialized multi-agent architecture to separate responsibilities across distinct health-related functions.

| Agent | Responsibility |
|---|---|
| Medical Knowledge Agent | Retrieves and interprets relevant medical reference information. |
| Monitoring Agent | Evaluates health measurement information and monitoring conditions. |
| Medication Agent | Processes medication-related information and adherence context. |
| Risk Assessment Agent | Supports structured health-risk screening and escalation logic. |
| Notification Agent | Coordinates relevant health notifications and follow-up information. |

An orchestration layer coordinates agent execution and consolidates results.

The architecture supports:

- Specialized agent responsibilities.
- Structured agent outputs.
- Coordinated execution.
- Execution audit records.
- Safety escalation handling.
- Graceful degradation when dependent AI services are unavailable.

Agent outputs are intended to support health-information workflows, not autonomous clinical diagnosis or treatment.

### Medication Management

The medication management functionality supports structured tracking of medication information and adherence-related activity.

Its purpose is to help users maintain organized records and understand adherence patterns.

The platform does not independently prescribe medication, determine dosages, or authorize treatment changes.

### Health Risk Screening

HealthGuard AI includes experimental health-risk assessment functionality.

These assessments are designed for informational screening and technical exploration.

**Risk scores and model outputs must not be interpreted as confirmed diagnoses or clinically validated predictions.**

### Notifications and Monitoring Events

The system supports notification-oriented workflows associated with monitoring activity and relevant health information.

Notification handling is integrated with backend services and agent orchestration to maintain a structured flow between observations, analysis, and user-facing information.

---

## System Architecture

HealthGuard AI follows a modular architecture that separates presentation, API services, application logic, AI orchestration, and persistent storage.

```text
                         HEALTHGUARD AI
                               |
                    +----------------------+
                    |   User Interface     |
                    |  Streamlit Dashboard |
                    +----------------------+
                               |
                               v
                    +----------------------+
                    |     FastAPI API      |
                    | Authentication / JWT |
                    | Validation / Routing |
                    +----------------------+
                               |
             +-----------------+-----------------+
             |                 |                 |
             v                 v                 v
    +----------------+ +----------------+ +----------------+
    | Health Records | | Medical RAG    | | Agentic        |
    | & Monitoring   | | Services       | | Orchestrator   |
    +----------------+ +----------------+ +----------------+
             |                 |                 |
             |                 |                 v
             |                 |       +----------------------+
             |                 |       | Specialized Agents   |
             |                 |       |                      |
             |                 |       | Medical Knowledge    |
             |                 |       | Monitoring           |
             |                 |       | Medication           |
             |                 |       | Risk Assessment      |
             |                 |       | Notification         |
             |                 |       +----------------------+
             |                 |
             v                 v
    +----------------+ +----------------------+
    | SQLAlchemy ORM | | Embedding Service    |
    | SQLite         | | all-MiniLM-L6-v2     |
    | Alembic        | +----------------------+
    +----------------+            |
                                  v
                         +------------------+
                         |     ChromaDB     |
                         | Clinical Vectors |
                         | User Documents   |
                         +------------------+
                                  |
                                  v
                         +------------------+
                         |  LLM Inference   |
                         |                  |
                         | Ollama (Local)   |
                         | Groq (Optional)  |
                         +------------------+
                                  |
                                  v
                         +------------------+
                         | Grounded Response|
                         | Source Metadata  |
                         | Safety Handling  |
                         +------------------+
```

The separation of services allows individual components to be tested, maintained, and extended without tightly coupling the user interface to AI inference.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Programming Language | Python 3.10 |
| Backend Framework | FastAPI |
| API Server | Uvicorn |
| Dashboard | Streamlit |
| Database | SQLite |
| ORM | SQLAlchemy |
| Database Migrations | Alembic |
| Authentication | JWT-based authentication |
| Vector Database | ChromaDB |
| Embedding Model | Sentence Transformers — `all-MiniLM-L6-v2` |
| Local LLM | Ollama with Llama 3.1 |
| Optional Cloud Inference | Groq API |
| HTTP Client | HTTPX |
| Testing | Pytest |
| AI Architecture | Retrieval-Augmented Generation and Multi-Agent Orchestration |

The backend is organized into independent modules for database access, APIs, monitoring, RAG, safety, and orchestration.

---

## Medical RAG Workflow

The retrieval-augmented generation pipeline is designed to improve the relevance and traceability of medical information provided by the assistant.

```text
User Question
     |
     v
Request Validation
     |
     v
Embedding Generation
     |
     v
ChromaDB Similarity Search
     |
     v
Relevant Clinical Passages
     |
     v
Source Metadata + Context Preparation
     |
     v
Ollama / Configured LLM Provider
     |
     v
Generated Educational Answer
     |
     v
Citation and Safety Checks
     |
     v
Answer + Retrieved Clinical References
```

### Embedding Consistency

The global medical knowledge index uses the `all-MiniLM-L6-v2` embedding model.

Consistent embedding generation is essential because switching embedding algorithms between indexing and querying can make semantic retrieval unreliable.

The embedding service is designed to avoid silently replacing the required model with an incompatible fallback.

### Source Attribution

Retrieved passages are assigned reference numbers before being supplied to the language model.

The assistant can use citations such as `[1]` and `[2]`, which correspond to source metadata returned by the retrieval pipeline.

Citation-number validation checks whether a generated reference points to an available retrieved passage.

It does **not** independently prove that the cited passage supports the associated medical claim.

### Knowledge Base Organization

HealthGuard AI separates approved global medical reference material from user-specific documents.

```text
ChromaDB
|
+-- medical_knowledge
|   |
|   +-- Approved clinical reference chunks
|
+-- user_documents_<user_id>
    |
    +-- User-specific document chunks
```

This design supports logical separation of shared reference information and private user documents.

---

## Privacy, Security, and Safety

Healthcare applications require particular attention to sensitive information and potentially harmful outputs.

HealthGuard AI incorporates several application-level safeguards.

### Authentication and Data Isolation

- JWT-based authenticated access.
- User-specific database records.
- Separate ChromaDB collections for user documents.
- Application-level access controls.
- Structured backend validation.

### Local AI Processing

Ollama enables language-model inference on a local machine.

This reduces the need to transmit medical prompts to external model providers.

Local processing does not, by itself, guarantee complete privacy or security. Operating-system access, application logs, storage configuration, and deployment settings must also be secured.

### Optional Cloud Inference

Groq integration is available as an optional inference provider.

Cloud inference is not automatically substituted when Ollama is unavailable.

**Privacy consideration:** Cloud-based inference transmits prompt content to an external provider. Personal health information and private medical documents should not be transmitted without appropriate authorization, safeguards, and a clear understanding of the provider's data-handling terms.

### Medical Safety Controls

The application includes:

- Medical request screening.
- Emergency keyword detection.
- Unsafe diagnostic and prescription pattern detection.
- Medication-change instruction checks.
- Retrieved-context prompt-injection filtering.
- Response validation and safety handling.
- Educational medical disclaimers.

These safeguards are supplementary controls and cannot guarantee detection of every unsafe or inaccurate response.

### Emergency Handling

The safety layer includes predefined emergency guidance for potentially serious situations.

The application is not intended for emergency triage or real-time emergency response.

Users experiencing a possible medical emergency should contact local emergency services immediately.

---

## Getting Started

### Prerequisites

Install the following:

- Python 3.10 or a compatible project environment.
- Git.
- Ollama for local AI inference.
- A supported operating system.
- Sufficient memory and storage for the selected language model and embedding model.

Groq is optional.

### 1. Clone the Repository

```bash
git clone https://github.com/Biswajeet111/healthcare-ai-agent.git
cd healthcare-ai-agent
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it on Windows:

```cmd
venv\Scripts\activate
```

On Linux or macOS:

```bash
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a local `.env` file using the project's configuration requirements.

Example settings:

```env
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=llama3.1
LLM_PROVIDER=ollama
```

For optional Groq inference:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
ALLOW_CLOUD_PERSONAL_DATA=false
```

Additional application settings, including database configuration and authentication secrets, must be configured according to the backend's settings module.

**Never commit `.env` files, API keys, authentication secrets, or private health information.**

### 5. Prepare Ollama

Install Ollama and download the local model:

```bash
ollama pull llama3.1
```

Verify that Ollama is available:

```bash
ollama list
```

Ensure the Ollama service is running before making local AI requests.

### 6. Apply Database Migrations

```bash
python -m alembic upgrade head
```

### 7. Start the Backend

```bash
python -m uvicorn healthguard.main:app --reload --port 8000
```

The API will be available locally at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

### 8. Start the Dashboard

Open another terminal:

```bash
python -m streamlit run healthguard/dashboard/app.py --server.port 8501
```

Access the dashboard at:

```text
http://localhost:8501
```

### 9. Prepare the Clinical Knowledge Base

The repository includes an ingestion utility for approved medical reference documents.

```bash
python -m scripts.ingest_approved_docs
```

The corresponding source documents must be available locally in the expected document directory.

If the SQL document records exist but their ChromaDB vectors are missing, the repair utility can rebuild the global vector index from the stored document chunks:

```bash
python -m scripts.repair_global_rag_index
```

**Do not run the repair utility unnecessarily against an already healthy index.** Back up the database and vector store before rebuilding indexes.

The vector database is maintained locally and is not required to be committed to Git.

---

## Testing and Verification

HealthGuard AI uses Pytest for automated backend and application testing.

Run the complete test suite:

```bash
python -m pytest tests/ -q
```

Latest local test result:

```text
363 passed in 67.41s
```

The test suite covers implemented application behavior, including backend functionality and agentic orchestration.

Additional manual verification has been performed for:

- Medical reference retrieval.
- Ollama-based answer generation.
- Source metadata presentation.
- Numbered citation formatting.
- Medication safety responses.
- Emergency guidance.
- Medical knowledge index consistency.

### RAG Index Verification

The repaired local clinical knowledge index contains:

```text
medical_knowledge: 3197 chunks
```

A separate legacy collection was preserved during the repair:

```text
langchain: 2705 chunks
```

These counts describe the tested local development environment and may differ in a fresh installation.

### Important Testing Limitation

Passing automated tests demonstrates that the tested software behavior meets its assertions.

It does not establish clinical effectiveness, medical accuracy across all scenarios, regulatory compliance, or suitability for real-world patient care.

---

## Engineering Design Principles

HealthGuard AI is developed around several technical principles.

**Modularity:** Application responsibilities are separated into independently maintainable services.

**Deterministic controls:** Authentication, record validation, access restrictions, and selected safety checks operate outside the language model.

**Evidence traceability:** Retrieved passages retain document metadata and source identifiers.

**Provider flexibility:** Local and optional cloud language-model inference can be configured without redesigning the application.

**Failure transparency:** Missing AI services or reference information should be communicated rather than silently replaced with fabricated results.

**Extensibility:** The API-oriented architecture supports additional user interfaces, monitoring capabilities, and AI services.

**Privacy awareness:** Sensitive health information requires explicit controls around storage, access, processing, and transmission.

---

## Current Limitations

HealthGuard AI is an engineering project with important limitations.

### Clinical Validation

The platform has not undergone clinical trials or formal validation as a medical decision-support system.

AI-generated responses may contain inaccurate, incomplete, outdated, or misleading information.

### Retrieval and Citation Reliability

Although the application retrieves real document passages and validates citation identifiers, it does not independently verify that every generated medical claim is fully supported by the cited source.

### Medical Knowledge Coverage

The clinical knowledge base is limited to the documents that have been ingested.

The presence of a medical document does not guarantee that its recommendations are current, comprehensive, or appropriate for a particular patient.

### Risk Assessment

Experimental risk-screening functionality must not be interpreted as a clinically validated diagnostic model.

### Document Processing

Text-based document extraction is supported in the ingestion workflow.

Scanned documents and image-based medical reports may require additional OCR capabilities.

### Emergency Use

The system is not suitable for emergency diagnosis, triage, or treatment decisions.

### Cloud Privacy

Using an external inference provider introduces additional data-transmission and privacy considerations.

### Production Readiness

Additional security assessment, deployment hardening, operational monitoring, clinical evaluation, and regulatory review would be required before considering real-world healthcare deployment.

---

## Future Extensibility

The modular architecture supports further development in areas such as:

- Enhanced clinical citation verification.
- Broader medical knowledge coverage.
- OCR-assisted medical document understanding.
- Improved health trend visualization.
- More comprehensive agent evaluation.
- Expanded interoperability with health data sources.
- Stronger monitoring and observability.
- Additional user-interface experiences.
- Privacy-preserving deployment strategies.

These represent architectural extension opportunities rather than claims of currently implemented functionality.

---

## Responsible Use

HealthGuard AI is intended for educational and software-engineering purposes.

It should not be used as the sole basis for diagnosing medical conditions, selecting treatments, changing prescriptions, or responding to emergencies.

Medical decisions should be made with qualified healthcare professionals.

The project does not claim clinical certification, regulatory approval, or guaranteed medical accuracy.

---

## Author

**Biswajeet Kumar**

Computer Science Engineering  
Lovely Professional University

**Areas of Interest:** Generative AI, Agentic AI, Machine Learning, Backend Engineering, and Intelligent Systems.

**GitHub:** https://github.com/Biswajeet111

**Portfolio:** https://biswajeet111.github.io/portfolio/

**LinkedIn:** https://www.linkedin.com/in/biswajeet-kumar-dev/

---

<div align="center">

### HealthGuard AI

**Bringing structured health information, clinical knowledge retrieval, and agentic intelligence together.**

*Built with Python, FastAPI, ChromaDB, Ollama, and multi-agent AI architecture.*

**Educational AI • Explainable Retrieval • Privacy-Aware Design**

</div>