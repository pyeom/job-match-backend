import math
from typing import List, Optional
from datetime import datetime, timezone
from app.services.embedding_service import embedding_service


class ScoringService:
    """Service for scoring job matches based on ML + rules as described in CLAUDE.md"""
    
    @staticmethod
    def calculate_skill_overlap(user_skills: Optional[List[str]], job_tags: Optional[List[str]]) -> float:
        """Calculate skill overlap score (0-1)"""
        if not user_skills or not job_tags:
            return 0.0
        
        user_skills_lower = [skill.lower() for skill in user_skills]
        job_tags_lower = [tag.lower() for tag in job_tags]
        
        common_skills = set(user_skills_lower) & set(job_tags_lower)
        
        if len(job_tags_lower) == 0:
            return 0.0
        
        return len(common_skills) / len(job_tags_lower)
    
    @staticmethod
    def calculate_seniority_match(user_seniority: Optional[str], job_seniority: Optional[str]) -> float:
        """Calculate seniority match score (0-1)"""
        if not user_seniority or not job_seniority:
            return 0.5  # Default score for missing data
        
        # Define seniority hierarchy
        seniority_levels = {
            "junior": 1,
            "mid": 2,
            "senior": 3,
            "lead": 4,
            "staff": 5,
            "principal": 6
        }
        
        user_level = seniority_levels.get(user_seniority.lower(), 2)
        job_level = seniority_levels.get(job_seniority.lower(), 2)
        
        if user_level == job_level:
            return 1.0  # Exact match
        elif abs(user_level - job_level) == 1:
            return 0.5  # Adjacent level
        else:
            return 0.0  # Too far apart
    
    @staticmethod
    def calculate_recency_decay(job_created_at: datetime) -> float:
        """Calculate recency decay score (0-1) - newer jobs get higher scores"""
        now = datetime.now(timezone.utc)
        hours_old = (now - job_created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        
        # Exponential decay with 72-hour half-life
        decay = math.exp(-hours_old / 72)
        return min(1.0, decay)
    
    @staticmethod
    def calculate_location_match(user_preferences: Optional[List[str]], job_location: Optional[str], job_remote: bool = False) -> float:
        """Calculate location match score (0-1)"""
        if job_remote:
            return 1.0  # Remote jobs match everyone
        
        if not user_preferences or not job_location:
            return 0.5  # Default score for missing data
        
        user_preferences_lower = [pref.lower() for pref in user_preferences]
        job_location_lower = job_location.lower()
        
        # Check if job location is in user preferences
        for preference in user_preferences_lower:
            if preference in job_location_lower or job_location_lower in preference:
                return 1.0
        
        return 0.0
    
    @staticmethod
    def calculate_job_score(
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
    ) -> int:
        """Calculate comprehensive job score (0-100) using the formula from CLAUDE.md
        
        Score = 0.55 * similarity + 0.20 * skill_overlap + 0.10 * seniority_match + 
                0.10 * recency_decay + 0.05 * location_match
        """
        
        # 1. Embedding similarity (0.55 weight)
        similarity_score = embedding_service.calculate_similarity(user_embedding, job_embedding)
        
        # 2. Skill overlap (0.20 weight)
        skill_score = ScoringService.calculate_skill_overlap(user_skills, job_tags)
        
        # 3. Seniority match (0.10 weight)
        seniority_score = ScoringService.calculate_seniority_match(user_seniority, job_seniority)
        
        # 4. Recency decay (0.10 weight)
        recency_score = ScoringService.calculate_recency_decay(job_created_at)
        
        # 5. Location match (0.05 weight)
        location_score = ScoringService.calculate_location_match(user_preferences, job_location, job_remote)
        
        # Calculate weighted final score
        final_score = (
            0.55 * similarity_score +
            0.20 * skill_score +
            0.10 * seniority_score +
            0.10 * recency_score +
            0.05 * location_score
        )
        
        # Convert to integer (0-100)
        return round(final_score * 100)


# Global instance
scoring_service = ScoringService()