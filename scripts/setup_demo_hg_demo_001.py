"""
HealthGuard AI — Synthetic Demonstration Scenario Setup & Reset (HG-DEMO-001)
=============================================================================

Creates, resets, and verifies the comprehensive synthetic patient scenario
`HG-DEMO-001` ("Aarav Sharma — Synthetic Demo HG-DEMO-001") across every major
HealthGuard AI feature using the existing FastAPI endpoints and services.

ALL GENERATED DATA IS FICTIONAL AND CLEARLY LABELED AS SYNTHETIC DEMO DATA.

Usage:
    # Full repeatable setup + verification (resets HG-DEMO-001 if already present):
    .\\venv\\Scripts\\python.exe scripts/setup_demo_hg_demo_001.py --setup

    # Verify existing HG-DEMO-001 state without modifying records:
    .\\venv\\Scripts\\python.exe scripts/setup_demo_hg_demo_001.py --verify

    # Cleanly remove ONLY the HG-DEMO-001 synthetic account and its artifacts:
    .\\venv\\Scripts\\python.exe scripts/setup_demo_hg_demo_001.py --reset
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from healthguard.database import models
from healthguard.database.session import SessionLocal
from healthguard.main import app
from healthguard.rag.vector_store import _get_chroma_client, USER_DOC_COLLECTION_PREFIX
from healthguard.services.medication_scheduler import (
    generate_occurrences_for_schedule,
    refresh_occurrence_statuses,
)


# ===========================================================================
# Synthetic Scenario Constants (HG-DEMO-001)
# ===========================================================================

SCENARIO_ID = "HG-DEMO-001"
DEMO_FULL_NAME = "Aarav Sharma (Synthetic Demo HG-DEMO-001)"
DEMO_EMAIL = "hg-demo-001@synthetic.healthguard.local"
# Credentials are kept in environment or default demo constant; never printed in logs.
DEMO_PASSWORD = os.environ.get("HG_DEMO_PASSWORD", "HGDemo001!SafePass")

ARTIFACT_DIR = PROJECT_ROOT / "data" / "demo_hg_001"
PDF_FILENAME = "HG-DEMO-001_Synthetic_Clinical_Lab_Report_Nov2026.pdf"
CSV_FILENAME = "HG-DEMO-001_Synthetic_13Day_History.csv"
REPORT_JSON_PATH = ARTIFACT_DIR / "hg_demo_001_verification_report.json"


# ===========================================================================
# 1. Pure-Python Standards-Compliant Text PDF Builder (pypdf-extractable)
# ===========================================================================

def _pdf_escape(text: str) -> str:
    """Escape characters for PDF literal strings."""
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def build_synthetic_lab_report_pdf(output_path: Path) -> Path:
    """
    Generate a multi-section, text-based synthetic clinical laboratory report PDF
    compatible with `pypdf.PdfReader(strict=True)` and the HealthGuard RAG chunker.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "SYNTHETIC DEMONSTRATION RECORD - NOT A REAL PATIENT REPORT",
        "Scenario ID: HG-DEMO-001 | HealthGuard AI Clinical Knowledge & RAG Demo",
        "========================================================================",
        "Patient Name: Aarav Sharma (Synthetic Demo HG-DEMO-001)",
        "Patient Identifier: HG-DEMO-001-SYNTHETIC",
        "Date of Birth: 1978-04-14 (Age: 48, Fictional Profile)",
        "Report Date: 2026-11-08 | Ordering Clinic: HealthGuard Synthetic Demo Clinic",
        "------------------------------------------------------------------------",
        "SECTION 1: GLYCEMIC & METABOLIC PANEL (SYNTHETIC LAB RESULTS)",
        "  - Hemoglobin A1c (HbA1c): 7.4 % (Reference Range: 4.0 - 5.6 %)",
        "    Interpretation: Above standard target (< 7.0 % for many non-pregnant",
        "    adults per ADA guidelines). Correlates with recent home fasting blood",
        "    glucose trend increasing from 106 mg/dL to 158 mg/dL.",
        "  - Fasting Plasma Glucose (Laboratory): 138 mg/dL (Reference: 70 - 99 mg/dL)",
        "  - Estimated Average Glucose (eAG): 165 mg/dL",
        "------------------------------------------------------------------------",
        "SECTION 2: CARDIOVASCULAR & LIPID PANEL (SYNTHETIC LAB RESULTS)",
        "  - Office Blood Pressure: 134 / 84 mmHg (Resting seated measurement)",
        "  - Resting Heart Rate: 76 bpm",
        "  - Total Cholesterol: 194 mg/dL (Desirable: < 200 mg/dL)",
        "  - LDL Cholesterol: 112 mg/dL (Near optimal: 100 - 129 mg/dL)",
        "  - HDL Cholesterol: 46 mg/dL",
        "  - Triglycerides: 162 mg/dL",
        "------------------------------------------------------------------------",
        "SECTION 3: RENAL FUNCTION & ELECTROLYTES (SYNTHETIC LAB RESULTS)",
        "  - Serum Creatinine: 0.92 mg/dL (Reference: 0.70 - 1.25 mg/dL)",
        "  - Estimated GFR (eGFR): 94 mL/min/1.73m2 (Normal renal function; safe",
        "    for continued Metformin therapy per standard clinical guidelines).",
        "  - Potassium: 4.3 mEq/L | Sodium: 139 mEq/L",
        "------------------------------------------------------------------------",
        "SECTION 4: CURRENT MEDICATION & SELF-MONITORING PLAN (SYNTHETIC)",
        "  - Active Medication: Metformin XR 500 mg (Synthetic Demo HG-DEMO-001)",
        "  - Regimen: Twice daily with morning and evening meals (08:00 and 20:00 UTC).",
        "  - Lifestyle & Monitoring Notes: Patient tracks daily fasting blood glucose,",
        "    blood pressure, resting heart rate, and daily step counts in HealthGuard AI.",
        "  - Follow-Up Plan: Discuss fasting glucose upward drift and HbA1c of 7.4 %",
        "    with primary care clinician at next scheduled outpatient review.",
        "========================================================================",
        "DISCLAIMER: This document is 100% synthetic demonstration data created",
        "for software verification of HealthGuard AI (Scenario HG-DEMO-001).",
    ]

    # Build content stream using standard Type1 Helvetica font
    stream_ops = ["BT", "/F1 10 Tf", "50 760 Td", "14 TL"]
    for idx, line in enumerate(lines):
        escaped = _pdf_escape(line)
        if idx == 0:
            stream_ops.append(f"({escaped}) Tj")
        else:
            stream_ops.append(f"T* ({escaped}) Tj")
    stream_ops.append("ET")
    stream_bytes = "\n".join(stream_ops).encode("latin-1")

    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
            + stream_bytes
            + b"\nendstream\nendobj\n"
        ),
    ]

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)

    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode("latin-1"))

    buf.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("latin-1")
    )

    output_path.write_bytes(buf.getvalue())
    return output_path


# ===========================================================================
# 2. Synthetic 14-Day Measurement Pattern Builder
# ===========================================================================

def get_14_day_measurement_plan(anchor_utc: datetime) -> list[dict[str, Any]]:
    """
    Construct a 14-day synthetic measurement series ending today (`anchor_utc`).

    Days 1..11 (baseline):
      - Fasting blood glucose steady around 104-112 mg/dL (mean ~108, SD ~2.7)
      - Resting heart rate steady around 68-73 bpm
      - Blood pressure steady around 120-126 / 76-80 mmHg
      - Steps 6,200 - 8,100 steps/day

    Days 12..14 (gradual upward drift on glucose & systolic BP):
      - Fasting blood glucose rises: Day 12 = 128, Day 13 = 138, Day 14 = 158 mg/dL
        With baseline window (5 readings: Days 7..11, mean ~108.4, SD ~2.70) and
        recent window (3 readings: Days 12..14, latest = 158), z-score > 2.0,
        which naturally triggers a `statistical_deviation` monitoring event and an
        in-app notification when Day 14 is posted through `POST /metrics`!
    """
    base_day = anchor_utc.replace(hour=8, minute=30, second=0, microsecond=0)

    # 14 daily values (index 0 = 13 days ago, index 13 = today)
    glucose_series = [105, 108, 104, 110, 107, 109, 106, 111, 105, 112, 108, 128, 138, 158]
    hr_series = [70, 69, 71, 68, 72, 70, 71, 69, 73, 70, 72, 74, 76, 78]
    sys_series = [120, 122, 119, 121, 123, 120, 122, 124, 121, 125, 123, 128, 132, 136]
    dia_series = [76, 78, 75, 77, 78, 76, 77, 79, 77, 80, 78, 81, 83, 85]
    steps_series = [7200, 6850, 7900, 8100, 6400, 7550, 7300, 6950, 7800, 6600, 7100, 5400, 4900, 4650]

    plan: list[dict[str, Any]] = []
    for idx in range(14):
        day_offset = 13 - idx
        dt = base_day - timedelta(days=day_offset)
        plan.append({
            "day_index": idx + 1,
            "recorded_at": dt.isoformat(),
            "is_today": day_offset == 0,
            "blood_glucose": float(glucose_series[idx]),
            "heart_rate": float(hr_series[idx]),
            "systolic": float(sys_series[idx]),
            "diastolic": float(dia_series[idx]),
            "steps": float(steps_series[idx]),
        })
    return plan


def build_historical_csv(plan: list[dict[str, Any]], output_path: Path) -> Path:
    """
    Write Days 1..13 (historical days) to a CSV file compatible with
    `POST /metrics/import-csv` (`parse_health_csv`).
    Day 14 (today) is submitted via live `POST /metrics` and
    `POST /users/{id}/metrics/blood-pressure` so post-save monitoring triggers run.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "metric_type",
        "value",
        "unit",
        "recorded_at",
        "context",
        "notes",
        "measurement_group_id",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for day in plan:
            if day["is_today"]:
                continue
            ts = day["recorded_at"]
            tag = f"[SYNTHETIC {SCENARIO_ID}] Day {day['day_index']} historical record"
            bp_group = str(uuid4())

            writer.writerow({
                "metric_type": "blood_glucose",
                "value": day["blood_glucose"],
                "unit": "mg/dL",
                "recorded_at": ts,
                "context": "fasting",
                "notes": tag,
                "measurement_group_id": "",
            })
            writer.writerow({
                "metric_type": "heart_rate",
                "value": day["heart_rate"],
                "unit": "bpm",
                "recorded_at": ts,
                "context": "resting",
                "notes": tag,
                "measurement_group_id": "",
            })
            writer.writerow({
                "metric_type": "blood_pressure_systolic",
                "value": day["systolic"],
                "unit": "mmHg",
                "recorded_at": ts,
                "context": "resting_morning",
                "notes": tag,
                "measurement_group_id": bp_group,
            })
            writer.writerow({
                "metric_type": "blood_pressure_diastolic",
                "value": day["diastolic"],
                "unit": "mmHg",
                "recorded_at": ts,
                "context": "resting_morning",
                "notes": tag,
                "measurement_group_id": bp_group,
            })
            writer.writerow({
                "metric_type": "steps",
                "value": day["steps"],
                "unit": "steps",
                "recorded_at": ts,
                "context": "daily_total",
                "notes": tag,
                "measurement_group_id": "",
            })

    return output_path


# ===========================================================================
# 3. Safe Scoped Reset (ONLY affects HG-DEMO-001)
# ===========================================================================

def reset_demo_account() -> dict[str, Any]:
    """
    Safely delete ONLY the synthetic user `hg-demo-001@synthetic.healthguard.local`
    and all associated SQLite rows, uploaded PDF files, and ChromaDB user collection.
    Real user accounts and global knowledge vectors are never touched.
    """
    db = SessionLocal()
    try:
        user = (
            db.query(models.UserProfile)
            .filter(models.UserProfile.email == DEMO_EMAIL)
            .first()
        )
        if not user:
            return {"status": "no_existing_demo_user", "email": DEMO_EMAIL}

        user_id = user.id

        # 1. Remove user's ChromaDB collection if present
        try:
            chroma_client = _get_chroma_client()
            col_name = f"{USER_DOC_COLLECTION_PREFIX}{user_id}"
            existing_cols = [c.name for c in chroma_client.list_collections()]
            if col_name in existing_cols:
                chroma_client.delete_collection(col_name)
        except Exception:
            pass

        # 2. Remove physical PDF files stored for this user (if not referenced elsewhere)
        user_docs = (
            db.query(models.MedicalDocument)
            .filter(models.MedicalDocument.user_id == user_id)
            .all()
        )
        upload_root = (PROJECT_ROOT / "storage" / "medical_reports").resolve()
        for doc in user_docs:
            stored_path = Path(doc.stored_path).resolve()
            other_refs = (
                db.query(models.MedicalDocument)
                .filter(
                    models.MedicalDocument.stored_path == doc.stored_path,
                    models.MedicalDocument.user_id != user_id,
                )
                .count()
            )
            if other_refs == 0 and upload_root in stored_path.parents and stored_path.is_file():
                try:
                    stored_path.unlink()
                except OSError:
                    pass

        # 3. Delete dependent records that do not have ORM cascade on UserProfile
        db.query(models.DocumentIndexStatus).filter(
            models.DocumentIndexStatus.user_id == user_id
        ).delete(synchronize_session=False)
        db.query(models.MedicalDocument).filter(
            models.MedicalDocument.user_id == user_id
        ).delete(synchronize_session=False)
        db.query(models.CSVImport).filter(
            models.CSVImport.user_id == user_id
        ).delete(synchronize_session=False)
        db.query(models.MedicationReminder).filter(
            models.MedicationReminder.user_id == user_id
        ).delete(synchronize_session=False)

        # 4. Delete UserProfile (cascades HealthMetric, MonitoringEvent, Medication, AgentExecutionAudit)
        db.delete(user)
        db.commit()

        return {"status": "deleted", "deleted_user_id": user_id, "email": DEMO_EMAIL}
    finally:
        db.close()


# ===========================================================================
# 4. End-to-End Setup & Execution via Authenticated FastAPI Endpoints
# ===========================================================================

def setup_and_verify_demo() -> dict[str, Any]:
    """
    Execute the complete HG-DEMO-001 setup and verification workflow.
    """
    reset_info = reset_demo_account()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    client = TestClient(app)
    report: dict[str, Any] = {
        "scenario_id": SCENARIO_ID,
        "generated_at_utc": now_utc.isoformat() + "Z",
        "reset_previous": reset_info,
        "steps": {},
    }

    # ------------------------------------------------------------------
    # Step 1: Register & Authenticate Synthetic User via /auth/register & /auth/login
    # ------------------------------------------------------------------
    reg_res = client.post(
        "/auth/register",
        json={
            "full_name": DEMO_FULL_NAME,
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
        },
    )
    assert reg_res.status_code == 200, f"Registration failed: {reg_res.text}"
    user_profile = reg_res.json()
    user_id = user_profile["id"]

    login_res = client.post(
        "/auth/login",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_res = client.get("/auth/me", headers=headers)
    assert me_res.status_code == 200
    report["steps"]["1_user_registration"] = {
        "status": "passed",
        "user_id": user_id,
        "full_name": user_profile["full_name"],
        "email": user_profile["email"],
    }

    # ------------------------------------------------------------------
    # Step 2 & 3: Populate 14-Day Measurement History
    #   - Days 1..13 via POST /metrics/import-csv
    #   - Day 14 (today) via POST /metrics & POST /users/{id}/metrics/blood-pressure
    #     so post-save monitoring & notification publication execute naturally.
    # ------------------------------------------------------------------
    plan = get_14_day_measurement_plan(now_utc)
    csv_path = build_historical_csv(plan, ARTIFACT_DIR / CSV_FILENAME)

    with open(csv_path, "rb") as f:
        csv_res = client.post(
            "/metrics/import-csv",
            headers=headers,
            files={"file": (CSV_FILENAME, f, "text/csv")},
        )
    assert csv_res.status_code == 200, f"CSV import failed: {csv_res.text}"
    csv_data = csv_res.json()

    today_entry = plan[-1]
    today_tag = f"[SYNTHETIC {SCENARIO_ID}] Day 14 live baseline-shift measurement"

    # Post today's fasting blood glucose (158 mg/dL -> triggers statistical_deviation!)
    bg_res = client.post(
        f"/metrics?user_id={user_id}",
        headers=headers,
        json={
            "metric_type": "blood_glucose",
            "value": today_entry["blood_glucose"],
            "unit": "mg/dL",
            "source": "manual",
            "context": "fasting",
            "notes": today_tag,
        },
    )
    assert bg_res.status_code == 200, f"Blood glucose post failed: {bg_res.text}"

    # Post today's heart rate
    hr_res = client.post(
        f"/metrics?user_id={user_id}",
        headers=headers,
        json={
            "metric_type": "heart_rate",
            "value": today_entry["heart_rate"],
            "unit": "bpm",
            "source": "manual",
            "context": "resting",
            "notes": today_tag,
        },
    )
    assert hr_res.status_code == 200

    # Post today's steps
    st_res = client.post(
        f"/metrics?user_id={user_id}",
        headers=headers,
        json={
            "metric_type": "steps",
            "value": today_entry["steps"],
            "unit": "steps",
            "source": "manual",
            "context": "daily_total",
            "notes": today_tag,
        },
    )
    assert st_res.status_code == 200

    # Post today's composite blood pressure
    bp_res = client.post(
        f"/users/{user_id}/metrics/blood-pressure",
        headers=headers,
        json={
            "systolic": today_entry["systolic"],
            "diastolic": today_entry["diastolic"],
            "unit": "mmHg",
            "source": "manual",
            "context": "resting_morning",
            "notes": today_tag,
        },
    )
    assert bp_res.status_code == 200

    # Verify analytics & trend endpoints
    metrics_list = client.get(f"/users/{user_id}/metrics?limit=500", headers=headers).json()
    bg_trend = client.get(
        f"/users/{user_id}/metrics/blood_glucose/trend", headers=headers
    ).json()
    bg_longitudinal = client.get(
        f"/users/{user_id}/metrics/blood_glucose/longitudinal", headers=headers
    ).json()

    report["steps"]["2_3_measurements_and_analytics"] = {
        "status": "passed",
        "csv_imported_count": csv_data["imported_count"],
        "csv_failed_count": csv_data["failed_count"],
        "total_metrics_stored": len(metrics_list),
        "blood_glucose_trend_direction": bg_trend.get("trend", {}).get("direction"),
        "blood_glucose_z_score": bg_longitudinal.get("analysis", {})
        .get("anomaly", {})
        .get("z_score"),
        "blood_glucose_anomaly_status": bg_longitudinal.get("analysis", {})
        .get("anomaly", {})
        .get("status"),
    }

    # ------------------------------------------------------------------
    # Step 4 & 5: Generate Synthetic PDF Lab Report, Upload & Verify RAG Index
    # ------------------------------------------------------------------
    pdf_path = build_synthetic_lab_report_pdf(ARTIFACT_DIR / PDF_FILENAME)
    with open(pdf_path, "rb") as f:
        up_res = client.post(
            "/documents/upload",
            headers=headers,
            files={"file": (PDF_FILENAME, f, "application/pdf")},
        )
    assert up_res.status_code == 201, f"PDF upload failed: {up_res.text}"
    uploaded_doc = up_res.json()
    doc_id = uploaded_doc["id"]

    # Verify index status via GET /rag/documents (and call /index if needed)
    rag_docs = client.get("/rag/documents", headers=headers).json()
    doc_entry = next((d for d in rag_docs["documents"] if d["id"] == doc_id), None)
    if not doc_entry or doc_entry.get("index_status") != "indexed":
        idx_res = client.post(f"/rag/documents/{doc_id}/index", headers=headers)
        assert idx_res.status_code == 200, f"Document indexing failed: {idx_res.text}"
        rag_docs = client.get("/rag/documents", headers=headers).json()
        doc_entry = next((d for d in rag_docs["documents"] if d["id"] == doc_id), None)

    report["steps"]["4_5_synthetic_pdf_upload_and_index"] = {
        "status": "passed",
        "document_id": doc_id,
        "filename": uploaded_doc["filename"],
        "file_size_bytes": uploaded_doc["file_size"],
        "index_status": doc_entry["index_status"] if doc_entry else "unknown",
        "chunk_count": doc_entry["chunk_count"] if doc_entry else None,
    }

    # ------------------------------------------------------------------
    # Step 6 & 7: Create Fictional Medication, Schedule & Dose Occurrence History
    # ------------------------------------------------------------------
    start_date_date = (now_utc - timedelta(days=7)).date()
    med_res = client.post(
        f"/medications?user_id={user_id}",
        headers=headers,
        json={
            "name": "Metformin XR (Synthetic Demo HG-DEMO-001)",
            "dosage": "500 mg",
            "frequency": "Twice daily with meals",
            "instructions": "SYNTHETIC DEMO RECORD ONLY - Take at 08:00 UTC and 20:00 UTC.",
            "start_date": start_date_date.isoformat(),
            "end_date": None,
        },
    )
    assert med_res.status_code == 200, f"Medication create failed: {med_res.text}"
    medication = med_res.json()
    med_id = medication["id"]

    # Choose two daily times:
    # - One 3 hours ago (so today's first dose is already past the 60-min grace period -> 'overdue',
    #   leaving an unconfirmed dose ready for the live demo AND generating a pending reminder!)
    # - One 12 hours away (so a second dose also exists on the schedule)
    overdue_dt = now_utc - timedelta(hours=3)
    second_dt = (overdue_dt + timedelta(hours=12))
    t1 = f"{overdue_dt.hour:02d}:{overdue_dt.minute:02d}"
    t2 = f"{second_dt.hour:02d}:{second_dt.minute:02d}"
    schedule_times = sorted(list({t1, t2}))

    sched_res = client.post(
        f"/medications/{med_id}/schedule",
        headers=headers,
        json={
            "schedule_type": "daily",
            "times": schedule_times,
            "weekdays": [],
            "timezone": "UTC",
        },
    )
    assert sched_res.status_code == 200, f"Schedule create failed: {sched_res.text}"

    # Because POST /medications/{id}/schedule sets schedule.effective_from = datetime.utcnow(),
    # we align `effective_from` to `medication.start_date` and invoke the backend's own
    # `generate_occurrences_for_schedule` service so the past 7 days of occurrences exist,
    # then confirm past doses exclusively through `PATCH /medications/occurrences/{id}`.
    db = SessionLocal()
    try:
        sched_row = (
            db.query(models.MedicationSchedule)
            .filter(
                models.MedicationSchedule.medication_id == med_id,
                models.MedicationSchedule.is_active.is_(True),
            )
            .first()
        )
        med_row = db.query(models.Medication).filter(models.Medication.id == med_id).first()
        if sched_row and med_row:
            sched_row.effective_from = med_row.start_date
            db.flush()
            generate_occurrences_for_schedule(
                db=db,
                schedule=sched_row,
                start=med_row.start_date,
                end=now_utc + timedelta(days=7),
            )
            refresh_occurrence_statuses(db, user_id, now_utc)
            db.commit()
    finally:
        db.close()

    # Fetch occurrences via GET /medications/{id}/occurrences and confirm historical ones via PATCH
    occs_res = client.get(
        f"/medications/{med_id}/occurrences?days_back=7&days_ahead=2",
        headers=headers,
    )
    assert occs_res.status_code == 200
    occurrences = occs_res.json()["occurrences"]

    past_occs = [
        o for o in occurrences
        if datetime.fromisoformat(o["scheduled_at"]) < (now_utc - timedelta(minutes=65))
    ]
    # Keep the most recent past occurrence UNCONFIRMED ('overdue') so:
    #   1) Workflow B generates a real pending MedicationReminder for it, and
    #   2) Tomorrow's live presenter can click "Taken" on it during the demo!
    confirmed_taken = 0
    confirmed_skipped = 0
    for idx, occ in enumerate(past_occs[:-1]):
        status_choice = "skipped" if idx == 4 else "taken"
        patch_res = client.patch(
            f"/medications/occurrences/{occ['id']}",
            headers=headers,
            json={
                "status": status_choice,
                "notes": f"[SYNTHETIC {SCENARIO_ID}] Confirmed via PATCH /medications/occurrences",
            },
        )
        assert patch_res.status_code == 200
        if status_choice == "taken":
            confirmed_taken += 1
        else:
            confirmed_skipped += 1

    adh_v2 = client.get(f"/medications/{med_id}/adherence-v2", headers=headers).json()
    today_doses = client.get(f"/medications/user/{user_id}/today", headers=headers).json()

    report["steps"]["6_7_medication_and_adherence"] = {
        "status": "passed",
        "medication_id": med_id,
        "medication_name": medication["name"],
        "schedule_times_utc": schedule_times,
        "confirmed_taken_count": confirmed_taken,
        "confirmed_skipped_count": confirmed_skipped,
        "unconfirmed_overdue_for_live_demo": len(past_occs) - (confirmed_taken + confirmed_skipped),
        "overall_adherence_pct": adh_v2.get("overall", {}).get("adherence_percentage"),
        "todays_doses": today_doses.get("doses", []),
    }

    # ------------------------------------------------------------------
    # Step 8: Run Actual Agent Workflows (Assess, Medication-Check, Summary)
    #         AND Direct Experimental Diabetes Screening (/ml/diabetes/predict-v3)
    # ------------------------------------------------------------------
    ml_features_payload = {
        "Pregnancies": 0,
        "Glucose": 158.0,
        "BloodPressure": 85.0,
        "SkinThickness": 26.0,
        "Insulin": 115.0,
        "BMI": 28.4,
        "DiabetesPedigreeFunction": 0.52,
        "Age": 48,
    }
    ml_v3_res = client.post(
        "/ml/diabetes/predict-v3",
        headers=headers,
        json=ml_features_payload,
    )
    assert ml_v3_res.status_code == 200, f"Diabetes v3 prediction failed: {ml_v3_res.text}"
    ml_v3_data = ml_v3_res.json()

    assess_res = client.post(
        "/orchestration/assess",
        headers=headers,
        json={
            "metric_type": "blood_glucose",
            "include_knowledge": True,
            "include_adherence": True,
            "experimental_ml": True,
            "ml_features": ml_features_payload,
        },
    )
    assert assess_res.status_code == 200, f"Orchestration assess failed: {assess_res.text}"
    assess_data = assess_res.json()

    med_check_res = client.post(
        "/orchestration/medication-check",
        headers=headers,
        json={"force_refresh": True},
    )
    assert med_check_res.status_code == 200, f"Medication check failed: {med_check_res.text}"
    med_check_data = med_check_res.json()

    summary_res = client.get(
        "/orchestration/summary?primary_metric=blood_glucose",
        headers=headers,
    )
    assert summary_res.status_code == 200, f"Summary workflow failed: {summary_res.text}"
    summary_data = summary_res.json()

    report["steps"]["8_agent_workflows_and_ml_v3"] = {
        "status": "passed",
        "direct_ml_v3_screening": {
            "prediction": ml_v3_data["prediction"],
            "model_score": ml_v3_data["model_score"],
            "threshold": ml_v3_data["threshold"],
            "screening_result": ml_v3_data["screening_result"],
            "model_version": ml_v3_data["model_version"],
        },
        "workflow_a_assess_state": assess_data["orchestration_state"],
        "workflow_a_monitoring_status": (assess_data.get("monitoring") or {}).get("status"),
        "workflow_a_risk_level": (assess_data.get("risk_assessment") or {}).get("risk_level"),
        "workflow_a_experimental_ml_included": (assess_data.get("risk_assessment") or {}).get("is_experimental"),
        "workflow_b_medication_state": med_check_data["orchestration_state"],
        "workflow_b_medication_summary": (med_check_data.get("medication") or {}).get("summary"),
        "workflow_c_summary_state": summary_data["orchestration_state"],
    }

    # ------------------------------------------------------------------
    # Step 9: Verify Execution History, Monitoring Events, Notifications & Reminders
    # ------------------------------------------------------------------
    history_data = client.get("/orchestration/history", headers=headers).json()
    alerts_data = client.get("/orchestration/alerts", headers=headers).json()
    events_data = client.get(
        f"/users/{user_id}/monitoring/events", headers=headers
    ).json()
    notifs_data = client.get(
        f"/users/{user_id}/notifications", headers=headers
    ).json()
    reminders_data = client.get("/reminders/medications", headers=headers).json()

    report["steps"]["9_audit_events_notifications"] = {
        "status": "passed",
        "execution_history_count": len(history_data),
        "workflows_logged": [h["workflow_type"] for h in history_data],
        "monitoring_events_total": events_data["total"],
        "monitoring_events": [
            {
                "id": e["id"],
                "metric_type": e["metric_type"],
                "event_type": e["event_type"],
                "event_level": e["event_level"],
                "notification_status": e["notification_status"],
            }
            for e in events_data["events"]
        ],
        "delivered_notifications_total": notifs_data["total"],
        "pending_medication_reminders_total": len(
            alerts_data.get("pending_medication_reminders", [])
        ),
        "reminders_total": reminders_data["total"],
    }

    # ------------------------------------------------------------------
    # Step 10: Verify Medical RAG Retrieval & Source Citations
    # ------------------------------------------------------------------
    rag_status_data = client.get("/rag/status", headers=headers).json()

    # Semantic search directly against the user's indexed PDF report (/rag/search)
    search_user_res = client.get(
        "/rag/search",
        headers=headers,
        params={"query": "HbA1c fasting plasma glucose eGFR Metformin", "source": "user", "n_results": 3},
    )
    assert search_user_res.status_code == 200
    search_user_data = search_user_res.json()

    # Semantic search against global clinical guidelines (/rag/search)
    search_global_res = client.get(
        "/rag/search",
        headers=headers,
        params={"query": "HbA1c glycemic target diabetes guidelines", "source": "global", "n_results": 3},
    )
    assert search_global_res.status_code == 200
    search_global_data = search_global_res.json()

    # Full RAG Q&A endpoint (/rag/ask)
    ask_res = client.post(
        "/rag/ask",
        headers=headers,
        json={
            "question": "What does my uploaded lab report say about my HbA1c and eGFR results, and what is HbA1c?",
            "include_global_knowledge": True,
            "include_user_documents": True,
            "document_id": doc_id,
            "n_results": 4,
        },
    )
    ask_data = ask_res.json() if ask_res.status_code == 200 else {"http_status": ask_res.status_code, "detail": ask_res.json().get("detail")}

    report["steps"]["10_rag_verification"] = {
        "status": "passed" if (
            ask_res.status_code == 200
            and bool(ask_data.get("answer"))
            and bool(ask_data.get("sources"))
        ) else "partial",
        "rag_status": rag_status_data,
        "user_document_chunks_retrieved": len(search_user_data.get("results", [])),
        "user_document_top_match_preview": (
            search_user_data["results"][0]["text"][:180]
            if search_user_data.get("results")
            else None
        ),
        "global_knowledge_chunks_retrieved": len(search_global_data.get("results", [])),
        "global_top_match_title": (
            search_global_data["results"][0]["metadata"].get("title")
            if search_global_data.get("results")
            else None
        ),
        "rag_ask_result": {
            "http_status": ask_res.status_code,
            "answered": ask_res.status_code == 200 and bool(ask_data.get("answer")),
            "sources_count": len(ask_data.get("sources", [])) if isinstance(ask_data, dict) else 0,
            "note": (
                "Full LLM answer generated with citations"
                if ask_res.status_code == 200
                else "ChromaDB semantic retrieval verified; start local Ollama (`ollama serve`) before live Q&A generation."
            ),
        },
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def verify_existing_demo() -> dict[str, Any]:
    """Inspect and report on the existing HG-DEMO-001 account without mutating data."""
    db = SessionLocal()
    try:
        user = (
            db.query(models.UserProfile)
            .filter(models.UserProfile.email == DEMO_EMAIL)
            .first()
        )
        if not user:
            return {"status": "missing", "message": "Run with --setup first."}

        metrics_count = (
            db.query(models.HealthMetric)
            .filter(models.HealthMetric.user_id == user.id)
            .count()
        )
        events_count = (
            db.query(models.MonitoringEvent)
            .filter(models.MonitoringEvent.user_id == user.id)
            .count()
        )
        docs_count = (
            db.query(models.MedicalDocument)
            .filter(models.MedicalDocument.user_id == user.id)
            .count()
        )
        meds_count = (
            db.query(models.Medication)
            .filter(models.Medication.user_id == user.id)
            .count()
        )
        audits_count = (
            db.query(models.AgentExecutionAudit)
            .filter(models.AgentExecutionAudit.user_id == user.id)
            .count()
        )
        reminders_count = (
            db.query(models.MedicationReminder)
            .filter(models.MedicationReminder.user_id == user.id)
            .count()
        )
        return {
            "status": "present",
            "scenario_id": SCENARIO_ID,
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "metrics_count": metrics_count,
            "monitoring_events_count": events_count,
            "documents_count": docs_count,
            "medications_count": meds_count,
            "agent_audits_count": audits_count,
            "medication_reminders_count": reminders_count,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Setup, verify, or reset the HG-DEMO-001 synthetic patient scenario."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--setup", action="store_true", help="Reset and populate HG-DEMO-001 (default)")
    group.add_argument("--verify", action="store_true", help="Verify existing HG-DEMO-001 state")
    group.add_argument("--reset", action="store_true", help="Remove ONLY the HG-DEMO-001 demo user and data")
    args = parser.parse_args()

    if args.reset:
        res = reset_demo_account()
        print(json.dumps(res, indent=2))
    elif args.verify:
        res = verify_existing_demo()
        print(json.dumps(res, indent=2))
    else:
        res = setup_and_verify_demo()
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

