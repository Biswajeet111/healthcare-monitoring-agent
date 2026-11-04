GLUCOSE_CONVERSION_FACTOR = 18.0182


def normalize_measurement(metric_type, value, unit):
    """
    Normalize supported measurements into canonical units.
    Original values should be preserved separately.
    """

    if value <= 0:
        raise ValueError("Measurement must be positive")

    if metric_type == "blood_glucose":
        if unit == "mmol/L":
            return round(value * GLUCOSE_CONVERSION_FACTOR, 2), "mg/dL"

        if unit == "mg/dL":
            return value, "mg/dL"

    canonical_units = {
        "blood_pressure_systolic": "mmHg",
        "blood_pressure_diastolic": "mmHg",
        "heart_rate": "bpm",
        "weight": "kg",
        "height": "cm",
        "steps": "steps",
        "sleep_duration": "hours",
    }

    expected_unit = canonical_units.get(metric_type)

    if expected_unit:
        if unit != expected_unit:
            raise ValueError(
                f"Expected {expected_unit}, received {unit}"
            )

        return value, expected_unit

    raise ValueError(f"Unsupported metric type: {metric_type}")