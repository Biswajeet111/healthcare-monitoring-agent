"""
HealthGuard AI — Medical Safety Layer

Phase 7 / Phase 8 safety improvements.

Features:
- Medical request screening
- Emergency detection
- Deterministic emergency guidance
- Unsafe diagnosis and prescription detection
- Medication instruction validation
- Reduced false positives
- Prompt injection filtering
- Safe response replacement for high-risk outputs

This module is a supplementary safety layer.
It does not replace clinical review.
"""

import logging
import re
from typing import Optional


logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

DISCLAIMER = (
    "This is educational information only and does not "
    "replace professional medical advice. "
    "Always consult a qualified healthcare provider "
    "for medical decisions."
)


EMERGENCY_GUIDANCE = (
    "⚠️ **Medical Emergency:** If you are experiencing severe "
    "chest pain, difficulty breathing, stroke symptoms, "
    "unconsciousness, or another potentially life-threatening "
    "condition, call emergency services immediately "
    "(112 in India / 911 in the US / 999 in the UK). "
    "Do not drive yourself to the hospital. "
    "Seek immediate professional medical assistance."
)


EMERGENCY_RESPONSE = (
    "⚠️ **Immediate medical attention is required.**\n\n"
    "Call your local emergency number now "
    "(112 in India / 911 in the US / 999 in the UK).\n\n"
    "If possible, ask someone nearby to assist you. "
    "Do not drive yourself to the hospital.\n\n"
    "Do not wait for an AI-generated assessment. "
    "These symptoms may indicate a medical emergency."
)


UNSAFE_REQUEST_MESSAGE = (
    "I can explain general medical information, but I cannot "
    "diagnose a condition, prescribe medication, or decide "
    "whether you should start, stop, or change a treatment. "
    "Please discuss medication and treatment decisions with "
    "a qualified healthcare professional."
)


UNSAFE_RESPONSE_MESSAGE = (
    "I cannot safely provide an individualized diagnosis, "
    "prescription, or medication-change instruction. "
    "Please consult a qualified healthcare professional "
    "for guidance specific to your situation."
)


# ============================================================
# REQUEST PATTERNS
# ============================================================

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


# ============================================================
# EMERGENCY DETECTION
# ============================================================

EMERGENCY_PATTERNS = [
    r"\b(severe|crushing|sudden)\s+chest\s+pain\b",
    r"\bchest\s+pain\b",
    r"\bcan'?t\s+breathe\b",
    r"\bcannot\s+breathe\b",
    r"\bdifficulty\s+breathing\b",
    r"\bsevere\s+shortness\s+of\s+breath\b",
    r"\bstopped\s+breathing\b",
    r"\bnot\s+breathing\b",
    r"\bstroke\s+symptoms\b",
    r"\bface\s+drooping\b",
    r"\bslurred\s+speech\b",
    r"\bsudden\s+weakness\s+on\s+one\s+side\b",
    r"\bseizure\b",
    r"\bunconscious\b",
    r"\bunresponsive\b",
    r"\banaphylaxis\b",
    r"\bsevere\s+allergic\s+reaction\b",
    r"\bsuicidal\s+thoughts\b",
    r"\bwant\s+to\s+kill\s+myself\b",
    r"\bwant\s+to\s+end\s+my\s+life\b",
    r"\bself[\s-]?harm\b",
]


def check_emergency_symptoms(query: str) -> bool:
    """
    Detect possible medical emergency language.

    This function is intentionally conservative.

    It cannot determine whether a real emergency exists.
    """

    if not query:
        return False

    query_lower = query.lower()

    return any(
        re.search(pattern, query_lower)
        for pattern in EMERGENCY_PATTERNS
    )


def get_emergency_response() -> str:
    """
    Return deterministic emergency guidance.

    The calling API can use this instead of waiting
    for an LLM-generated emergency response.
    """

    return EMERGENCY_RESPONSE


# ============================================================
# REQUEST SAFETY
# ============================================================

def check_unsafe_request(query: str) -> dict:
    """
    Screen user requests.

    Preserves the existing response structure:
    - is_emergency
    - has_unsafe_request
    - emergency_guidance
    - safe_to_process
    - reason
    """

    query = query or ""

    query_lower = query.lower()

    is_emergency = check_emergency_symptoms(query_lower)

    has_unsafe_request = any(
        re.search(pattern, query_lower)
        for pattern in UNSAFE_REQUEST_PATTERNS
    )

    result = {
        "is_emergency": is_emergency,
        "has_unsafe_request": has_unsafe_request,
        "emergency_guidance": (
            EMERGENCY_GUIDANCE if is_emergency else None
        ),
        "safe_to_process": True,
        "reason": None,
    }

    if is_emergency:
        result["safe_to_process"] = False
        result["reason"] = EMERGENCY_RESPONSE

        return result

    if has_unsafe_request:
        result["safe_to_process"] = False
        result["reason"] = UNSAFE_REQUEST_MESSAGE

    return result


# ============================================================
# RESPONSE SAFETY
# ============================================================

# Clear unsafe instructions or unsupported diagnoses.
UNSAFE_RESPONSE_PATTERNS = [
    r"\byou\s+(have|are)\s+(diabetes|hypertension|cancer)\b",
    r"\bi\s+diagnose\s+you\b",
    r"\bmy\s+diagnosis\s+is\b",
    r"\bi\s+prescribe\b",
    r"\byou\s+should\s+take\s+\d+\s*(mg|mcg|g)\b",
    r"\btake\s+\d+\s*(mg|mcg|g)\s+of\b",
    r"\bincrease\s+your\s+(medication\s+)?dose\b",
    r"\bdecrease\s+your\s+(medication\s+)?dose\b",
    r"\breduce\s+your\s+(medication\s+)?dose\b",
    r"\bstop\s+taking\s+your\s+(medication|medicine|pills)\b",
    r"\bdiscontinue\s+your\s+(medication|medicine|treatment)\b",
    r"\bskip\s+your\s+(medication|medicine|dose)\b",
]


# Safe negative instructions that must not be flagged.
SAFE_NEGATION_PATTERNS = [
    r"\bdo\s+not\s+stop\s+taking\b",
    r"\bdon'?t\s+stop\s+taking\b",
    r"\bshould\s+not\s+stop\s+taking\b",
    r"\bshouldn'?t\s+stop\s+taking\b",
    r"\bnever\s+stop\s+taking\b",
    r"\bdo\s+not\s+change\s+your\s+dose\b",
    r"\bdon'?t\s+change\s+your\s+dose\b",
    r"\bshould\s+not\s+change\s+your\s+dose\b",
    r"\bconsult\s+your\s+(doctor|healthcare\s+provider)\b",
]


def _is_negated_medication_instruction(
    text: str,
    match_start: int,
) -> bool:
    """
    Check whether a medication instruction is negated.

    Only examines the text immediately before the match.
    This reduces false positives such as:

    'Do not stop taking your medication.'

    It does not guarantee semantic understanding.
    """

    preceding = text[
        max(0, match_start - 60):match_start
    ].lower()

    # Limit to the current sentence.
    preceding = re.split(
        r"[.!?\n]",
        preceding,
    )[-1]

    return bool(
        re.search(
            r"\b("
            r"do\s+not|"
            r"don'?t|"
            r"should\s+not|"
            r"shouldn'?t|"
            r"never|"
            r"must\s+not"
            r")\s*$",
            preceding,
        )
    )


def validate_response(response_text: str) -> dict:
    """
    Validate generated medical responses.

    Returns:
    - is_safe: bool
    - flagged_patterns: list[str]
    - sanitized: str

    High-risk content is replaced with a safe response.
    """

    response_text = response_text or ""

    response_lower = response_text.lower()

    flagged_patterns = []

    for pattern in UNSAFE_RESPONSE_PATTERNS:

        for match in re.finditer(
            pattern,
            response_lower,
        ):

            # Medication instruction patterns require
            # a negation check.
            is_medication_pattern = any(
                keyword in pattern
                for keyword in (
                    "stop",
                    "increase",
                    "decrease",
                    "reduce",
                    "discontinue",
                    "skip",
                )
            )

            if is_medication_pattern:

                if _is_negated_medication_instruction(
                    response_lower,
                    match.start(),
                ):
                    continue

            flagged_patterns.append(pattern)

            break

    if flagged_patterns:

        logger.warning(
            "Unsafe medical response patterns detected: %s",
            flagged_patterns,
        )

        return {
            "is_safe": False,
            "flagged_patterns": flagged_patterns,
            "sanitized": UNSAFE_RESPONSE_MESSAGE,
        }

    return {
        "is_safe": True,
        "flagged_patterns": [],
        "sanitized": response_text,
    }


# ============================================================
# RETRIEVED CONTEXT SANITIZATION
# ============================================================

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"ignore\s+all\s+instructions",
    r"you\s+are\s+now\s+a",
    r"new\s+system\s+prompt",
    r"disregard\s+your\s+rules",
    r"override\s+system\s+instructions",
    r"developer\s+message\s*:",
    r"system\s+message\s*:",
]


def sanitize_retrieved_context(
    chunks: list[dict],
) -> list[dict]:
    """
    Sanitize retrieved documents before sending them to the LLM.

    Preserves chunk IDs and metadata.

    Excludes obvious prompt-injection attempts.
    Truncates excessively long chunks.
    """

    safe_chunks = []

    for chunk in chunks or []:

        text = str(
            chunk.get("text") or ""
        )

        if not text.strip():
            continue

        text_lower = text.lower()

        is_injection = any(
            re.search(pattern, text_lower)
            for pattern in PROMPT_INJECTION_PATTERNS
        )

        if is_injection:

            logger.warning(
                "Potential prompt injection detected in chunk %s",
                chunk.get("id", "unknown"),
            )

            continue

        # Limit individual chunks.
        if len(text) > 1500:
            text = text[:1500] + "..."

        safe_chunks.append(
            {
                **chunk,
                "text": text,
            }
        )

    return safe_chunks