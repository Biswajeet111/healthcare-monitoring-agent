"""
Medical Safety Layer — Phase 7

Validates medical queries and responses to prevent:
- Diagnostic claims
- Prescription recommendations
- Dangerous dosage advice
- Fabricated clinical findings

This layer operates as application logic, not just prompt text.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Patterns that indicate potentially unsafe medical requests
UNSAFE_REQUEST_PATTERNS = [
    r"\bdiagnose\s+me\b",
    r"\bam\s+i\s+(sick|ill|diabetic|hypertensive)\b",
    r"\bdo\s+i\s+have\b",
    r"\bprescribe\b",
    r"\bchange\s+my\s+(dose|dosage|medication|prescription)\b",
    r"\bstop\s+(taking|my)\s+medication\b",
    r"\bhow\s+much\s+(of\s+)?\w+\s+should\s+i\s+take\b",
    r"\bwhat\s+medication\s+should\s+i\s+take\b",
    r"\bwhat\s+drug\s+should\s+i\s+take\b",
]

# Patterns in LLM output that suggest unsafe diagnostic claims
UNSAFE_RESPONSE_PATTERNS = [
    r"\byou\s+(have|are)\s+(diabetes|hypertension|cancer|disease)\b",
    r"\bmy\s+diagnosis\s+is\b",
    r"\bi\s+diagnose\b",
    r"\bi\s+prescribe\b",
    r"\btake\s+\d+\s*mg\s+of\b",
    r"\bstop\s+taking\s+your\b",
    r"\bincrease\s+your\s+dose\b",
    r"\bdecrease\s+your\s+dose\b",
]

# Emergency symptom patterns
EMERGENCY_PATTERNS = [
    r"\bchest\s+pain\b",
    r"\bcan'?t\s+breathe\b",
    r"\bdifficulty\s+breathing\b",
    r"\bstroke\b",
    r"\bseizure\b",
    r"\bsevere\s+allergic\b",
    r"\banaphylaxis\b",
    r"\bunconscious\b",
    r"\bstopped\s+breathing\b",
    r"\bsuicide\b",
    r"\bself[\s-]?harm\b",
]

EMERGENCY_GUIDANCE = (
    "⚠️ **Important:** If you or someone nearby is experiencing a medical emergency, "
    "please call emergency services (112 in India / 911 in the US / 999 in the UK) immediately. "
    "Do not rely on this AI for emergency medical guidance."
)

DISCLAIMER = (
    "This is educational information only and does not replace professional medical advice. "
    "Always consult a qualified healthcare provider for medical decisions."
)


def check_emergency_symptoms(query: str) -> bool:
    """Return True if the query contains emergency symptom keywords."""
    q_lower = query.lower()
    for pattern in EMERGENCY_PATTERNS:
        if re.search(pattern, q_lower):
            return True
    return False


def check_unsafe_request(query: str) -> dict:
    """
    Check if the user's query contains patterns that require safety handling.

    Returns dict with:
    - is_emergency: bool
    - has_unsafe_request: bool
    - emergency_guidance: str or None
    - safe_to_process: bool
    - reason: explanation if not safe
    """
    q_lower = query.lower()

    is_emergency = check_emergency_symptoms(q_lower)
    has_unsafe_request = any(
        re.search(pattern, q_lower) for pattern in UNSAFE_REQUEST_PATTERNS
    )

    result = {
        "is_emergency": is_emergency,
        "has_unsafe_request": has_unsafe_request,
        "emergency_guidance": EMERGENCY_GUIDANCE if is_emergency else None,
        "safe_to_process": True,
        "reason": None,
    }

    if has_unsafe_request and not is_emergency:
        result["safe_to_process"] = False
        result["reason"] = (
            "This question requests a medical diagnosis, prescription, or dosage advice. "
            "HealthGuard AI cannot provide these. Please consult a qualified healthcare provider."
        )

    return result


def validate_response(response_text: str) -> dict:
    """
    Check if a generated response contains unsafe diagnostic or prescriptive content.

    Returns dict with:
    - is_safe: bool
    - flagged_patterns: list of matched unsafe patterns
    - sanitized: cleaned response text (or original if safe)
    """
    r_lower = response_text.lower()
    flagged = []

    for pattern in UNSAFE_RESPONSE_PATTERNS:
        if re.search(pattern, r_lower):
            flagged.append(pattern)

    if flagged:
        logger.warning(
            "LLM response flagged for unsafe content patterns: %s",
            flagged,
        )
        sanitized = (
            response_text
            + "\n\n> **Note:** Some content in this response has been flagged for review. "
            "Please consult a qualified healthcare provider for medical decisions."
        )
        return {
            "is_safe": False,
            "flagged_patterns": flagged,
            "sanitized": sanitized,
        }

    return {
        "is_safe": True,
        "flagged_patterns": [],
        "sanitized": response_text,
    }


def sanitize_retrieved_context(chunks: list[dict]) -> list[dict]:
    """
    Sanitize retrieved document chunks to prevent prompt injection.

    - Strips any text that looks like system prompt instructions.
    - Truncates excessively long chunks.
    """
    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+previous\s+instructions",
        r"ignore\s+all\s+instructions",
        r"you\s+are\s+now\s+a",
        r"new\s+system\s+prompt",
        r"disregard\s+your\s+rules",
    ]

    safe_chunks = []
    for chunk in chunks:
        text = chunk.get("text", "")
        t_lower = text.lower()

        is_injection = any(re.search(pat, t_lower) for pat in PROMPT_INJECTION_PATTERNS)
        if is_injection:
            logger.warning(
                "Potential prompt injection detected in chunk '%s'; chunk excluded.",
                chunk.get("id", "unknown"),
            )
            continue

        # Limit chunk length
        if len(text) > 1500:
            text = text[:1500] + "..."

        safe_chunks.append({**chunk, "text": text})

    return safe_chunks
