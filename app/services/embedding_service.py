import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating embeddings using sentence-transformers"""

    def __init__(self):
        self._model = None
        self._load_attempted = False
        self._load_error = None

    @property
    def model(self):
        """Lazy load the model on first access"""
        if self._model is None and not self._load_attempted:
            self._load_model()
        if self._model is None:
            raise RuntimeError(
                f"Embedding model not available. {self._load_error or 'Model not loaded.'} "
                "Call /api/v1/health/embeddings to check status or retry loading."
            )
        return self._model

    @property
    def is_available(self) -> bool:
        """Check if the embedding model is loaded and available"""
        if self._model is not None:
            return True
        if not self._load_attempted:
            self._load_model()
        return self._model is not None

    def _load_model(self):
        """Load the sentence transformer model"""
        self._load_attempted = True
        try:
            logger.info(f"Loading embedding model: {settings.embedding_model}")
            self._model = SentenceTransformer(settings.embedding_model)
            self._load_error = None
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            self._load_error = str(e)
            logger.error(f"Failed to load embedding model: {e}")

    def retry_load(self) -> bool:
        """Retry loading the model. Returns True if successful."""
        self._load_attempted = False
        self._load_model()
        return self._model is not None
    
    async def generate_job_embedding(self, job_text: str) -> List[float]:
        """Generate embedding for a job posting from combined text
        
        Args:
            job_text: Combined text (title + company + tags + description)
            
        Returns:
            List of float values representing the embedding
        """
        try:
            embedding = self.model.encode(job_text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to generate job embedding: {e}")
            raise
    
    def generate_job_embedding_from_parts(
        self,
        title: str,
        company: str,
        short_description: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[float]:
        """Generate embedding for a job posting

        Args:
            title: Job title
            company: Company name
            short_description: Brief job description for cards (preferred for embedding)
            description: Full job description (fallback)
            tags: List of skills/tags (optional)

        Returns:
            List of float values representing the embedding
        """
        # Combine job information into a single text
        text_parts = [title, company]

        if tags:
            text_parts.append(" ".join(tags))

        # Prioritize short_description for embedding, fallback to description
        desc_to_use = short_description or description
        if desc_to_use:
            # Truncate description to prevent very long texts
            desc_to_use = desc_to_use[:500] if len(desc_to_use) > 500 else desc_to_use
            text_parts.append(desc_to_use)

        combined_text = " | ".join(text_parts)
        
        try:
            embedding = self.model.encode(combined_text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to generate job embedding: {e}")
            raise
    
    def build_experience_summary(self, experience: list) -> Optional[str]:
        """Build a text summary from top 3 experiences.

        Handles both dict (from DB JSON columns) and object (from parsed data) formats.
        """
        if not experience:
            return None

        parts = []
        for exp in experience[:3]:
            if isinstance(exp, dict):
                title = exp.get("title", "")
                company = exp.get("company", "")
                desc = exp.get("description", "") or ""
            else:
                title = getattr(exp, "title", "")
                company = getattr(exp, "company", "")
                desc = getattr(exp, "description", "") or ""

            entry = f"{title} at {company}"
            if desc:
                entry += f": {desc[:80]}"
            parts.append(entry)

        return "; ".join(parts) if parts else None

    def build_education_summary(self, education: list) -> Optional[str]:
        """Build a text summary from top 2 education entries.

        Handles both dict (from DB JSON columns) and object (from parsed data) formats.
        """
        if not education:
            return None

        parts = []
        for edu in education[:2]:
            if isinstance(edu, dict):
                degree = edu.get("degree", "")
                field = edu.get("field_of_study", "")
                institution = edu.get("institution", "")
            else:
                degree = getattr(edu, "degree", "")
                field = getattr(edu, "field_of_study", "")
                institution = getattr(edu, "institution", "")

            entry_parts = [p for p in [degree, field] if p]
            entry = " ".join(entry_parts)
            if institution:
                entry += f" at {institution}"
            if entry.strip():
                parts.append(entry.strip())

        return "; ".join(parts) if parts else None

    def generate_user_embedding(
        self,
        headline: Optional[str] = None,
        skills: Optional[List[str]] = None,
        preferences: Optional[List[str]] = None,
        bio: Optional[str] = None,
        experience_text: Optional[str] = None,
        education_text: Optional[str] = None
    ) -> List[float]:
        """Generate embedding for a user profile

        Args:
            headline: User's professional headline
            skills: List of user skills
            preferences: List of job preferences/locations
            bio: User's bio/summary text
            experience_text: Pre-built experience summary
            education_text: Pre-built education summary

        Returns:
            List of float values representing the embedding
        """
        text_parts = []

        if headline:
            text_parts.append(headline)

        if bio:
            text_parts.append(bio[:150])

        if skills:
            text_parts.append(" ".join(skills))

        if experience_text:
            text_parts.append(experience_text[:200])

        if education_text:
            text_parts.append(education_text[:100])

        if preferences:
            text_parts.append(" ".join(preferences))

        if not text_parts:
            # Return a default/zero embedding if no profile data
            return [0.0] * 384  # Dimension for all-MiniLM-L6-v2

        combined_text = " | ".join(text_parts)
        # Hard cap to stay within model's 256-token limit
        combined_text = combined_text[:900]

        logger.info(f"Generating user embedding from: {combined_text[:120]}...")

        try:
            embedding = self.model.encode(combined_text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to generate user embedding: {e}")
            raise
    
    def update_user_embedding_with_history(
        self, 
        base_embedding: List[float], 
        liked_job_embeddings: List[List[float]], 
        alpha: float = 0.3
    ) -> List[float]:
        """Update user embedding based on liked jobs history
        
        Args:
            base_embedding: Original user profile embedding
            liked_job_embeddings: List of embeddings from jobs user swiped RIGHT
            alpha: Weight for base profile (0.3 = 30% profile, 70% history)
            
        Returns:
            Updated user embedding
        """
        if not liked_job_embeddings:
            return base_embedding
        
        try:
            base_array = np.array(base_embedding)
            history_arrays = [np.array(emb) for emb in liked_job_embeddings]
            
            # Calculate mean of historical job embeddings
            history_mean = np.mean(history_arrays, axis=0)
            
            # Combine with weighted average
            updated_embedding = alpha * base_array + (1 - alpha) * history_mean
            
            # Normalize the embedding
            norm = np.linalg.norm(updated_embedding)
            if norm > 0:
                updated_embedding = updated_embedding / norm
            
            return updated_embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to update user embedding: {e}")
            return base_embedding
    
    def calculate_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Calculate cosine similarity between two embeddings
        
        Args:
            embedding1: First embedding
            embedding2: Second embedding
            
        Returns:
            Cosine similarity score (0-1)
        """
        try:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)
            
            # Calculate cosine similarity
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            similarity = dot_product / (norm1 * norm2)
            # Convert to float if numpy scalar, ensure similarity is between 0 and 1
            similarity_float = float(similarity)
            return max(0.0, min(1.0, similarity_float))
            
        except Exception as e:
            logger.error(f"Failed to calculate similarity: {e}")
            return 0.0


# Global instance
embedding_service = EmbeddingService()