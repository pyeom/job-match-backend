"""
HTTP client for the job-match-mala microservice.
Called from arq background workers — never in the request/response path.

Includes:
- Per-request timeout (20s for candidate analysis, 60s for job analysis)
- Circuit breaker: after 3 consecutive failures, skip MALA calls for 60 seconds
"""
import time
import logging

import httpx
from app.core.config import settings
from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)

MALA_URL = getattr(settings, "mala_service_url", "http://localhost:8001")

# ---------------------------------------------------------------------------
# Simple module-level circuit breaker
# ---------------------------------------------------------------------------
_consecutive_failures: int = 0
_circuit_open_until: float = 0.0  # monotonic timestamp; 0 means closed
_FAILURE_THRESHOLD: int = 3
_COOLDOWN_SECONDS: float = 60.0


def _is_circuit_open() -> bool:
    global _circuit_open_until
    if _circuit_open_until and time.monotonic() < _circuit_open_until:
        return True
    _circuit_open_until = 0.0
    return False


def _record_success() -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def _record_failure() -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= _FAILURE_THRESHOLD:
        _circuit_open_until = time.monotonic() + _COOLDOWN_SECONDS
        logger.warning(
            "MALA circuit breaker OPEN after %d consecutive failures — "
            "skipping MALA calls for %.0fs",
            _consecutive_failures,
            _COOLDOWN_SECONDS,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze_candidate(candidate_id: str, cv_text: str, answers: list[dict]) -> dict:
    """Call the MALA /analyze/candidate endpoint.

    Returns a dict with ``mala_available: False`` on timeout, 5xx, or circuit open.
    """
    if _is_circuit_open():
        logger.info("MALA circuit breaker open — skipping analyze_candidate for %s", candidate_id)
        return {"mala_available": False, "reason": "circuit_open"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{MALA_URL}/analyze/candidate",
                json={"candidate_id": candidate_id, "cv_text": cv_text, "mala_answers": answers},
                headers={"X-Request-ID": get_request_id()},
            )
        if response.status_code >= 500:
            _record_failure()
            logger.warning(
                "MALA returned %s for analyze_candidate(%s) — degraded mode",
                response.status_code, candidate_id,
            )
            return {"mala_available": False, "reason": f"upstream_{response.status_code}"}
        response.raise_for_status()
        _record_success()
        return response.json()

    except httpx.TimeoutException:
        _record_failure()
        logger.warning("MALA timeout on analyze_candidate(%s) — degraded mode", candidate_id)
        return {"mala_available": False, "reason": "timeout"}

    except Exception as exc:
        _record_failure()
        logger.warning("MALA error on analyze_candidate(%s): %s — degraded mode", candidate_id, exc)
        return {"mala_available": False, "reason": "error"}


async def analyze_job(job_offer_id: str, description: str, e_answers: list[dict]) -> dict:
    """Call the MALA /analyze/job endpoint.

    Returns a dict with ``mala_available: False`` on timeout, 5xx, or circuit open.
    """
    if _is_circuit_open():
        logger.info("MALA circuit breaker open — skipping analyze_job for %s", job_offer_id)
        return {"mala_available": False, "reason": "circuit_open"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{MALA_URL}/analyze/job",
                json={"job_offer_id": job_offer_id, "description": description, "e_answers": e_answers},
                headers={"X-Request-ID": get_request_id()},
            )
        if response.status_code >= 500:
            _record_failure()
            logger.warning(
                "MALA returned %s for analyze_job(%s) — degraded mode",
                response.status_code, job_offer_id,
            )
            return {"mala_available": False, "reason": f"upstream_{response.status_code}"}
        response.raise_for_status()
        _record_success()
        return response.json()

    except httpx.TimeoutException:
        _record_failure()
        logger.warning("MALA timeout on analyze_job(%s) — degraded mode", job_offer_id)
        return {"mala_available": False, "reason": "timeout"}

    except Exception as exc:
        _record_failure()
        logger.warning("MALA error on analyze_job(%s): %s — degraded mode", job_offer_id, exc)
        return {"mala_available": False, "reason": "error"}
