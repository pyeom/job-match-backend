"""
Status mapping utilities for application status translation between frontend and backend.

The backend uses detailed workflow statuses to track application progress through
various stages, while the frontend uses simplified statuses for UI clarity.

Backend statuses (detailed workflow):
- SUBMITTED: Initial application submission
- WAITING_FOR_REVIEW: Application is queued for review
- HR_MEETING: HR interview stage
- TECHNICAL_INTERVIEW: Technical assessment stage
- FINAL_INTERVIEW: Final interview stage
- HIRED: Successful hire (final positive state)
- REJECTED: Application rejected (final negative state)

Frontend statuses (simplified):
- SUBMITTED: All in-progress states (not yet decided)
- ACCEPTED: Successfully hired
- REJECTED: Application rejected
"""

from typing import Optional


def map_status_to_frontend(backend_status: str) -> str:
    """
    Map backend application status to frontend-friendly status.

    This function consolidates multiple backend workflow states into simplified
    frontend categories for better UX. All intermediate states (from submission
    through interviews) are presented as "SUBMITTED" to indicate the application
    is still in progress.

    Args:
        backend_status: The detailed backend status string

    Returns:
        Frontend status string (SUBMITTED, ACCEPTED, or REJECTED)

    Raises:
        ValueError: If backend_status is None, empty, or not recognized

    Example:
        >>> map_status_to_frontend("HR_MEETING")
        'SUBMITTED'
        >>> map_status_to_frontend("HIRED")
        'ACCEPTED'
        >>> map_status_to_frontend("REJECTED")
        'REJECTED'
    """
    if not backend_status:
        raise ValueError("backend_status cannot be None or empty")

    backend_status = backend_status.strip().upper()

    # Map HIRED to ACCEPTED (successful final state)
    if backend_status == "HIRED":
        return "ACCEPTED"

    # Map all in-progress states to SUBMITTED
    if backend_status in (
        "SUBMITTED",
        "WAITING_FOR_REVIEW",
        "HR_MEETING",
        "TECHNICAL_INTERVIEW",
        "FINAL_INTERVIEW"
    ):
        return "SUBMITTED"

    # REJECTED remains REJECTED
    if backend_status == "REJECTED":
        return "REJECTED"

    raise ValueError(f"Unknown backend status: {backend_status}")


def map_status_to_backend(frontend_status: str) -> str:
    """
    Map frontend status to backend status.

    This function converts simplified frontend statuses back to backend workflow
    states. Since the frontend only sends updates for final states (ACCEPTED/REJECTED),
    this primarily handles those transitions. SUBMITTED maps to the initial backend
    SUBMITTED state.

    Args:
        frontend_status: The simplified frontend status string

    Returns:
        Backend status string (SUBMITTED, HIRED, or REJECTED)

    Raises:
        ValueError: If frontend_status is None, empty, or not recognized

    Example:
        >>> map_status_to_backend("ACCEPTED")
        'HIRED'
        >>> map_status_to_backend("SUBMITTED")
        'SUBMITTED'
        >>> map_status_to_backend("REJECTED")
        'REJECTED'
    """
    if not frontend_status:
        raise ValueError("frontend_status cannot be None or empty")

    frontend_status = frontend_status.strip().upper()

    # Map ACCEPTED to HIRED (backend final success state)
    if frontend_status == "ACCEPTED":
        return "HIRED"

    # Map SUBMITTED to initial backend state
    if frontend_status == "SUBMITTED":
        return "SUBMITTED"

    # REJECTED remains REJECTED
    if frontend_status == "REJECTED":
        return "REJECTED"

    raise ValueError(f"Unknown frontend status: {frontend_status}")


def get_valid_backend_statuses() -> list[str]:
    """
    Get list of all valid backend statuses.

    Returns:
        List of valid backend status strings
    """
    return [
        "SUBMITTED",
        "WAITING_FOR_REVIEW",
        "HR_MEETING",
        "TECHNICAL_INTERVIEW",
        "FINAL_INTERVIEW",
        "HIRED",
        "REJECTED"
    ]


def get_valid_frontend_statuses() -> list[str]:
    """
    Get list of all valid frontend statuses.

    Returns:
        List of valid frontend status strings
    """
    return ["SUBMITTED", "ACCEPTED", "REJECTED"]
