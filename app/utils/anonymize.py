"""
Candidate anonymization utilities for blind review.

Provides a stable, deterministic alias generator and a helper that strips
PII fields from a serialized application so companies see only professional
attributes until they explicitly reveal a candidate.
"""
import hashlib
from typing import Any

# 50 adjectives — general-purpose, positive, neutral
ALIAS_ADJECTIVES = [
    "Swift", "Bright", "Keen", "Bold", "Sharp",
    "Calm", "Clear", "Crisp", "Deep", "Deft",
    "Eager", "Fair", "Fast", "Fine", "Firm",
    "Free", "Full", "Good", "Grand", "Great",
    "High", "Just", "Kind", "Lean", "Light",
    "Lively", "Noble", "Open", "Plain", "Prime",
    "Pure", "Quick", "Rare", "Rich", "Safe",
    "Smart", "Solid", "Sound", "Steady", "Still",
    "Strong", "Sure", "Tall", "True", "Vast",
    "Warm", "Wide", "Wise", "Young", "Zeal",
]

# 50 nouns — nature / geography / space; no personal references
ALIAS_NOUNS = [
    "Falcon", "Cedar", "River", "Summit", "Comet",
    "Anchor", "Beacon", "Brook", "Canyon", "Cloud",
    "Coral", "Crest", "Delta", "Dune", "Eagle",
    "Field", "Fjord", "Forest", "Gale", "Glade",
    "Glen", "Harbor", "Haven", "Hawk", "Heath",
    "Hill", "Isle", "Lake", "Larch", "Leaf",
    "Maple", "Marsh", "Mesa", "Moon", "Oak",
    "Ocean", "Orbit", "Peak", "Pine", "Plain",
    "Prism", "Ridge", "Sage", "Shore", "Sky",
    "Solar", "Stone", "Storm", "Tide", "Vale",
]

# Fields that are considered PII and must be stripped from anonymous views
_PII_USER_FIELDS = frozenset(
    {
        "full_name",
        "email",
        "phone",
        "avatar_url",
        "linkedin_url",
        "github_url",
        "location",
        "headline",
    }
)


def candidate_alias(application_id: Any) -> str:
    """Return a stable, human-readable alias for a given application ID.

    The alias is derived deterministically from the application ID so the
    same application always produces the same alias across requests.  It is
    NOT reversible — knowing the alias does not reveal the underlying ID to
    a recruiter.

    Format: "<Adjective> <Noun> #<NNN>"
    Example: "Swift Falcon #042"

    Args:
        application_id: The application primary key (UUID or int).

    Returns:
        A human-readable alias string.
    """
    h = hashlib.sha256(str(application_id).encode()).hexdigest()
    adj_idx = int(h[0:4], 16) % len(ALIAS_ADJECTIVES)
    noun_idx = int(h[4:8], 16) % len(ALIAS_NOUNS)
    num = int(h[8:10], 16)  # 0–255
    return f"{ALIAS_ADJECTIVES[adj_idx]} {ALIAS_NOUNS[noun_idx]} #{num:03d}"


def anonymize_candidate(user_data: dict[str, Any]) -> dict[str, Any]:
    """Strip PII fields from a user data dictionary.

    Returns a new dictionary with all keys in ``_PII_USER_FIELDS`` removed.
    Non-PII professional fields (skills, seniority, etc.) are preserved.

    Args:
        user_data: A dictionary representing user/profile data, typically
                   produced by serialising a ``User`` ORM instance.

    Returns:
        A copy of ``user_data`` with PII fields removed.
    """
    return {k: v for k, v in user_data.items() if k not in _PII_USER_FIELDS}
