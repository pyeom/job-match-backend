"""
Unit tests for app.utils.anonymize — TASK-041 blind review.

Covers:
  - candidate_alias is deterministic (same input → same output)
  - aliases are distinct across the first 1 000 application IDs
  - alias format matches the expected pattern
  - anonymize_candidate strips all PII fields
  - anonymize_candidate preserves non-PII fields
"""
from __future__ import annotations

import re
import uuid

import pytest

from app.utils.anonymize import (
    ALIAS_ADJECTIVES,
    ALIAS_NOUNS,
    _PII_USER_FIELDS,
    anonymize_candidate,
    candidate_alias,
)


# ---------------------------------------------------------------------------
# candidate_alias
# ---------------------------------------------------------------------------


class TestCandidateAlias:
    def test_same_id_always_returns_same_alias(self):
        """Alias must be deterministic."""
        app_id = uuid.uuid4()
        assert candidate_alias(app_id) == candidate_alias(app_id)

    def test_same_integer_id_is_deterministic(self):
        for i in range(20):
            assert candidate_alias(i) == candidate_alias(i)

    def test_different_ids_produce_different_aliases_in_1000(self):
        """No collisions among the first 1 000 UUID-based application IDs."""
        ids = [uuid.uuid4() for _ in range(1_000)]
        aliases = [candidate_alias(i) for i in ids]
        # Allow a tiny number of hash collisions (< 0.5 %) but none is ideal
        unique = set(aliases)
        assert len(unique) >= 990, (
            f"Too many alias collisions: {1000 - len(unique)} collisions in 1 000 IDs"
        )

    def test_alias_format_matches_pattern(self):
        """Alias must match '<Adjective> <Noun> #NNN' (NNN = zero-padded 3-digit int)."""
        pattern = re.compile(r"^[A-Za-z]+ [A-Za-z]+ #\d{3}$")
        for _ in range(50):
            alias = candidate_alias(uuid.uuid4())
            assert pattern.match(alias), f"Alias '{alias}' does not match expected format"

    def test_adjective_comes_from_word_list(self):
        for _ in range(100):
            alias = candidate_alias(uuid.uuid4())
            adjective = alias.split(" ")[0]
            assert adjective in ALIAS_ADJECTIVES, f"'{adjective}' not in ALIAS_ADJECTIVES"

    def test_noun_comes_from_word_list(self):
        for _ in range(100):
            alias = candidate_alias(uuid.uuid4())
            noun = alias.split(" ")[1]
            assert noun in ALIAS_NOUNS, f"'{noun}' not in ALIAS_NOUNS"

    def test_numeric_suffix_in_0_to_255(self):
        for _ in range(200):
            alias = candidate_alias(uuid.uuid4())
            num = int(alias.split("#")[1])
            assert 0 <= num <= 255

    def test_accepts_uuid_type(self):
        app_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        alias = candidate_alias(app_id)
        assert isinstance(alias, str)
        assert len(alias) > 0

    def test_accepts_string_id(self):
        alias = candidate_alias("some-string-id")
        assert isinstance(alias, str)

    def test_accepts_integer_id(self):
        alias = candidate_alias(42)
        assert isinstance(alias, str)

    def test_number_lists_have_correct_lengths(self):
        """Both word lists must have exactly 50 entries (affects modulo distribution)."""
        assert len(ALIAS_ADJECTIVES) == 50
        assert len(ALIAS_NOUNS) == 50


# ---------------------------------------------------------------------------
# anonymize_candidate
# ---------------------------------------------------------------------------


class TestAnonymizeCandidate:
    def _full_user_dict(self) -> dict:
        """Return a user data dict containing all PII and non-PII fields."""
        return {
            # PII fields — should be stripped
            "full_name": "Alice Smith",
            "email": "alice@example.com",
            "phone": "+1-555-123-4567",
            "avatar_url": "https://cdn.example.com/avatars/alice.jpg",
            "linkedin_url": "https://linkedin.com/in/alicesmith",
            "github_url": "https://github.com/alicesmith",
            "location": "San Francisco, CA",
            "headline": "Senior Python Engineer",
            # Non-PII professional fields — should be preserved
            "id": str(uuid.uuid4()),
            "skills": ["python", "fastapi", "postgresql"],
            "seniority": "senior",
            "experience_years": 7,
        }

    def test_pii_fields_are_absent_in_output(self):
        user = self._full_user_dict()
        result = anonymize_candidate(user)
        for pii_key in _PII_USER_FIELDS:
            assert pii_key not in result, f"PII field '{pii_key}' was not stripped"

    def test_non_pii_fields_are_preserved(self):
        user = self._full_user_dict()
        result = anonymize_candidate(user)
        assert result["skills"] == ["python", "fastapi", "postgresql"]
        assert result["seniority"] == "senior"
        assert result["experience_years"] == 7
        assert "id" in result

    def test_does_not_mutate_input(self):
        user = self._full_user_dict()
        original_keys = set(user.keys())
        anonymize_candidate(user)
        assert set(user.keys()) == original_keys, "anonymize_candidate mutated the input dict"

    def test_empty_dict_returns_empty_dict(self):
        assert anonymize_candidate({}) == {}

    def test_dict_with_only_pii_returns_empty(self):
        user = {"full_name": "Bob", "email": "bob@example.com"}
        result = anonymize_candidate(user)
        assert result == {}

    def test_dict_with_only_non_pii_returns_same(self):
        user = {"skills": ["python"], "seniority": "mid"}
        result = anonymize_candidate(user)
        assert result == user

    def test_pii_fields_constant_covers_expected_keys(self):
        """Ensure the PII field list includes all expected sensitive keys."""
        expected = {
            "full_name",
            "email",
            "phone",
            "avatar_url",
            "linkedin_url",
            "github_url",
            "location",
            "headline",
        }
        assert expected <= _PII_USER_FIELDS, (
            f"Missing PII keys: {expected - _PII_USER_FIELDS}"
        )
