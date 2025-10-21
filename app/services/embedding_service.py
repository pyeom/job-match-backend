import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating embeddings using sentence-transformers"""
    
    def __init__(self):
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load the sentence transformer model"""
        try:
            logger.info(f"Loading embedding model: {settings.embedding_model}")
            self.model = SentenceTransformer(settings.embedding_model)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    
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
    
    def generate_user_embedding(self, headline: Optional[str] = None, skills: Optional[List[str]] = None, preferences: Optional[List[str]] = None) -> List[float]:
        """Generate embedding for a user profile
        
        Args:
            headline: User's professional headline
            skills: List of user skills
            preferences: List of job preferences/locations
            
        Returns:
            List of float values representing the embedding
        """
        text_parts = []
        
        if headline:
            text_parts.append(headline)
        
        if skills:
            text_parts.append(" ".join(skills))
        
        if preferences:
            text_parts.append(" ".join(preferences))
        
        if not text_parts:
            # Return a default/zero embedding if no profile data
            return [0.0] * 384  # Dimension for all-MiniLM-L6-v2
        
        combined_text = " | ".join(text_parts)
        
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