"""
Unit tests for Pydantic schema validators.

Verifies that schemas correctly accept valid data and reject invalid data
with appropriate error messages.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models.user import UserRole
from app.schemas.auth import CompanyUserCreate
from app.schemas.auth import UserCreate as AuthUserCreate
from app.schemas.job import JobCreate
from app.schemas.swipe import SwipeCreate
from app.schemas.user import PasswordChange, UserUpdate


# ---------------------------------------------------------------------------
# auth.UserCreate
# ---------------------------------------------------------------------------
class TestAuthUserCreate:
    def test_valid_user_create(self):
        data = AuthUserCreate(
            email="test@example.com",
            password="secret123",
            full_name="Jane Doe",
        )
        assert data.email == "test@example.com"
        assert data.full_name == "Jane Doe"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            AuthUserCreate(
                email="not-an-email",
                password="secret123",
                full_name="Jane Doe",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("email",) for e in errors)

    def test_empty_full_name_raises(self):
        with pytest.raises(ValidationError):
            AuthUserCreate(
                email="test@example.com",
                password="secret123",
                full_name="",
            )

    def test_whitespace_only_full_name_raises(self):
        with pytest.raises(ValidationError):
            AuthUserCreate(
                email="test@example.com",
                password="secret123",
                full_name="   ",
            )

    def test_full_name_trimmed(self):
        data = AuthUserCreate(
            email="test@example.com",
            password="secret123",
            full_name="  Jane Doe  ",
        )
        assert data.full_name == "Jane Doe"

    def test_default_role_is_job_seeker(self):
        data = AuthUserCreate(
            email="test@example.com",
            password="secret123",
            full_name="Jane Doe",
        )
        assert data.role == UserRole.JOB_SEEKER


# ---------------------------------------------------------------------------
# auth.CompanyUserCreate
# ---------------------------------------------------------------------------
class TestCompanyUserCreate:
    def test_valid_company_admin(self):
        data = CompanyUserCreate(
            email="admin@company.com",
            password="secret123",
            full_name="Admin User",
            role="admin",
            company_name="Acme Corp",
        )
        assert data.role == UserRole.COMPANY_ADMIN

    def test_recruiter_role_maps_correctly(self):
        data = CompanyUserCreate(
            email="rec@company.com",
            password="secret123",
            full_name="Recruiter",
            role="recruiter",
            company_name="Acme Corp",
        )
        assert data.role == UserRole.COMPANY_RECRUITER

    def test_hr_role_maps_to_recruiter(self):
        data = CompanyUserCreate(
            email="hr@company.com",
            password="secret123",
            full_name="HR Manager",
            role="hr",
            company_name="Acme Corp",
        )
        assert data.role == UserRole.COMPANY_RECRUITER

    def test_invalid_role_raises(self):
        with pytest.raises(ValidationError):
            CompanyUserCreate(
                email="test@company.com",
                password="secret123",
                full_name="User",
                role="superadmin",  # not a valid company role
                company_name="Acme Corp",
            )

    def test_job_seeker_role_rejected(self):
        with pytest.raises(ValidationError):
            CompanyUserCreate(
                email="test@company.com",
                password="secret123",
                full_name="User",
                role="job_seeker",
                company_name="Acme Corp",
            )

    def test_optional_fields_accepted(self):
        data = CompanyUserCreate(
            email="admin@co.com",
            password="pass",
            full_name="Admin",
            role="admin",
            company_name="Co",
            company_description="We build software",
            company_website="https://co.example.com",
            company_industry="Software",
            company_size="11-50",
            company_location="Remote",
        )
        assert data.company_description == "We build software"


# ---------------------------------------------------------------------------
# swipe.SwipeCreate
# ---------------------------------------------------------------------------
class TestSwipeCreate:
    def test_valid_right_swipe(self):
        job_id = uuid.uuid4()
        data = SwipeCreate(job_id=job_id, direction="RIGHT")
        assert data.direction == "RIGHT"
        assert data.job_id == job_id

    def test_valid_left_swipe(self):
        data = SwipeCreate(job_id=uuid.uuid4(), direction="LEFT")
        assert data.direction == "LEFT"

    def test_invalid_job_id_raises(self):
        with pytest.raises(ValidationError):
            SwipeCreate(job_id="not-a-uuid", direction="RIGHT")

    def test_missing_job_id_raises(self):
        with pytest.raises(ValidationError):
            SwipeCreate(direction="RIGHT")

    def test_missing_direction_raises(self):
        with pytest.raises(ValidationError):
            SwipeCreate(job_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# job.JobCreate
# ---------------------------------------------------------------------------
class TestJobCreate:
    def test_minimal_valid_job(self):
        data = JobCreate(title="Software Engineer")
        assert data.title == "Software Engineer"

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            JobCreate()  # title is required

    def test_full_job_create(self):
        data = JobCreate(
            title="Senior Backend Engineer",
            location="Remote",
            short_description="Build APIs",
            description="Full description",
            tags=["python", "fastapi"],
            seniority="senior",
            salary_min=100_000,
            salary_max=150_000,
            currency="USD",
            salary_negotiable=True,
            remote=True,
            work_arrangement="Remote",
            job_type="Full-time",
        )
        assert data.remote is True
        assert data.salary_min == 100_000

    def test_default_currency_is_usd(self):
        data = JobCreate(title="Engineer")
        assert data.currency == "USD"

    def test_default_remote_is_false(self):
        data = JobCreate(title="Engineer")
        assert data.remote is False

    def test_tags_list_accepted(self):
        data = JobCreate(title="Engineer", tags=["python", "docker", "kubernetes"])
        assert len(data.tags) == 3


# ---------------------------------------------------------------------------
# user.PasswordChange
# ---------------------------------------------------------------------------
class TestPasswordChange:
    def test_valid_password(self):
        data = PasswordChange(
            current_password="OldPass1",
            new_password="NewPass1",
        )
        assert data.new_password == "NewPass1"

    def test_password_too_short_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            PasswordChange(
                current_password="old",
                new_password="Short1",  # only 6 chars
            )
        errors = exc_info.value.errors()
        assert any("new_password" in str(e["loc"]) for e in errors)

    def test_no_uppercase_raises(self):
        with pytest.raises(ValidationError):
            PasswordChange(
                current_password="old",
                new_password="nouppercase1",
            )

    def test_no_lowercase_raises(self):
        with pytest.raises(ValidationError):
            PasswordChange(
                current_password="old",
                new_password="NOLOWERCASE1",
            )

    def test_no_digit_raises(self):
        with pytest.raises(ValidationError):
            PasswordChange(
                current_password="old",
                new_password="NoDigitPass",
            )

    def test_exactly_8_chars_accepted(self):
        data = PasswordChange(
            current_password="old",
            new_password="Abc12345",  # 8 chars, has upper/lower/digit
        )
        assert data.new_password == "Abc12345"


# ---------------------------------------------------------------------------
# user.UserUpdate
# ---------------------------------------------------------------------------
class TestUserUpdate:
    def test_empty_update_accepted(self):
        data = UserUpdate()
        assert data.full_name is None

    def test_partial_update_accepted(self):
        data = UserUpdate(headline="Python Developer", seniority="senior")
        assert data.headline == "Python Developer"

    def test_empty_string_full_name_raises(self):
        with pytest.raises(ValidationError):
            UserUpdate(full_name="")

    def test_whitespace_full_name_raises(self):
        with pytest.raises(ValidationError):
            UserUpdate(full_name="   ")

    def test_valid_full_name_trimmed(self):
        data = UserUpdate(full_name="  Jane Doe  ")
        assert data.full_name == "Jane Doe"

    def test_skills_list_accepted(self):
        data = UserUpdate(skills=["python", "go", "rust"])
        assert len(data.skills) == 3

    def test_experience_list_accepted(self):
        exp = [{"title": "Dev", "company": "Acme", "start_date": "2020-01-01"}]
        data = UserUpdate(experience=exp)
        assert len(data.experience) == 1
