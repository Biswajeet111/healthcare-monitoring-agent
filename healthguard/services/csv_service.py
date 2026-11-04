import csv
import io
from datetime import datetime

from fastapi import HTTPException

from healthguard.schemas import HealthMetricCreate


MAX_CSV_SIZE = 5 * 1024 * 1024  # 5 MB


def parse_health_csv(content: bytes):
    if len(content) > MAX_CSV_SIZE:
        raise HTTPException(status_code=413, detail="CSV exceeds 5 MB limit")

    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        required_columns = {"metric_type", "value", "unit"}

        if not reader.fieldnames or not required_columns.issubset(
            set(reader.fieldnames)
        ):
            raise HTTPException(
                status_code=400,
                detail="CSV must contain metric_type, value and unit columns"
            )

        records = []
        errors = []

        for row_number, row in enumerate(reader, start=2):
            try:
                data = HealthMetricCreate.model_validate({
                    "metric_type": row.get("metric_type", "").strip(),
                    "value": float(row.get("value", "")),
                    "unit": row.get("unit", "").strip(),
                    "source": "imported",
                    "context": row.get("context") or None,
                    "notes": row.get("notes") or None,
                    "measurement_group_id": row.get("measurement_group_id") or None
                })

                recorded_at = None
                if row.get("recorded_at"):
                    recorded_at = datetime.fromisoformat(
                        row["recorded_at"].strip()
                    )

                records.append({
                    **data.model_dump(),
                    "recorded_at": recorded_at
                })

            except Exception as exc:
                errors.append({
                    "row": row_number,
                    "error": str(exc)
                })

        return {
            "records": records,
            "errors": errors
        }

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="CSV must use UTF-8 encoding"
        )