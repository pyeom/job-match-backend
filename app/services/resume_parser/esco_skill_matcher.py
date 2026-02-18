"""
ESCO-based semantic skill matching.

Uses a pre-built ESCO skills index with embeddings (all-MiniLM-L6-v2) for
semantic similarity matching. Also does exact substring matching for
high-precision hits. Reuses the app's existing embedding model instance.
"""

import logging
import os
import pickle
import re
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from app.core.config import settings
from app.schemas.resume_parser import ParsedSkills

logger = logging.getLogger(__name__)

# Certification patterns (regex-based — works well enough)
CERT_PATTERNS = [
    re.compile(r"(?i)(aws\s+certified[\w\s-]*)"),
    re.compile(r"(?i)(azure[\w\s-]*certified[\w\s-]*)"),
    re.compile(r"(?i)(google\s+cloud[\w\s-]*certified[\w\s-]*)"),
    re.compile(r"(?i)(pmp|project\s+management\s+professional)"),
    re.compile(r"(?i)(cpa|certified\s+public\s+accountant)"),
    re.compile(r"(?i)(cissp|cism|ceh|comptia[\w\s+-]*)"),
    re.compile(r"(?i)(certified\s+scrum\s*master|csm)"),
    re.compile(r"(?i)(six\s*sigma[\w\s-]*)"),
    re.compile(r"(?i)(itil[\w\s-]*)"),
    re.compile(r"(?i)(cisco[\w\s-]*certified|ccna|ccnp|ccie)"),
    re.compile(r"(?i)(oracle\s+certified[\w\s-]*)"),
    re.compile(r"(?i)(red\s+hat\s+certified[\w\s-]*)"),
    re.compile(r"(?i)(certified\s+kubernetes[\w\s-]*)"),
    re.compile(r"(?i)(terraform[\w\s-]*certified[\w\s-]*)"),
]


class EscoSkillMatcher:
    """
    Matches resume text against the ESCO skills taxonomy using
    semantic similarity and exact matching.
    """

    def __init__(self):
        self._index: Optional[Dict] = None
        self._model = None
        self._load_attempted = False

    def _load_index(self):
        """Lazy-load the ESCO index from disk."""
        if self._load_attempted:
            return
        self._load_attempted = True

        index_path = settings.esco_index_path
        if not os.path.exists(index_path):
            logger.warning(f"ESCO index not found at {index_path}. Skill matching will use fallback.")
            return

        try:
            with open(index_path, "rb") as f:
                self._index = pickle.load(f)
            logger.info(
                f"Loaded ESCO index: {len(self._index['labels'])} skills, "
                f"embeddings shape {self._index['embeddings'].shape}"
            )
        except Exception as e:
            logger.error(f"Failed to load ESCO index: {e}")
            self._index = None

    def _get_embedding_model(self):
        """Get the shared embedding model from embedding_service."""
        if self._model is not None:
            return self._model

        try:
            from app.services.embedding_service import embedding_service
            if embedding_service.is_available:
                self._model = embedding_service.model
                return self._model
        except Exception as e:
            logger.warning(f"Could not load shared embedding model: {e}")

        # Fallback: load our own model instance
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            return self._model
        except Exception as e:
            logger.error(f"Failed to load any embedding model: {e}")
            return None

    def match_skills(
        self,
        text: str,
        noun_chunks: Optional[List[str]] = None,
        skill_section_items: Optional[List[str]] = None,
        language: str = "en",
        experiences: Optional[List] = None,
        education: Optional[List] = None,
    ) -> ParsedSkills:
        """
        Match skills from resume text against the ESCO taxonomy.

        Args:
            text: Full resume text
            noun_chunks: Noun chunks extracted by SpaCy (optional)
            skill_section_items: Items from an explicit skills section (optional)
            language: Resume language code

        Returns:
            ParsedSkills with matched and categorized skills
        """
        self._load_index()

        # Collect candidate phrases
        candidates = self._extract_candidates(
            text, noun_chunks, skill_section_items, experiences, education
        )

        logger.info(
            f"Skill matching: {len(candidates)} candidates, "
            f"skill_section_items={skill_section_items}, "
            f"noun_chunks_count={len(noun_chunks) if noun_chunks else 0}"
        )

        technical: List[str] = []
        soft: List[str] = []
        matched_lower: Set[str] = set()

        if self._index is not None:
            # Semantic matching
            sem_tech, sem_soft, sem_matched = self._semantic_match(candidates)
            technical.extend(sem_tech)
            soft.extend(sem_soft)
            matched_lower.update(sem_matched)

            # Exact substring matching for high-precision hits
            exact_tech, exact_soft, exact_matched = self._exact_match(text)
            for s in exact_tech:
                if s.lower() not in matched_lower:
                    technical.append(s)
                    matched_lower.add(s.lower())
                    logger.info(f"Exact match (technical): '{s}'")
            for s in exact_soft:
                if s.lower() not in matched_lower:
                    soft.append(s)
                    matched_lower.add(s.lower())
                    logger.info(f"Exact match (soft): '{s}'")
        else:
            # Fallback: basic keyword matching (similar to old parser)
            technical, soft = self._fallback_match(text)
            matched_lower = {s.lower() for s in technical + soft}

        # Include unmatched skill section items as technical skills (user explicitly listed them)
        if skill_section_items:
            for item in skill_section_items:
                if item.lower() not in matched_lower and len(item) > 1:
                    technical.append(item)
                    matched_lower.add(item.lower())
                    logger.info(f"Passthrough skill section item: '{item}'")

        # Extract certifications (always regex)
        certifications = self._extract_certifications(text)

        # Deduplicate and cap
        technical = list(dict.fromkeys(technical))[:50]
        soft = list(dict.fromkeys(soft))[:20]
        certifications = list(dict.fromkeys(certifications))[:10]
        all_skills = list(dict.fromkeys(technical + soft))[:50]

        return ParsedSkills(
            technical_skills=technical,
            soft_skills=soft,
            certifications=certifications,
            all_skills=all_skills,
            # languages and language_proficiencies are set by coordinator
        )

    def _extract_description_candidates(
        self,
        experiences: Optional[List],
        education: Optional[List],
    ) -> List[str]:
        """
        Extract skill-like fragments from experience and education descriptions.

        Splits descriptions by sentence and delimiter boundaries to find
        short, skill-name-like fragments (e.g., "React", "Node.js", "Docker").
        Also does a targeted scan for tech terms that are language-agnostic.
        """
        candidates: List[str] = []

        # Delimiters to split within sentences (Spanish + English)
        split_pattern = re.compile(
            r"\s*(?:,\s*|\s+y\s+|\s+and\s+|\s+con\s+|\s+with\s+"
            r"|\s+using\s+|\s+como\s+|\s+such\s+as\s+"
            r"|\s*[/|·]\s*|\s*\(\s*|\s*\)\s*)\s*",
            re.IGNORECASE,
        )
        # Sentence boundary pattern
        sentence_boundary = re.compile(r"(?:\.\s+|;\s+|\n)")

        # Tech term regex — language-agnostic terms commonly found in descriptions
        # Captures terms like React, Node.js, C++, .NET, AWS, PostgreSQL etc.
        tech_term_pattern = re.compile(
            r"(?<![a-zA-Z])"
            r"("
            r"[A-Z][a-zA-Z]*(?:\.[jJ][sS]|\.NET|\.io)?"  # React, Node.js, .NET
            r"|[a-z]+(?:\.[jJ][sS])"                       # express.js, next.js
            r"|[A-Z]{2,}[a-z]*"                             # AWS, GCP, FastAPI
            r"|[A-Z][a-zA-Z]*(?:DB|SQL|ML|AI|UI|UX)"       # PostgreSQL, MongoDB, NoSQL
            r")"
            r"(?![a-zA-Z])"
        )

        def _extract_from_description(desc: str) -> None:
            """Extract skill candidates from a description string."""
            if not desc:
                return
            for sentence in sentence_boundary.split(desc):
                fragments = split_pattern.split(sentence.strip())
                for frag in fragments:
                    frag = frag.strip().strip(".-•*()[]:")
                    if 2 <= len(frag) <= 50:
                        candidates.append(frag)

            # Also scan for standalone tech terms in the raw description
            for m in tech_term_pattern.finditer(desc):
                term = m.group(1)
                if len(term) >= 2:
                    candidates.append(term)

        if experiences:
            for exp in experiences:
                # Extract from description
                desc = getattr(exp, "description", None) or ""
                title = getattr(exp, "title", None) or ""
                logger.info(f"Experience: title='{title}', desc_len={len(desc)}, desc_preview='{desc[:150]}'")
                _extract_from_description(desc)

                # Extract from job title
                title = getattr(exp, "title", None) or ""
                if title and title != "Unknown Position":
                    candidates.append(title)
                    # Also extract meaningful parts (e.g., "Full Stack Developer" -> "Full Stack")
                    title_words = title.split()
                    if len(title_words) > 2:
                        generic_suffixes = {
                            "developer", "engineer", "manager", "analyst",
                            "specialist", "consultant", "lead", "director",
                            "coordinator", "administrator", "arquitecto",
                            "desarrollador", "ingeniero",
                        }
                        if title_words[-1].lower() in generic_suffixes:
                            prefix = " ".join(title_words[:-1])
                            if len(prefix) > 2:
                                candidates.append(prefix)

        if education:
            for edu in education:
                _extract_from_description(getattr(edu, "description", None) or "")

                # Extract field_of_study and degree
                field = getattr(edu, "field_of_study", None) or ""
                if field:
                    candidates.append(field)
                degree = getattr(edu, "degree", None) or ""
                if degree and degree != "Degree":
                    candidates.append(degree)

        return candidates

    def _extract_candidates(
        self,
        text: str,
        noun_chunks: Optional[List[str]],
        skill_section_items: Optional[List[str]],
        experiences: Optional[List] = None,
        education: Optional[List] = None,
    ) -> List[str]:
        """Extract candidate phrases for skill matching."""
        candidates: List[str] = []

        # Add noun chunks from SpaCy
        if noun_chunks:
            candidates.extend(noun_chunks)

        # Add explicit skill section items
        if skill_section_items:
            candidates.extend(skill_section_items)

        # Add description-derived candidates from experience and education
        if experiences or education:
            desc_candidates = self._extract_description_candidates(experiences, education)
            candidates.extend(desc_candidates)
            logger.info(f"Description-derived candidates: {len(desc_candidates)}")
            logger.info(f"Description candidates sample: {desc_candidates[:30]}")

        # Extract comma/bullet separated items from skills-like sections
        # (these are often short skill names)
        skill_line_pattern = re.compile(
            r"(?:^|\n)\s*[-•*]\s*(.+?)(?:\n|$)"
        )
        for match in skill_line_pattern.finditer(text):
            item = match.group(1).strip()
            if len(item) < 60:  # Skill names are short
                # Split by commas if present
                if "," in item:
                    for sub in item.split(","):
                        sub = sub.strip()
                        if sub and len(sub) > 1:
                            candidates.append(sub)
                else:
                    candidates.append(item)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for c in candidates:
            c_lower = c.lower().strip()
            if c_lower and c_lower not in seen and len(c_lower) > 1:
                seen.add(c_lower)
                unique.append(c.strip())

        return unique

    def _semantic_match(
        self, candidates: List[str]
    ) -> Tuple[List[str], List[str], Set[str]]:
        """
        Match candidates against ESCO embeddings using cosine similarity.

        Returns (technical_skills, soft_skills, matched_lower_set)
        """
        if not candidates or self._index is None:
            return [], [], set()

        model = self._get_embedding_model()
        if model is None:
            return [], [], set()

        threshold = settings.esco_skill_similarity_threshold

        try:
            # Encode all candidates at once
            candidate_embeddings = model.encode(candidates, show_progress_bar=False)
            candidate_embeddings = np.array(candidate_embeddings, dtype=np.float32)

            # Normalize for cosine similarity via dot product
            norms = np.linalg.norm(candidate_embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1
            candidate_embeddings = candidate_embeddings / norms

            # Batch cosine similarity: (num_candidates, num_esco_skills)
            similarity_matrix = candidate_embeddings @ self._index["embeddings"].T

            technical = []
            soft = []
            matched_lower: Set[str] = set()

            for i, candidate in enumerate(candidates):
                best_idx = np.argmax(similarity_matrix[i])
                best_score = similarity_matrix[i][best_idx]

                if best_score >= threshold:
                    matched_label = self._index["labels"][best_idx]
                    category = self._index["categories"][best_idx]

                    if matched_label.lower() in matched_lower:
                        continue
                    matched_lower.add(matched_label.lower())

                    logger.info(f"Semantic match: '{candidate}' -> '{matched_label}' (score={best_score:.3f}, cat={category})")

                    if category in ("technical", "knowledge"):
                        technical.append(matched_label)
                    else:
                        soft.append(matched_label)
                elif best_score >= threshold - 0.15:
                    # Log near-misses for tuning
                    near_label = self._index["labels"][best_idx]
                    logger.info(f"Near-miss: '{candidate}' -> '{near_label}' (score={best_score:.3f}, threshold={threshold})")

            return technical, soft, matched_lower

        except Exception as e:
            logger.error(f"Semantic skill matching failed: {e}")
            return [], [], set()

    def _exact_match(self, text: str) -> Tuple[List[str], List[str], Set[str]]:
        """
        Exact substring match against ESCO labels for high-precision hits.

        Returns (technical_skills, soft_skills, matched_lower_set)
        """
        if self._index is None:
            return [], [], set()

        text_lower = text.lower()
        technical = []
        soft = []
        matched_lower: Set[str] = set()

        labels = self._index["labels"]
        labels_lower = self._index["labels_lower"]
        categories = self._index["categories"]

        for idx, label_lower in enumerate(labels_lower):
            # Only match labels that are at least 3 chars (avoid false positives)
            if len(label_lower) < 3:
                continue

            # Word boundary check: the label should appear as a whole word/phrase
            if label_lower in text_lower:
                # Verify word boundaries
                pos = text_lower.find(label_lower)
                if pos >= 0:
                    before = text_lower[pos - 1] if pos > 0 else " "
                    after_pos = pos + len(label_lower)
                    after = text_lower[after_pos] if after_pos < len(text_lower) else " "

                    if not before.isalnum() and not after.isalnum():
                        label = labels[idx]
                        if label.lower() not in matched_lower:
                            matched_lower.add(label.lower())
                            category = categories[idx]
                            if category in ("technical", "knowledge"):
                                technical.append(label)
                            else:
                                soft.append(label)

        return technical, soft, matched_lower

    def _fallback_match(self, text: str) -> Tuple[List[str], List[str]]:
        """Fallback keyword matching when ESCO index is unavailable."""
        text_lower = text.lower()

        fallback_technical = {
            "python", "javascript", "typescript", "java", "c++", "c#", "ruby", "go",
            "golang", "rust", "swift", "kotlin", "php", "scala", "react", "vue",
            "angular", "node.js", "django", "flask", "fastapi", "spring", "docker",
            "kubernetes", "aws", "azure", "gcp", "sql", "postgresql", "mongodb",
            "redis", "git", "linux", "tensorflow", "pytorch", "machine learning",
            "deep learning", "html", "css", "sass", "tailwind", "webpack", "graphql",
            "rest", "restful", "elasticsearch", "kafka", "spark", "pandas", "numpy",
            "react native", "flutter", "bootstrap", "next.js", "express",
            "nginx", "github", "gitlab", "jenkins", "terraform",
        }
        fallback_soft = {
            "leadership", "communication", "teamwork", "problem solving",
            "analytical", "critical thinking", "time management",
            "project management", "agile", "scrum", "collaboration",
            "mentoring", "presentation", "negotiation", "adaptability",
        }

        # Use word boundary matching to prevent "go" in "mongodb", "java" in "javascript"
        technical = []
        for s in fallback_technical:
            pattern = re.compile(r"\b" + re.escape(s) + r"\b", re.IGNORECASE)
            if pattern.search(text_lower):
                technical.append(s.title() if s.islower() else s)

        soft = []
        for s in fallback_soft:
            pattern = re.compile(r"\b" + re.escape(s) + r"\b", re.IGNORECASE)
            if pattern.search(text_lower):
                soft.append(s.title())

        return technical, soft

    def _extract_certifications(self, text: str) -> List[str]:
        """Extract certification mentions using regex patterns."""
        certifications = []
        for pattern in CERT_PATTERNS:
            matches = pattern.findall(text)
            certifications.extend([m.strip() for m in matches if m.strip()])
        return list(dict.fromkeys(certifications))
