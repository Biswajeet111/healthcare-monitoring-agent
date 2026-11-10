import math
import re
from typing import Any


class MonitoringSafetyError(ValueError):
    """Raised when monitoring data violates a safety requirement."""


ALLOWED_PRIORITIES = {
    "routine_tracking",
    "review_recommended",
    "more_data_needed",
}

ALLOWED_STATUSES = {
    "within_configured_threshold",
    "statistical_deviation_detected",
    "insufficient_baseline_variability",
}

ALLOWED_DIRECTIONS = {
    "increasing",
    "decreasing",
    "unchanged",
}

EXPECTED_PRIORITIES = {
    "within_configured_threshold": "routine_tracking",
    "statistical_deviation_detected": "review_recommended",
    "insufficient_baseline_variability": "more_data_needed",
}

REQUIRED_DISCLAIMER_PHRASES = (
    "not medical urgency",
    "does not establish medical safety",
    "does not diagnose",
)


# ============================================================
# UNSAFE MEDICAL LANGUAGE PATTERNS
# ============================================================

# Conservative screening for unsupported clinical claims.
# This is a defense-in-depth check, not a complete medical
# language safety classifier.

UNSAFE_PATTERNS = (
    # Unsupported diagnosis statements
    r"\byou (?:have|are suffering from) (?:diabetes|hypertension|heart disease)\b",

    # Unsupported certainty claims
    r"\b(?:definitely|certainly) (?:have|indicates) (?:diabetes|hypertension|disease)\b",

    # Medication and dosage instructions
    # FIX: Supports "Stop taking your medication"
    r"\b(?:start|stop|increase|decrease|double)\s+(?:taking\s+)?(?:your\s+)?(?:medication|medicine|insulin|dose|dosage)\b",

    # Unsupported safety claims
    r"\bno (?:medical|health) risk\b",
    r"\bmedically safe\b",
    r"\b(?:guaranteed|definitely) healthy\b",
)


# ============================================================
# NUMERIC VALIDATION
# ============================================================

def _finite_number(value: Any, field: str) -> float:
    """
    Validate that a value is a finite numeric measurement.

    Rejects:
    - Boolean values
    - Strings
    - None
    - NaN
    - Positive/negative infinity
    """

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise MonitoringSafetyError(
            f"{field} must be a finite number."
        )

    try:
        if not math.isfinite(value):
            raise MonitoringSafetyError(
                f"{field} must be a finite number."
            )

        return float(value)

    except (OverflowError, ValueError, TypeError) as exc:
        raise MonitoringSafetyError(
            f"{field} must be a finite number."
        ) from exc


# ============================================================
# STRUCTURE VALIDATION
# ============================================================

def _required_dict(parent: dict, key: str) -> dict:
    """
    Ensure a required dictionary section exists.
    """

    value = parent.get(key)

    if not isinstance(value, dict):
        raise MonitoringSafetyError(
            f"Missing or invalid section: {key}"
        )

    return value


def _required_text(parent: dict, key: str) -> str:
    """
    Ensure a required text field is non-empty.
    """

    value = parent.get(key)

    if not isinstance(value, str) or not value.strip():
        raise MonitoringSafetyError(
            f"{key} must be a non-empty string."
        )

    return value.strip()


# ============================================================
# UNSAFE LANGUAGE SCREENING
# ============================================================

def _check_unsafe_language(text: str) -> None:
    """
    Detect selected unsupported clinical statements,
    medication instructions, and safety claims.

    This is a limited rule-based filter and does not
    guarantee detection of all unsafe medical language.
    """

    for pattern in UNSAFE_PATTERNS:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            raise MonitoringSafetyError(
                "Unsupported clinical or treatment claim detected."
            )


# ============================================================
# MAIN MONITORING SAFETY VALIDATOR
# ============================================================

def validate_monitoring_decision(
    decision: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate a deterministic monitoring agent decision.

    Validation includes:
    1. Input structure
    2. Monitoring priority consistency
    3. Statistical consistency
    4. Selected unsafe-language patterns
    5. Required medical disclaimers

    This validator does not establish clinical correctness
    or guarantee medical safety.
    """

    # --------------------------------------------------------
    # 1. Validate input structure
    # --------------------------------------------------------

    if not isinstance(decision, dict):
        raise MonitoringSafetyError(
            "Monitoring decision must be a dictionary."
        )

    metric_type = _required_text(
        decision,
        "metric_type",
    )

    unit = _required_text(
        decision,
        "unit",
    )

    priority = _required_text(
        decision,
        "monitoring_priority",
    )

    status = _required_text(
        decision,
        "statistical_status",
    )

    direction = _required_text(
        decision,
        "observed_direction",
    )

    summary = _required_text(
        decision,
        "summary",
    )

    disclaimer = _required_text(
        decision,
        "disclaimer",
    )

    # --------------------------------------------------------
    # 2. Validate monitoring priority
    # --------------------------------------------------------

    if priority not in ALLOWED_PRIORITIES:
        raise MonitoringSafetyError(
            "Unsupported monitoring priority."
        )

    if status not in ALLOWED_STATUSES:
        raise MonitoringSafetyError(
            "Unsupported statistical status."
        )

    if direction not in ALLOWED_DIRECTIONS:
        raise MonitoringSafetyError(
            "Unsupported observed direction."
        )

    expected_priority = EXPECTED_PRIORITIES[status]

    if priority != expected_priority:
        raise MonitoringSafetyError(
            "Monitoring priority contradicts statistical status."
        )

    # --------------------------------------------------------
    # 3. Validate medical disclaimer
    # --------------------------------------------------------

    disclaimer_lower = disclaimer.lower()

    for phrase in REQUIRED_DISCLAIMER_PHRASES:

        if phrase not in disclaimer_lower:
            raise MonitoringSafetyError(
                "Required medical disclaimer is incomplete."
            )

    # --------------------------------------------------------
    # 4. Validate recommended actions
    # --------------------------------------------------------

    actions = decision.get("recommended_actions")

    if (
        not isinstance(actions, list)
        or len(actions) == 0
        or any(
            not isinstance(action, str)
            or not action.strip()
            for action in actions
        )
    ):
        raise MonitoringSafetyError(
            "Recommended actions must be a non-empty list of strings."
        )

    # --------------------------------------------------------
    # 5. Validate statistical evidence
    # --------------------------------------------------------

    evidence = _required_dict(
        decision,
        "evidence",
    )

    baseline_mean = _finite_number(
        evidence.get("baseline_mean"),
        "baseline_mean",
    )

    baseline_std = _finite_number(
        evidence.get("baseline_standard_deviation"),
        "baseline_standard_deviation",
    )

    recent_mean = _finite_number(
        evidence.get("recent_mean"),
        "recent_mean",
    )

    latest_value = _finite_number(
        evidence.get("latest_value"),
        "latest_value",
    )

    absolute_change = _finite_number(
        evidence.get("absolute_change"),
        "absolute_change",
    )

    threshold = _finite_number(
        evidence.get("configured_threshold"),
        "configured_threshold",
    )

    if baseline_std < 0:
        raise MonitoringSafetyError(
            "Baseline standard deviation cannot be negative."
        )

    if threshold <= 0:
        raise MonitoringSafetyError(
            "Configured threshold must be positive."
        )

    # --------------------------------------------------------
    # 6. Validate measurement change consistency
    # --------------------------------------------------------

    # The upstream longitudinal analyzer rounds
    # reported means and absolute changes to 3 decimals.

    tolerance = 0.002

    expected_change = recent_mean - baseline_mean

    if not math.isclose(
        absolute_change,
        expected_change,
        rel_tol=1e-9,
        abs_tol=tolerance,
    ):
        raise MonitoringSafetyError(
            "Absolute change contradicts baseline and recent means."
        )

    # --------------------------------------------------------
    # 7. Validate observed direction
    # --------------------------------------------------------

    if absolute_change > tolerance:
        expected_direction = "increasing"

    elif absolute_change < -tolerance:
        expected_direction = "decreasing"

    else:
        expected_direction = "unchanged"

    # Small changes may disappear because of rounding.

    if (
        expected_direction != "unchanged"
        and direction != expected_direction
    ):
        raise MonitoringSafetyError(
            "Observed direction contradicts measurement change."
        )

    # --------------------------------------------------------
    # 8. Validate statistical anomaly consistency
    # --------------------------------------------------------

    z_score = evidence.get("z_score")

    if status == "insufficient_baseline_variability":

        if z_score is not None:
            raise MonitoringSafetyError(
                "Zero-variance status must have a null z-score."
            )

        if baseline_std != 0:
            raise MonitoringSafetyError(
                "Insufficient baseline variability requires zero standard deviation."
            )

    else:

        z_score = _finite_number(
            z_score,
            "z_score",
        )

        if baseline_std <= 0:
            raise MonitoringSafetyError(
                "A z-score requires positive baseline variability."
            )

        # Allow for 3-decimal rounding of the z-score.

        if status == "statistical_deviation_detected":

            if abs(z_score) < threshold - 0.001:
                raise MonitoringSafetyError(
                    "Deviation status contradicts z-score."
                )

        else:

            if abs(z_score) >= threshold + 0.001:
                raise MonitoringSafetyError(
                    "Routine status contradicts z-score."
                )

    # --------------------------------------------------------
    # 9. Screen unsafe medical language
    # --------------------------------------------------------

    _check_unsafe_language(summary)

    for action in actions:
        _check_unsafe_language(action)

    # --------------------------------------------------------
    # 10. Return validated safety report
    # --------------------------------------------------------

    return {
        "safe": True,

        "validation_status": "passed",

        "metric_type": metric_type,

        "unit": unit,

        "monitoring_priority": priority,

        "statistical_status": status,

        "checks": {
            "structure": "passed",
            "priority_consistency": "passed",
            "statistical_consistency": "passed",
            "language_screening": "passed",
            "disclaimer": "passed",
        },

        "limitations": (
            "This validator checks deterministic rules and selected "
            "unsafe phrases. Passing validation does not establish "
            "clinical safety or guarantee detection of all unsafe language."
        ),
    }