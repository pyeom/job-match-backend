"""
User service for business logic operations on user profiles.
"""

from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.user import User
from app.schemas.resume_parser import ResumeParseResponse
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class UserService:
    """Service for user-related business logic."""

    async def update_profile_from_resume(
        self,
        db: AsyncSession,
        user: User,
        parsed_data: ResumeParseResponse
    ) -> Tuple[User, List[str]]:
        """
        Update user profile with parsed resume data.

        Only updates fields that are currently empty to avoid overwriting
        user-provided data.

        Args:
            db: Database session
            user: User model instance
            parsed_data: Parsed resume data

        Returns:
            Tuple of (updated user, list of fields updated)
        """
        fields_updated = []
        update_dict = {}

        # Update contact information (only if empty)
        if parsed_data.contact.full_name and not user.full_name:
            update_dict["full_name"] = parsed_data.contact.full_name
            fields_updated.append("full_name")

        if parsed_data.contact.phone and not getattr(user, 'phone', None):
            update_dict["phone"] = parsed_data.contact.phone
            fields_updated.append("phone")

        # Update summary/headline
        if parsed_data.summary.headline and not getattr(user, 'headline', None):
            update_dict["headline"] = parsed_data.summary.headline
            fields_updated.append("headline")

        if parsed_data.summary.summary and not getattr(user, 'bio', None):
            update_dict["bio"] = parsed_data.summary.summary
            fields_updated.append("bio")

        # Update skills
        existing_skills = getattr(user, 'skills', None) or []
        if parsed_data.skills.all_skills:
            if not existing_skills:
                update_dict["skills"] = parsed_data.skills.all_skills
                fields_updated.append("skills")
            else:
                # Merge skills, avoiding duplicates
                existing_set = {s.lower() for s in existing_skills}
                new_skills = [s for s in parsed_data.skills.all_skills if s.lower() not in existing_set]
                if new_skills:
                    merged_skills = existing_skills + new_skills
                    update_dict["skills"] = merged_skills[:50]  # Limit to 50 skills
                    fields_updated.append("skills")

        # Update experience
        if parsed_data.experience and not getattr(user, 'experience', None):
            experience_list = []
            for exp in parsed_data.experience:
                experience_list.append({
                    "title": exp.title,
                    "company": exp.company,
                    "start_date": exp.start_date,
                    "end_date": exp.end_date,
                    "description": exp.description,
                    "location": exp.location,
                    "is_current": exp.is_current
                })
            update_dict["experience"] = experience_list
            fields_updated.append("experience")

        # Update education
        if parsed_data.education and not getattr(user, 'education', None):
            education_list = []
            for edu in parsed_data.education:
                education_list.append({
                    "degree": edu.degree,
                    "institution": edu.institution,
                    "field_of_study": edu.field_of_study,
                    "start_date": edu.start_date,
                    "end_date": edu.end_date,
                    "gpa": edu.gpa,
                    "description": edu.description
                })
            update_dict["education"] = education_list
            fields_updated.append("education")

        # Infer seniority from experience
        if not getattr(user, 'seniority', None) and parsed_data.experience:
            seniority = self._infer_seniority(parsed_data)
            if seniority:
                update_dict["seniority"] = seniority
                fields_updated.append("seniority")

        # Extract preferred locations from experience
        if not getattr(user, 'preferred_locations', None):
            locations = self._extract_locations(parsed_data)
            if locations:
                update_dict["preferred_locations"] = locations
                fields_updated.append("preferred_locations")

        # Apply updates
        if update_dict:
            for key, value in update_dict.items():
                if hasattr(user, key):
                    setattr(user, key, value)

            # Update profile embedding if we changed significant fields
            if any(field in fields_updated for field in ["headline", "bio", "skills", "experience"]):
                try:
                    # Generate profile embedding using existing embedding service
                    user_skills = getattr(user, 'skills', None) or []
                    user_headline = getattr(user, 'headline', None)
                    user_locations = getattr(user, 'preferred_locations', None) or []

                    embedding = embedding_service.generate_user_embedding(
                        headline=user_headline,
                        skills=user_skills,
                        preferences=user_locations
                    )

                    if hasattr(user, 'profile_embedding'):
                        user.profile_embedding = embedding
                        fields_updated.append("profile_embedding")
                        logger.info(f"Updated profile embedding for user {user.id}")
                except Exception as e:
                    logger.error(f"Failed to update embedding for user {user.id}: {e}")

            await db.commit()
            await db.refresh(user)
            logger.info(f"Updated user {user.id} profile with fields: {fields_updated}")

        return user, fields_updated

    def _infer_seniority(self, parsed_data: ResumeParseResponse) -> Optional[str]:
        """Infer seniority level from parsed resume data."""
        if not parsed_data.experience:
            return None

        # Check titles for seniority keywords
        all_titles = " ".join([exp.title.lower() for exp in parsed_data.experience])

        seniority_keywords = {
            "intern": [
                "intern", "internship", "trainee",  # English
                "practicante", "pasante", "becario", "aprendiz"  # Spanish
            ],
            "junior": [
                "junior", "entry level", "entry-level", "associate", "jr.",  # English
                "principiante", "nivel inicial", "asistente"  # Spanish
            ],
            "mid": [
                "mid level", "mid-level", "intermediate",  # English
                "nivel medio", "intermedio", "semi senior", "semi-senior", "ssr"  # Spanish
            ],
            "senior": [
                "senior", "sr.", "principal", "staff",  # English
                "especialista", "experto"  # Spanish
            ],
            "lead": [
                "lead", "team lead", "tech lead", "architect",  # English
                "líder", "lider", "jefe de equipo", "arquitecto", "coordinador"  # Spanish
            ],
            "manager": [
                "manager", "director", "head of", "vp", "chief", "cto", "ceo",  # English
                "gerente", "director", "jefe", "responsable", "encargado"  # Spanish
            ]
        }

        # Check from most senior to least
        for level in ["manager", "lead", "senior", "mid", "junior", "intern"]:
            keywords = seniority_keywords[level]
            for keyword in keywords:
                if keyword in all_titles:
                    return level

        # Infer from number of experiences as fallback
        num_experiences = len(parsed_data.experience)
        if num_experiences >= 6:
            return "senior"
        elif num_experiences >= 3:
            return "mid"
        elif num_experiences >= 1:
            return "junior"

        return None

    def _extract_locations(self, parsed_data: ResumeParseResponse) -> List[str]:
        """Extract unique locations from experience and contact."""
        locations = set()

        # From experience
        for exp in parsed_data.experience:
            if exp.location:
                locations.add(exp.location)

        # From contact
        if parsed_data.contact.location:
            locations.add(parsed_data.contact.location)

        return list(locations)[:5]  # Limit to 5 locations


# Singleton instance
user_service = UserService()
