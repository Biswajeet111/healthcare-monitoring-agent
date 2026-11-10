import hashlib
import json
import math

from datetime import datetime, timedelta, timezone
from typing import Any


class MonitoringEventDeduplicationError(ValueError):
    """Raised when event deduplication inputs are invalid."""


DEFAULT_COOLDOWN_MINUTES = 60

MAX_COOLDOWN_MINUTES = 10080  # Seven days

ALLOWED_EVENT_TYPES = {
    "statistical_deviation",
    "insufficient_baseline_variability",
    "routine_monitoring",
}

EXPECTED_EVENT_LEVELS = {
    "statistical_deviation": "review",
    "insufficient_baseline_variability": "informational",
    "routine_monitoring": "routine",
}

EXPECTED_PRIORITIES = {
    "statistical_deviation": "review_recommended",
    "insufficient_baseline_variability": "more_data_needed",
    "routine_monitoring": "routine_tracking",
}

EXPECTED_STATUSES = {
    "statistical_deviation": "statistical_deviation_detected",
    "insufficient_baseline_variability": "insufficient_baseline_variability",
    "routine_monitoring": "within_configured_threshold",
}


# ============================================================
# INPUT VALIDATION
# ============================================================

def _required_text(parent: dict, key: str) -> str:
    value = parent.get(key)

    if not isinstance(value, str) or not value.strip():
        raise MonitoringEventDeduplicationError(
            f"{key} must be a non-empty string."
        )

    return value.strip()


def _validate_user_id(user_id: Any) -> int:
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise MonitoringEventDeduplicationError(
            "user_id must be a positive integer."
        )

    return user_id


def _validate_cooldown(cooldown_minutes: Any) -> int:
    if (
        isinstance(cooldown_minutes, bool)
        or not isinstance(cooldown_minutes, int)
        or not 1 <= cooldown_minutes <= MAX_COOLDOWN_MINUTES
    ):
        raise MonitoringEventDeduplicationError(
            "cooldown_minutes must be an integer between "
            f"1 and {MAX_COOLDOWN_MINUTES}."
        )

    return cooldown_minutes


def _parse_datetime(value: Any, field: str) -> datetime:
    """
    Parse a timezone-aware datetime or ISO 8601 string.

    Naive timestamps are rejected to prevent timezone ambiguity.
    """

    if isinstance(value, datetime):
        parsed = value

    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise MonitoringEventDeduplicationError(
                f"{field} must be a valid ISO 8601 datetime."
            ) from exc

    else:
        raise MonitoringEventDeduplicationError(
            f"{field} must be a datetime or ISO 8601 string."
        )

    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise MonitoringEventDeduplicationError(
            f"{field} must include timezone information."
        )

    return parsed.astimezone(timezone.utc)


def _validate_event(event: Any) -> dict[str, str]:
    """
    Validate the identifying fields of a classified event.

    Only events from the trusted backend classifier should
    be passed to this function.
    """

    if not isinstance(event, dict):
        raise MonitoringEventDeduplicationError(
            "Event must be a dictionary."
        )

    if event.get("classification_status") != "completed":
        raise MonitoringEventDeduplicationError(
            "Event classification is incomplete."
        )

    event_type = _required_text(event, "event_type")
    event_level = _required_text(event, "event_level")
    metric_type = _required_text(event, "metric_type")
    unit = _required_text(event, "unit")
    priority = _required_text(event, "monitoring_priority")
    status = _required_text(event, "statistical_status")

    if event_type not in ALLOWED_EVENT_TYPES:
        raise MonitoringEventDeduplicationError(
            "Unsupported event type."
        )

    if event_level != EXPECTED_EVENT_LEVELS[event_type]:
        raise MonitoringEventDeduplicationError(
            "Event level contradicts event type."
        )

    if priority != EXPECTED_PRIORITIES[event_type]:
        raise MonitoringEventDeduplicationError(
            "Monitoring priority contradicts event type."
        )

    if status != EXPECTED_STATUSES[event_type]:
        raise MonitoringEventDeduplicationError(
            "Statistical status contradicts event type."
        )

    return {
        "event_type": event_type,
        "event_level": event_level,
        "metric_type": metric_type,
        "unit": unit,
        "monitoring_priority": priority,
        "statistical_status": status,
    }


# ============================================================
# EVENT FINGERPRINT
# ============================================================

def generate_event_fingerprint(
    user_id: int,
    event: dict[str, Any],
) -> str:
    """
    Generate a stable SHA-256 fingerprint.

    The fingerprint identifies a monitoring condition
    for one user and measurement unit.

    Measurement values and timestamps are deliberately
    excluded so repeated occurrences of the same
    condition produce the same fingerprint.

    The fingerprint is an identifier, not encryption
    or an authorization mechanism.
    """

    validated_user_id = _validate_user_id(user_id)

    event_fields = _validate_event(event)

    fingerprint_payload = {
        "user_id": validated_user_id,
        "event_type": event_fields["event_type"],
        "metric_type": event_fields["metric_type"],
        "unit": event_fields["unit"],
        "monitoring_priority": event_fields[
            "monitoring_priority"
        ],
        "statistical_status": event_fields[
            "statistical_status"
        ],
    }

    serialized = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


# ============================================================
# PREVIOUS EVENT VALIDATION
# ============================================================

def _validate_previous_events(
    previous_events: Any,
    user_id: int,
) -> list[dict[str, Any]]:
    """
    Validate previous notification records.

    Each record must contain:
        user_id
        fingerprint
        notified_at

    Only records representing notifications actually sent
    should be provided by the persistence layer.
    """

    if not isinstance(previous_events, list):
        raise MonitoringEventDeduplicationError(
            "previous_events must be a list."
        )

    validated_records = []

    for record in previous_events:

        if not isinstance(record, dict):
            raise MonitoringEventDeduplicationError(
                "Previous event records must be dictionaries."
            )

        record_user_id = _validate_user_id(
            record.get("user_id")
        )

        if record_user_id != user_id:
            raise MonitoringEventDeduplicationError(
                "Previous event belongs to another user."
            )

        fingerprint = _required_text(
            record,
            "fingerprint",
        )

        if (
            len(fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in fingerprint
            )
        ):
            raise MonitoringEventDeduplicationError(
                "Previous event fingerprint is invalid."
            )

        notified_at = _parse_datetime(
            record.get("notified_at"),
            "notified_at",
        )

        validated_records.append({
            "user_id": record_user_id,
            "fingerprint": fingerprint,
            "notified_at": notified_at,
        })

    return validated_records


# ============================================================
# EVENT DEDUPLICATION
# ============================================================

def evaluate_event_deduplication(
    user_id: int,
    event: dict[str, Any],
    previous_events: list[dict[str, Any]],
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
    current_time: datetime | str | None = None,
) -> dict[str, Any]:
    """
    Determine whether a monitoring notification should
    be allowed or suppressed.

    Rules:
        1. New fingerprint -> allow.
        2. Matching fingerprint within cooldown -> suppress.
        3. Matching fingerprint at/after cooldown -> allow.
        4. Different event conditions -> independent.
        5. Future notification timestamps -> reject.

    This function is deterministic when current_time is
    explicitly supplied.

    It does not store events or send notifications.
    """

    validated_user_id = _validate_user_id(user_id)

    cooldown = _validate_cooldown(
        cooldown_minutes
    )

    event_fields = _validate_event(event)

    fingerprint = generate_event_fingerprint(
        validated_user_id,
        event,
    )

    if current_time is None:
        now = datetime.now(timezone.utc)
    else:
        now = _parse_datetime(
            current_time,
            "current_time",
        )

    records = _validate_previous_events(
        previous_events,
        validated_user_id,
    )

    matching_records = [
        record
        for record in records
        if record["fingerprint"] == fingerprint
    ]

    # --------------------------------------------------------
    # NEW MONITORING CONDITION
    # --------------------------------------------------------

    if not matching_records:

        return {
            "user_id": validated_user_id,
            "fingerprint": fingerprint,
            "event_type": event_fields["event_type"],
            "metric_type": event_fields["metric_type"],
            "unit": event_fields["unit"],
            "notification_allowed": True,
            "deduplication_status": "new_event",
            "cooldown_minutes": cooldown,
            "last_notified_at": None,
            "next_allowed_at": None,
            "evaluated_at": now.isoformat(),
        }

    # --------------------------------------------------------
    # EXISTING MONITORING CONDITION
    # --------------------------------------------------------

    latest_record = max(
        matching_records,
        key=lambda record: record["notified_at"],
    )

    last_notified_at = latest_record["notified_at"]

    if last_notified_at > now:
        raise MonitoringEventDeduplicationError(
            "Previous notification timestamp cannot be in the future."
        )

    next_allowed_at = (
        last_notified_at
        + timedelta(minutes=cooldown)
    )

    notification_allowed = now >= next_allowed_at

    if notification_allowed:
        deduplication_status = "cooldown_expired"
    else:
        deduplication_status = "duplicate_suppressed"

    return {
        "user_id": validated_user_id,
        "fingerprint": fingerprint,
        "event_type": event_fields["event_type"],
        "metric_type": event_fields["metric_type"],
        "unit": event_fields["unit"],
        "notification_allowed": notification_allowed,
        "deduplication_status": deduplication_status,
        "cooldown_minutes": cooldown,
        "last_notified_at": last_notified_at.isoformat(),
        "next_allowed_at": next_allowed_at.isoformat(),
        "evaluated_at": now.isoformat(),
    }