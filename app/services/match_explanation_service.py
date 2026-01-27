"""
Match Explanation Service

This service provides AI-powered natural language explanations for job match scores.
It breaks down the hybrid scoring algorithm into human-readable insights.
"""

from typing import List, Optional
from datetime import datetime, timezone
from app.schemas.match_explanation import MatchExplanation, MatchFactorExplanation
from app.services.scoring_service import ScoringService
from app.services.embedding_service import embedding_service


class MatchExplanationService:
    """Service for generating natural language match explanations"""

    @staticmethod
    def _explain_embedding_similarity(score: float, weight: float) -> MatchFactorExplanation:
        """Generate explanation for embedding similarity"""
        percentage = int(score * 100)

        if score >= 0.9:
            explanation = (
                f"Your profile shows exceptional alignment with this role ({percentage}% similarity). "
                "Our AI detected strong matches in your experience, skills, and career goals."
            )
        elif score >= 0.75:
            explanation = (
                f"Your profile aligns very well with this role ({percentage}% similarity). "
                "The AI found significant overlap in your professional background and the job requirements."
            )
        elif score >= 0.6:
            explanation = (
                f"Your profile shows good alignment with this role ({percentage}% similarity). "
                "The AI identified several relevant connections between your background and the position."
            )
        elif score >= 0.45:
            explanation = (
                f"Your profile has moderate alignment with this role ({percentage}% similarity). "
                "While not a perfect match, there are some relevant aspects of your background for this position."
            )
        else:
            explanation = (
                f"Your profile shows limited alignment with this role ({percentage}% similarity). "
                "The AI found fewer connections between your background and the job requirements."
            )

        return MatchFactorExplanation(
            score=score,
            weight=weight,
            weighted_contribution=score * weight,
            explanation=explanation,
            details=f"Profile similarity: {percentage}%"
        )

    @staticmethod
    def _explain_skill_overlap(
        user_skills: Optional[List[str]],
        job_tags: Optional[List[str]],
        score: float,
        weight: float
    ) -> MatchFactorExplanation:
        """Generate explanation for skill overlap"""

        if not user_skills or not job_tags:
            explanation = "Skill comparison not available due to incomplete profile or job data."
            details = "Missing skill information"
        else:
            user_skills_lower = [skill.lower() for skill in user_skills]
            job_tags_lower = [tag.lower() for tag in job_tags]
            common_skills = set(user_skills_lower) & set(job_tags_lower)

            matching_count = len(common_skills)
            required_count = len(job_tags_lower)

            # Get original case for display
            common_skills_display = [
                skill for skill in job_tags
                if skill.lower() in common_skills
            ]

            if score >= 0.8:
                explanation = (
                    f"You have {matching_count} out of {required_count} required skills for this position. "
                    "This is an excellent skill match!"
                )
            elif score >= 0.6:
                explanation = (
                    f"You have {matching_count} out of {required_count} required skills for this position. "
                    "You possess most of the key skills needed."
                )
            elif score >= 0.4:
                explanation = (
                    f"You have {matching_count} out of {required_count} required skills for this position. "
                    "Some skills overlap, but there are gaps to consider."
                )
            elif score > 0:
                explanation = (
                    f"You have {matching_count} out of {required_count} required skills for this position. "
                    "Limited skill overlap - you may need to develop additional skills."
                )
            else:
                explanation = (
                    f"Your skills don't currently match the {required_count} required skills for this position. "
                    "This role may require significant upskilling."
                )

            if common_skills_display:
                details = f"Matching skills: {', '.join(common_skills_display[:10])}"
                if len(common_skills_display) > 10:
                    details += f" (+{len(common_skills_display) - 10} more)"
            else:
                details = f"Required: {', '.join(job_tags[:5])}" + ("..." if len(job_tags) > 5 else "")

        return MatchFactorExplanation(
            score=score,
            weight=weight,
            weighted_contribution=score * weight,
            explanation=explanation,
            details=details
        )

    @staticmethod
    def _explain_seniority_match(
        user_seniority: Optional[str],
        job_seniority: Optional[str],
        score: float,
        weight: float
    ) -> MatchFactorExplanation:
        """Generate explanation for seniority match"""

        if not user_seniority or not job_seniority:
            explanation = "Seniority comparison not available due to incomplete profile or job data."
            details = "Missing seniority information"
        else:
            user_level = user_seniority.capitalize()
            job_level = job_seniority.capitalize()

            if score == 1.0:
                explanation = f"Your seniority level ({user_level}) exactly matches the job requirements ({job_level})."
            elif score == 0.5:
                explanation = (
                    f"Your seniority level ({user_level}) is one level different from the job requirements ({job_level}). "
                    "This could still be a good fit depending on your experience."
                )
            else:
                explanation = (
                    f"Your seniority level ({user_level}) differs significantly from the job requirements ({job_level}). "
                    "This may not be the right career stage for you."
                )

            details = f"You: {user_level}, Job: {job_level}"

        return MatchFactorExplanation(
            score=score,
            weight=weight,
            weighted_contribution=score * weight,
            explanation=explanation,
            details=details
        )

    @staticmethod
    def _explain_recency_decay(
        job_created_at: datetime,
        score: float,
        weight: float
    ) -> MatchFactorExplanation:
        """Generate explanation for recency decay"""

        now = datetime.now(timezone.utc)
        hours_old = (now - job_created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        days_old = int(hours_old / 24)

        if days_old == 0:
            time_str = "today"
        elif days_old == 1:
            time_str = "yesterday"
        else:
            time_str = f"{days_old} days ago"

        if score >= 0.9:
            explanation = f"This is a fresh posting from {time_str}. Apply soon for the best chance!"
        elif score >= 0.7:
            explanation = f"This posting is relatively recent ({time_str}). Good timing to apply."
        elif score >= 0.5:
            explanation = f"This posting is {time_str}. Still active but not brand new."
        else:
            explanation = f"This posting is older ({time_str}), but positions can take time to fill."

        details = f"Posted {time_str}"

        return MatchFactorExplanation(
            score=score,
            weight=weight,
            weighted_contribution=score * weight,
            explanation=explanation,
            details=details
        )

    @staticmethod
    def _explain_location_match(
        user_preferences: Optional[List[str]],
        job_location: Optional[str],
        job_remote: bool,
        score: float,
        weight: float
    ) -> MatchFactorExplanation:
        """Generate explanation for location match"""

        if job_remote:
            explanation = "This is a remote position, which matches any location preference."
            details = "Remote position"
        elif not user_preferences:
            if job_location:
                explanation = f"Location is {job_location}. Add location preferences to your profile for better matching."
                details = f"Location: {job_location}"
            else:
                explanation = "Location information is not available for comparison."
                details = "Location not specified"
        elif not job_location:
            explanation = "Job location is not specified. Check the job description for details."
            details = "Location not specified"
        else:
            if score == 1.0:
                explanation = f"The job location ({job_location}) matches your preferences perfectly!"
                details = f"Match: {job_location}"
            else:
                user_prefs_str = ", ".join(user_preferences[:3])
                if len(user_preferences) > 3:
                    user_prefs_str += "..."
                explanation = (
                    f"The job location ({job_location}) doesn't match your stated preferences ({user_prefs_str}). "
                    "Consider if you're open to relocation or updating your preferences."
                )
                details = f"Job: {job_location}, You prefer: {user_prefs_str}"

        return MatchFactorExplanation(
            score=score,
            weight=weight,
            weighted_contribution=score * weight,
            explanation=explanation,
            details=details
        )

    @staticmethod
    def _generate_overall_summary(
        overall_score: int,
        job_title: str,
        company_name: str,
        embedding_score: float,
        skill_score: float,
        seniority_score: float
    ) -> str:
        """Generate an overall match summary"""

        # Determine primary strengths
        strengths = []
        if embedding_score >= 0.8:
            strengths.append("strong profile alignment")
        if skill_score >= 0.7:
            strengths.append("excellent skill match")
        if seniority_score >= 0.5:
            strengths.append("appropriate seniority level")

        # Determine overall quality
        if overall_score >= 85:
            quality = "an exceptional"
            action = "We highly recommend applying for this position."
        elif overall_score >= 75:
            quality = "an excellent"
            action = "This looks like a great opportunity for you."
        elif overall_score >= 65:
            quality = "a good"
            action = "This position is worth considering."
        elif overall_score >= 50:
            quality = "a moderate"
            action = "Review the details to see if it aligns with your goals."
        else:
            quality = "a limited"
            action = "This may not be the best fit, but could be worth exploring if you're interested in pivoting."

        # Build summary
        if strengths:
            strengths_str = ", ".join(strengths[:-1])
            if len(strengths) > 1:
                strengths_str += f" and {strengths[-1]}"
            else:
                strengths_str = strengths[0]

            summary = (
                f"This is {quality} match ({overall_score}%) for the {job_title} role at {company_name}. "
                f"Key strengths include {strengths_str}. {action}"
            )
        else:
            summary = (
                f"This shows {quality} match ({overall_score}%) for the {job_title} role at {company_name}. "
                f"{action}"
            )

        return summary

    def generate_match_explanation(
        self,
        job_id: str,
        job_title: str,
        company_name: str,
        user_embedding: List[float],
        job_embedding: List[float],
        user_skills: Optional[List[str]],
        user_seniority: Optional[str],
        user_preferences: Optional[List[str]],
        job_tags: Optional[List[str]],
        job_seniority: Optional[str],
        job_location: Optional[str],
        job_remote: bool,
        job_created_at: datetime
    ) -> MatchExplanation:
        """
        Generate comprehensive match explanation with natural language insights.

        This method calculates all match factors and generates human-readable
        explanations for each component of the hybrid scoring algorithm.

        Args:
            job_id: UUID of the job
            job_title: Title of the job position
            company_name: Name of the company
            user_embedding: User's profile embedding vector
            job_embedding: Job's embedding vector
            user_skills: User's skills list
            user_seniority: User's seniority level
            user_preferences: User's location preferences
            job_tags: Job's required skills/tags
            job_seniority: Job's required seniority
            job_location: Job location
            job_remote: Whether job is remote
            job_created_at: Job creation timestamp

        Returns:
            MatchExplanation with detailed breakdown and natural language explanations
        """

        # Calculate individual scores (0-1 range)
        similarity_score = embedding_service.calculate_similarity(user_embedding, job_embedding)
        skill_score = ScoringService.calculate_skill_overlap(user_skills, job_tags)
        seniority_score = ScoringService.calculate_seniority_match(user_seniority, job_seniority)
        recency_score = ScoringService.calculate_recency_decay(job_created_at)
        location_score = ScoringService.calculate_location_match(user_preferences, job_location, job_remote)

        # Weights from CLAUDE.md
        WEIGHT_SIMILARITY = 0.55
        WEIGHT_SKILLS = 0.20
        WEIGHT_SENIORITY = 0.10
        WEIGHT_RECENCY = 0.10
        WEIGHT_LOCATION = 0.05

        # Calculate overall score (0-100)
        overall_score = round((
            WEIGHT_SIMILARITY * similarity_score +
            WEIGHT_SKILLS * skill_score +
            WEIGHT_SENIORITY * seniority_score +
            WEIGHT_RECENCY * recency_score +
            WEIGHT_LOCATION * location_score
        ) * 100)

        # Generate explanations for each factor
        embedding_explanation = self._explain_embedding_similarity(
            similarity_score, WEIGHT_SIMILARITY
        )

        skill_explanation = self._explain_skill_overlap(
            user_skills, job_tags, skill_score, WEIGHT_SKILLS
        )

        seniority_explanation = self._explain_seniority_match(
            user_seniority, job_seniority, seniority_score, WEIGHT_SENIORITY
        )

        recency_explanation = self._explain_recency_decay(
            job_created_at, recency_score, WEIGHT_RECENCY
        )

        location_explanation = self._explain_location_match(
            user_preferences, job_location, job_remote, location_score, WEIGHT_LOCATION
        )

        # Generate overall summary
        overall_summary = self._generate_overall_summary(
            overall_score, job_title, company_name,
            similarity_score, skill_score, seniority_score
        )

        return MatchExplanation(
            job_id=job_id,
            job_title=job_title,
            company_name=company_name,
            overall_score=overall_score,
            overall_summary=overall_summary,
            embedding_similarity=embedding_explanation,
            skill_overlap=skill_explanation,
            seniority_match=seniority_explanation,
            recency_decay=recency_explanation,
            location_match=location_explanation
        )


# Global instance
match_explanation_service = MatchExplanationService()
