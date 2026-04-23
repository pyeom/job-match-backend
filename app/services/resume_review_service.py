"""
AI-powered resume review service.

This service analyzes resumes and provides actionable improvement suggestions.
It evaluates structure, content, keywords, formatting, and relevance to target jobs.
Supports English, Spanish, and Portuguese resumes.
"""

from typing import Optional, List, Dict, Set
from uuid import UUID
from dataclasses import dataclass, field
import asyncio
import hashlib
import json
import re
import logging

from app.schemas.resume_review import (
    ResumeReviewResponse,
    ResumeSection,
    KeywordAnalysis
)
from app.models.document import Document
from app.models.job import Job
from app.services.resume_parser_service import ResumeParserService

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# Cache TTL: 30 days in seconds
_REVIEW_CACHE_TTL = 2_592_000

# JSON schema — defined once, shared across all language prompts
_SCHEMA = (
    '{"summary":str,"strengths":[str],"weaknesses":[str],'
    '"top_suggestions":[str],"section_feedback":{"<section>":'
    '{"strengths":[str],"weaknesses":[str],"suggestions":[str]}}}'
)

# i18n system prompts — one per language, referencing the shared schema
_PROMPTS: Dict[str, str] = {
    "en": (
        "Expert resume reviewer. Output ONLY valid JSON, no markdown.\n"
        f"Schema: {_SCHEMA}\n"
        "Rules: specific+actionable, reference real content, empty arrays not null, "
        "max 5 items per list, max 7 top_suggestions."
    ),
    "es": (
        "Revisor experto de currículums. Responde SOLO con JSON válido, sin markdown.\n"
        f"Esquema: {_SCHEMA}\n"
        "Reglas: específico y accionable, referencia contenido real, arrays vacíos no null, "
        "máx 5 items por lista, máx 7 top_suggestions."
    ),
    "pt": (
        "Revisor especialista de currículos. Responda APENAS com JSON válido, sem markdown.\n"
        f"Esquema: {_SCHEMA}\n"
        "Regras: específico e acionável, referencie conteúdo real, arrays vazios não null, "
        "máx 5 itens por lista, máx 7 top_suggestions."
    ),
}
_DEFAULT_LANG = "en"

# Simple vocabulary sets used for heuristic language detection
_ES_MARKERS: Set[str] = {
    "experiencia", "educación", "educacion", "habilidades", "resumen",
    "objetivo", "formación", "formacion", "logros", "idiomas", "referencias",
}
_PT_MARKERS: Set[str] = {
    "experiência", "experiencia", "educação", "educacao", "habilidades",
    "resumo", "objetivo", "formação", "formacao", "conquistas", "idiomas",
    "referências", "referencias",
}


def _detect_language(text: str) -> str:
    """Heuristic language detection — returns 'en', 'es', or 'pt'."""
    sample = text[:2000].lower()
    words = set(re.findall(r"[a-záéíóúàâãêôõüñç]+", sample))
    pt_hits = len(words & _PT_MARKERS)
    es_hits = len(words & _ES_MARKERS)
    # Portuguese marker set is a superset of some Spanish words, so require
    # at least one unique Portuguese marker (ã/ê/õ/ç accent signals).
    pt_unique = bool(re.search(r"[ãâêôõç]", sample))
    if pt_hits >= 2 and pt_unique:
        return "pt"
    if es_hits >= 2:
        return "es"
    return "en"


@dataclass
class LLMReviewResult:
    """Structured result from the LLM resume analysis."""

    summary: str
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    top_suggestions: List[str] = field(default_factory=list)
    section_feedback: Dict[str, Dict] = field(default_factory=dict)


class ResumeReviewService:
    """Service for analyzing resumes and generating improvement suggestions."""

    # Common resume sections to look for (English and Spanish)
    EXPECTED_SECTIONS = {
        # English
        "contact", "summary", "objective", "experience", "work", "employment",
        "education", "skills", "projects", "certifications", "achievements",
        "awards", "publications", "languages",
        # Spanish
        "contacto", "resumen", "perfil", "objetivo", "experiencia", "empleo",
        "educación", "educacion", "formación", "formacion", "habilidades",
        "aptitudes", "competencias", "proyectos", "certificaciones", "logros",
        "premios", "publicaciones", "idiomas"
    }

    # Use section patterns from the resume parser for multilingual support
    SECTION_PATTERNS = ResumeParserService.SECTION_PATTERNS

    # Keywords indicating quantified achievements (English and Spanish)
    QUANTIFICATION_KEYWORDS = [
        r'\d+%', r'\$\d+', r'€\d+', r'\d+\+', r'\d+x', r'\d+ million', r'\d+ billion',
        r'\d+ thousand', r'\d+ millones', r'\d+ mil',
        # English
        r'increased', r'decreased', r'reduced', r'improved', r'grew', r'generated', r'saved', r'achieved',
        # Spanish
        r'aumenté', r'aumente', r'incrementé', r'incremente', r'reduje', r'disminuí', r'disminui',
        r'mejoré', r'mejore', r'crecí', r'creci', r'generé', r'genere', r'ahorré', r'ahorre',
        r'logré', r'logre'
    ]

    # Contact information patterns
    CONTACT_PATTERNS = [
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # Phone number
        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # Phone with area code
    ]

    # Action verbs for strong resume writing (English and Spanish)
    STRONG_ACTION_VERBS = {
        # English
        "led", "managed", "developed", "created", "implemented", "designed",
        "achieved", "improved", "increased", "reduced", "launched", "built",
        "established", "coordinated", "directed", "executed", "optimized",
        "streamlined", "delivered", "drove", "spearheaded", "initiated",
        # Spanish
        "lideré", "lidere", "gestioné", "gestione", "desarrollé", "desarrolle",
        "creé", "cree", "implementé", "implemente", "diseñé", "diseñe",
        "logré", "logre", "mejoré", "mejore", "aumenté", "aumente",
        "reduje", "lancé", "lance", "construí", "construi", "establecí",
        "estableci", "coordiné", "coordine", "dirigí", "dirigi", "ejecuté",
        "ejecute", "optimicé", "optimice", "entregué", "entregue", "impulsé",
        "impulse", "inicié", "inicie", "supervisé", "supervise"
    }

    def __init__(self) -> None:
        self._async_client = None
        self._redis_client = None

    # ------------------------------------------------------------------
    # Redis cache (async client, lazy-initialized)
    # ------------------------------------------------------------------

    async def _get_redis(self):
        """Return a lazy-initialized async Redis client, or None on error."""
        if self._redis_client is not None:
            return self._redis_client
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings
            self._redis_client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            return self._redis_client
        except Exception as exc:
            logger.warning("Failed to init Redis for review cache: %s", exc)
            return None

    async def _cache_get(self, key: str) -> Optional[LLMReviewResult]:
        """Read a cached LLMReviewResult. Returns None on miss or error."""
        try:
            r = await self._get_redis()
            if r is None:
                return None
            raw = await r.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            raw_sf: Dict[str, Dict] = data.get("section_feedback") or {}
            return LLMReviewResult(
                summary=str(data.get("summary") or ""),
                strengths=list(data.get("strengths") or []),
                weaknesses=list(data.get("weaknesses") or []),
                top_suggestions=list(data.get("top_suggestions") or []),
                section_feedback={k.lower(): v for k, v in raw_sf.items()},
            )
        except Exception as exc:
            logger.debug("Review cache read error (ignored): %s", exc)
            return None

    async def _cache_set(self, key: str, result: LLMReviewResult) -> None:
        """Write an LLMReviewResult to cache. Silently ignores errors."""
        try:
            r = await self._get_redis()
            if r is None:
                return
            payload = json.dumps({
                "summary": result.summary,
                "strengths": result.strengths,
                "weaknesses": result.weaknesses,
                "top_suggestions": result.top_suggestions,
                "section_feedback": result.section_feedback,
            })
            await r.set(key, payload, ex=_REVIEW_CACHE_TTL)
        except Exception as exc:
            logger.debug("Review cache write error (ignored): %s", exc)

    def _get_async_client(self):
        """Lazy-initialise an async OpenAI-compatible client for DashScope.

        Returns None if DASHSCOPE_API_KEY is not configured.
        """
        try:
            from app.core.config import settings
            import openai

            if not settings.dashscope_api_key:
                return None

            if self._async_client is None:
                self._async_client = openai.AsyncOpenAI(
                    api_key=settings.dashscope_api_key,
                    base_url=DASHSCOPE_BASE_URL,
                )
            return self._async_client
        except Exception as exc:
            logger.warning(f"Could not initialise DashScope async client: {exc}")
            return None

    @staticmethod
    def _build_structured_input(
        resume_text: str,
        rule_scores: Dict[str, float],
        sections: List[ResumeSection],
        target_job: Optional[Job] = None,
    ) -> str:
        """Build a compact, token-efficient structured summary of the resume.

        Replaces the raw resume_text[:4000] blob sent to the LLM.
        Stays well under 400 tokens for typical resumes.
        """
        structure = round(rule_scores.get("structure", 0) * 100)
        content = round(rule_scores.get("content", 0) * 100)
        formatting = round(rule_scores.get("formatting", 0) * 100)

        # Extract first non-empty line as a best-effort candidate name
        first_line = next(
            (ln.strip() for ln in resume_text.splitlines() if ln.strip()),
            "",
        )

        section_names = ", ".join(s.section_name for s in sections) if sections else "none detected"

        lines = [
            f"CANDIDATE: {first_line}" if first_line else "",
            f"SECTIONS FOUND: {section_names}",
            f"RULE SCORES: structure={structure}/100, content={content}/100, formatting={formatting}/100",
        ]

        # Add per-section brief (name + score only — no full text)
        for sec in sections:
            lines.append(f"SECTION {sec.section_name.upper()}: score={round(sec.score * 100)}/100")

        if target_job:
            job_line = f"TARGET JOB: {target_job.title}"
            if target_job.tags:
                job_line += f" | tags: {', '.join(target_job.tags[:10])}"
            lines.append(job_line)

        return "\n".join(ln for ln in lines if ln)

    async def _llm_analyze(
        self,
        resume_text: str,
        rule_scores: Dict[str, float],
        sections: List[ResumeSection],
        language: str,
        target_job: Optional[Job] = None,
    ) -> Optional[LLMReviewResult]:
        """Call Qwen via DashScope to produce narrative resume feedback.

        Returns None on any failure so the caller can fall back gracefully.
        """
        try:
            from app.core.config import settings
            client = self._get_async_client()
            if client is None:
                return None

            # Normalise language code: "pt-BR" -> "pt", "en-US" -> "en"
            lang = language.lower().split("-")[0].split("_")[0]
            system_prompt = _PROMPTS.get(lang, _PROMPTS[_DEFAULT_LANG])

            # Build compact structured input (instead of raw resume_text[:4000])
            structured_input = self._build_structured_input(
                resume_text, rule_scores, sections, target_job
            )

            # Cache key includes language so different prompt variants don't collide
            target_job_id_str = str(target_job.id) if target_job else "none"
            cache_key = (
                f"resume_review_llm:{lang}:"
                + hashlib.sha256(structured_input.encode()).hexdigest()[:32]
                + f":{target_job_id_str}"
            )

            cached = await self._cache_get(cache_key)
            if cached is not None:
                logger.debug("Review LLM cache hit for key %s…", cache_key[:32])
                return cached

            response = await client.chat.completions.create(
                model=settings.qwen_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_input},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1500,
                timeout=25,
            )

            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)

            # Normalise section_feedback keys to lowercase for merging
            raw_section_feedback: Dict[str, Dict] = data.get("section_feedback") or {}
            normalised_section_feedback: Dict[str, Dict] = {
                k.lower(): v for k, v in raw_section_feedback.items()
            }

            result = LLMReviewResult(
                summary=str(data.get("summary") or ""),
                strengths=list(data.get("strengths") or []),
                weaknesses=list(data.get("weaknesses") or []),
                top_suggestions=list(data.get("top_suggestions") or []),
                section_feedback=normalised_section_feedback,
            )

            await self._cache_set(cache_key, result)

            return result

        except Exception as exc:
            logger.warning("LLM resume analysis failed, using rule-based fallback: %s", exc)
            return None

    async def analyze_resume(
        self,
        resume_text: str,
        resume_document: Document,
        target_job: Optional[Job] = None
    ) -> ResumeReviewResponse:
        """
        Analyze a resume and generate comprehensive review.

        Args:
            resume_text: Extracted text from the resume
            resume_document: Document model instance
            target_job: Optional target job for relevance analysis

        Returns:
            ResumeReviewResponse with scores and suggestions
        """
        try:
            # Analyze basic resume properties
            word_count = self._count_words(resume_text)
            has_contact = self._check_contact_info(resume_text)
            has_quantified = self._check_quantified_achievements(resume_text)

            # Analyze sections
            sections = self._analyze_sections(resume_text)
            structure_score = self._calculate_structure_score(sections, resume_text)

            # Analyze content quality
            content_score = self._calculate_content_score(
                resume_text, has_quantified, word_count
            )

            # Analyze formatting
            formatting_score = self._calculate_formatting_score(resume_text, word_count)

            # Keyword analysis if target job provided
            keyword_analysis = None
            relevance_score = None
            if target_job:
                keyword_analysis = self._analyze_keywords(resume_text, target_job)
                relevance_score = keyword_analysis.keyword_density_score

            # Calculate overall score (always rule-based)
            overall_score = self._calculate_overall_score(
                structure_score,
                content_score,
                formatting_score,
                relevance_score
            )

            # Generate rule-based insights (used as fallback)
            strengths = self._identify_strengths(
                resume_text, has_contact, has_quantified, structure_score, content_score
            )
            weaknesses = self._identify_weaknesses(
                resume_text, has_contact, has_quantified, structure_score,
                content_score, sections, word_count
            )
            top_suggestions = self._generate_top_suggestions(
                weaknesses, has_quantified, sections, target_job, keyword_analysis
            )

            # Generate rule-based executive summary (fallback)
            summary = self._generate_summary(
                overall_score, strengths, weaknesses, target_job
            )

            # LLM enhancement — narrative fields are replaced when available
            rule_scores = {
                "structure": structure_score,
                "content": content_score,
                "formatting": formatting_score,
            }

            # Optimisation: skip LLM entirely for very low-quality resumes
            # (rule-based analysis is already the right output for them)
            llm_result = None
            if overall_score >= 40:
                language = _detect_language(resume_text)
                llm_result = await self._llm_analyze(
                    resume_text=resume_text,
                    rule_scores=rule_scores,
                    sections=sections,
                    language=language,
                    target_job=target_job,
                )

            if llm_result:
                # LLM wins for all narrative fields
                if llm_result.summary:
                    summary = llm_result.summary
                if llm_result.strengths:
                    strengths = llm_result.strengths
                if llm_result.weaknesses:
                    weaknesses = llm_result.weaknesses
                if llm_result.top_suggestions:
                    top_suggestions = llm_result.top_suggestions

                # Merge per-section feedback (normalise section names to lowercase for lookup)
                if llm_result.section_feedback:
                    for section in sections:
                        key = section.section_name.lower()
                        fb = llm_result.section_feedback.get(key)
                        if fb:
                            if fb.get("strengths"):
                                section.strengths = list(fb["strengths"])
                            if fb.get("weaknesses"):
                                section.weaknesses = list(fb["weaknesses"])
                            if fb.get("suggestions"):
                                section.suggestions = list(fb["suggestions"])

            return ResumeReviewResponse(
                document_id=resume_document.id,
                target_job_id=target_job.id if target_job else None,
                overall_score=overall_score,
                structure_score=structure_score,
                content_score=content_score,
                formatting_score=formatting_score,
                relevance_score=relevance_score,
                summary=summary,
                sections=sections,
                keyword_analysis=keyword_analysis,
                top_suggestions=top_suggestions,
                strengths=strengths,
                weaknesses=weaknesses,
                word_count=word_count,
                has_contact_info=has_contact,
                has_quantified_achievements=has_quantified
            )

        except Exception as e:
            logger.error(f"Error analyzing resume {resume_document.id}: {e}")
            raise

    def _count_words(self, text: str) -> int:
        """Count words in text."""
        return len(text.split())

    def _check_contact_info(self, text: str) -> bool:
        """Check if resume contains contact information."""
        for pattern in self.CONTACT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _check_quantified_achievements(self, text: str) -> bool:
        """Check if resume contains quantified achievements."""
        for pattern in self.QUANTIFICATION_KEYWORDS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _analyze_sections(self, text: str) -> List[ResumeSection]:
        """Analyze individual sections of the resume."""
        sections = []
        lines = text.split('\n')

        # Detect major sections
        detected_sections = self._detect_sections(lines)

        for section_name, section_content in detected_sections.items():
            section_analysis = self._analyze_section(section_name, section_content)
            sections.append(section_analysis)

        return sections

    def _detect_sections(self, lines: List[str]) -> Dict[str, str]:
        """Detect major sections in the resume using multilingual patterns."""
        sections = {}
        current_section = "header"
        current_content = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                current_content.append("")
                continue

            # Check if line matches any section pattern (multilingual)
            section_found = None
            for section_name, pattern in self.SECTION_PATTERNS.items():
                if re.match(pattern, line_stripped):
                    section_found = section_name
                    break

            # Fallback: check for simple keyword match
            if not section_found:
                line_lower = line_stripped.lower()
                for section_keyword in self.EXPECTED_SECTIONS:
                    if section_keyword in line_lower and len(line_stripped.split()) <= 4:
                        section_found = section_keyword
                        break

            if section_found:
                # Save previous section
                if current_content:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = section_found
                current_content = []
            else:
                current_content.append(line)

        # Save last section
        if current_content:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    def _analyze_section(self, section_name: str, content: str) -> ResumeSection:
        """Analyze a specific resume section."""
        strengths = []
        weaknesses = []
        suggestions = []
        score = 0.7  # Default moderate score

        content_lower = content.lower()
        word_count = len(content.split())

        # Section-specific analysis
        if section_name in ["experience", "work", "employment"]:
            score, section_strengths, section_weaknesses, section_suggestions = \
                self._analyze_experience_section(content, word_count)
            strengths.extend(section_strengths)
            weaknesses.extend(section_weaknesses)
            suggestions.extend(section_suggestions)

        elif section_name in ["skills"]:
            score, section_strengths, section_weaknesses, section_suggestions = \
                self._analyze_skills_section(content)
            strengths.extend(section_strengths)
            weaknesses.extend(section_weaknesses)
            suggestions.extend(section_suggestions)

        elif section_name in ["education"]:
            score, section_strengths, section_weaknesses, section_suggestions = \
                self._analyze_education_section(content)
            strengths.extend(section_strengths)
            weaknesses.extend(section_weaknesses)
            suggestions.extend(section_suggestions)

        else:
            # Generic section analysis
            if word_count > 20:
                strengths.append(f"Section has substantial content ({word_count} words)")
                score += 0.1
            elif word_count < 10:
                weaknesses.append("Section appears too brief")
                suggestions.append(f"Expand the {section_name} section with more details")
                score -= 0.2

        return ResumeSection(
            section_name=section_name.capitalize(),
            score=max(0.0, min(1.0, score)),
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions
        )

    def _analyze_experience_section(
        self, content: str, word_count: int
    ) -> tuple[float, List[str], List[str], List[str]]:
        """Analyze experience/work section."""
        score = 0.6
        strengths = []
        weaknesses = []
        suggestions = []

        # Check for action verbs
        action_verb_count = sum(
            1 for verb in self.STRONG_ACTION_VERBS
            if re.search(rf'\b{verb}\b', content, re.IGNORECASE)
        )

        if action_verb_count >= 3:
            strengths.append(f"Uses {action_verb_count} strong action verbs")
            score += 0.15
        else:
            weaknesses.append("Limited use of strong action verbs")
            suggestions.append("Start bullet points with strong action verbs (led, developed, achieved)")

        # Check for quantified results
        has_numbers = bool(re.search(r'\d+', content))
        if has_numbers:
            strengths.append("Includes quantified achievements")
            score += 0.15
        else:
            weaknesses.append("Missing quantified achievements")
            suggestions.append("Add specific metrics and numbers to demonstrate impact (e.g., 'Increased revenue by 25%')")

        # Check for bullet points or structured format
        has_bullets = bool(re.search(r'[•\-\*]', content))
        if has_bullets:
            strengths.append("Well-structured with bullet points")
            score += 0.1
        else:
            suggestions.append("Use bullet points to improve readability")

        return score, strengths, weaknesses, suggestions

    def _analyze_skills_section(
        self, content: str
    ) -> tuple[float, List[str], List[str], List[str]]:
        """Analyze skills section."""
        score = 0.7
        strengths = []
        weaknesses = []
        suggestions = []

        # Count listed skills (simple heuristic: commas or newlines)
        skill_count = len(re.findall(r'[,\n]', content)) + 1

        if skill_count >= 8:
            strengths.append(f"Comprehensive skills list ({skill_count}+ skills)")
            score += 0.2
        elif skill_count >= 5:
            strengths.append(f"Good variety of skills listed ({skill_count} skills)")
            score += 0.1
        else:
            weaknesses.append("Limited skills listed")
            suggestions.append("Expand skills section to include more relevant technical and soft skills")
            score -= 0.1

        return score, strengths, weaknesses, suggestions

    def _analyze_education_section(
        self, content: str
    ) -> tuple[float, List[str], List[str], List[str]]:
        """Analyze education section (supports English and Spanish)."""
        score = 0.7
        strengths = []
        weaknesses = []
        suggestions = []

        # Check for degree information (English and Spanish)
        has_degree = bool(re.search(
            r'\b(bachelor|master|phd|doctorate|associate|b\.s\.|m\.s\.|b\.a\.|m\.a\.|'
            r'licenciatura|licenciado|ingenier[ií]a|ingeniero|maestr[ií]a|doctorado|'
            r'grado|t[eé]cnico|diplomado|mag[ií]ster)\b',
            content, re.IGNORECASE
        ))

        if has_degree:
            strengths.append("Includes degree information")
            score += 0.15
        else:
            suggestions.append("Clearly state your degree type (Bachelor's/Licenciatura, Master's/Maestría, etc.)")

        # Check for graduation date or year
        has_date = bool(re.search(r'\b(20\d{2}|19\d{2})\b', content))
        if has_date:
            strengths.append("Includes graduation date")
            score += 0.1

        return score, strengths, weaknesses, suggestions

    def _calculate_structure_score(self, sections: List[ResumeSection], text: str) -> float:
        """Calculate overall structure score."""
        score = 0.5

        # Check for essential sections
        section_names_lower = {s.section_name.lower() for s in sections}

        if any(exp in section_names_lower for exp in ["experience", "work", "employment"]):
            score += 0.2
        if "education" in section_names_lower:
            score += 0.15
        if "skills" in section_names_lower:
            score += 0.15

        return min(1.0, score)

    def _calculate_content_score(
        self, text: str, has_quantified: bool, word_count: int
    ) -> float:
        """Calculate content quality score."""
        score = 0.5

        # Optimal word count: 400-800 words
        if 400 <= word_count <= 800:
            score += 0.2
        elif 300 <= word_count <= 1000:
            score += 0.1
        elif word_count < 200:
            score -= 0.1

        # Quantified achievements
        if has_quantified:
            score += 0.15

        # Action verbs
        action_verb_count = sum(
            1 for verb in self.STRONG_ACTION_VERBS
            if re.search(rf'\b{verb}\b', text, re.IGNORECASE)
        )
        if action_verb_count >= 5:
            score += 0.15
        elif action_verb_count >= 3:
            score += 0.1

        return min(1.0, max(0.0, score))

    def _calculate_formatting_score(self, text: str, word_count: int) -> float:
        """Calculate formatting and readability score."""
        score = 0.6

        # Check for proper paragraphing (not one massive block)
        paragraph_count = len(re.findall(r'\n\s*\n', text))
        if paragraph_count >= 3:
            score += 0.15
        elif paragraph_count == 0 and word_count > 200:
            score -= 0.1

        # Check for bullet points
        bullet_count = len(re.findall(r'[•\-\*]', text))
        if bullet_count >= 5:
            score += 0.15
        elif bullet_count >= 3:
            score += 0.1

        # Check for excessive length
        if word_count > 1000:
            score -= 0.1

        return min(1.0, max(0.0, score))

    def _analyze_keywords(self, resume_text: str, job: Job) -> KeywordAnalysis:
        """Analyze keyword match between resume and job."""
        resume_lower = resume_text.lower()

        # Extract job requirements
        job_keywords: Set[str] = set()
        if job.tags:
            job_keywords.update(tag.lower() for tag in job.tags)

        # Extract keywords from job description
        if job.description:
            # Extract technical terms and skills (simplified approach)
            description_words = re.findall(r'\b[a-z]{3,}\b', job.description.lower())
            # Filter for likely technical terms (appears multiple times or in tags)
            for word in description_words:
                if word in [tag.lower() for tag in (job.tags or [])]:
                    job_keywords.add(word)

        # Find matched and missing keywords
        matched = [kw for kw in job_keywords if kw in resume_lower]
        missing = [kw for kw in job_keywords if kw not in resume_lower]

        # Calculate keyword density score
        if job_keywords:
            density_score = len(matched) / len(job_keywords)
        else:
            density_score = 0.5

        return KeywordAnalysis(
            matched_keywords=sorted(matched)[:20],  # Top 20
            missing_keywords=sorted(missing)[:10],   # Top 10 missing
            keyword_density_score=density_score
        )

    def _calculate_overall_score(
        self,
        structure_score: float,
        content_score: float,
        formatting_score: float,
        relevance_score: Optional[float]
    ) -> float:
        """Calculate overall resume score (0-100)."""
        # Weighted average
        weights = {
            "structure": 0.25,
            "content": 0.35,
            "formatting": 0.20,
            "relevance": 0.20
        }

        score = (
            structure_score * weights["structure"] +
            content_score * weights["content"] +
            formatting_score * weights["formatting"]
        )

        if relevance_score is not None:
            score += relevance_score * weights["relevance"]
        else:
            # Redistribute relevance weight if no target job
            score += structure_score * weights["relevance"]

        return round(score * 100, 1)

    def _identify_strengths(
        self,
        text: str,
        has_contact: bool,
        has_quantified: bool,
        structure_score: float,
        content_score: float
    ) -> List[str]:
        """Identify overall resume strengths."""
        strengths = []

        if has_contact:
            strengths.append("Includes complete contact information")

        if has_quantified:
            strengths.append("Contains quantified achievements and metrics")

        if structure_score >= 0.8:
            strengths.append("Well-organized with clear section structure")

        if content_score >= 0.8:
            strengths.append("Strong content with impactful language")

        action_verb_count = sum(
            1 for verb in self.STRONG_ACTION_VERBS
            if re.search(rf'\b{verb}\b', text, re.IGNORECASE)
        )
        if action_verb_count >= 5:
            strengths.append(f"Uses {action_verb_count} strong action verbs throughout")

        return strengths

    def _identify_weaknesses(
        self,
        text: str,
        has_contact: bool,
        has_quantified: bool,
        structure_score: float,
        content_score: float,
        sections: List[ResumeSection],
        word_count: int
    ) -> List[str]:
        """Identify areas for improvement."""
        weaknesses = []

        if not has_contact:
            weaknesses.append("Missing contact information (email, phone)")

        if not has_quantified:
            weaknesses.append("Lacks quantified achievements and measurable results")

        if structure_score < 0.6:
            weaknesses.append("Resume structure could be improved with clearer sections")

        if content_score < 0.6:
            weaknesses.append("Content quality could be enhanced with stronger language and details")

        if word_count < 300:
            weaknesses.append("Resume appears too brief - consider adding more detail")
        elif word_count > 1000:
            weaknesses.append("Resume is lengthy - consider condensing to 1-2 pages")

        # Check for missing key sections
        section_names_lower = {s.section_name.lower() for s in sections}
        if not any(exp in section_names_lower for exp in ["experience", "work", "employment"]):
            weaknesses.append("Missing work experience section")
        if "skills" not in section_names_lower:
            weaknesses.append("Missing skills section")

        return weaknesses

    def _generate_top_suggestions(
        self,
        weaknesses: List[str],
        has_quantified: bool,
        sections: List[ResumeSection],
        target_job: Optional[Job],
        keyword_analysis: Optional[KeywordAnalysis]
    ) -> List[str]:
        """Generate prioritized improvement suggestions."""
        suggestions = []

        # Priority 1: Quantified achievements
        if not has_quantified:
            suggestions.append(
                "Add specific metrics and numbers to demonstrate your impact "
                "(e.g., 'Increased sales by 30%' instead of 'Increased sales')"
            )

        # Priority 2: Keywords for target job
        if target_job and keyword_analysis and keyword_analysis.missing_keywords:
            missing_kw = keyword_analysis.missing_keywords[:5]
            suggestions.append(
                f"Incorporate missing relevant keywords: {', '.join(missing_kw)}"
            )

        # Priority 3: Section improvements
        for section in sections:
            if section.suggestions:
                suggestions.extend(section.suggestions[:1])  # Top suggestion per section

        # Priority 4: Action verbs
        suggestions.append(
            "Use more strong action verbs at the start of bullet points "
            "(led, developed, achieved, implemented, optimized)"
        )

        # Priority 5: Formatting
        suggestions.append(
            "Ensure consistent formatting with clear visual hierarchy and bullet points"
        )

        # Limit to top 7 suggestions
        return suggestions[:7]

    def _generate_summary(
        self,
        overall_score: float,
        strengths: List[str],
        weaknesses: List[str],
        target_job: Optional[Job]
    ) -> str:
        """Generate executive summary of the review."""
        # Determine overall quality level
        if overall_score >= 80:
            quality = "excellent"
            tone = "Your resume is strong and well-positioned for success."
        elif overall_score >= 70:
            quality = "good"
            tone = "Your resume has a solid foundation with room for improvement."
        elif overall_score >= 60:
            quality = "moderate"
            tone = "Your resume needs several improvements to be competitive."
        else:
            quality = "needs significant improvement"
            tone = "Your resume requires substantial revisions to meet professional standards."

        job_context = ""
        if target_job:
            job_context = f" for the {target_job.title} position"

        summary_parts = [
            f"Overall, your resume is {quality} with a score of {overall_score}/100{job_context}. {tone}"
        ]

        if strengths:
            summary_parts.append(f" Key strengths: {strengths[0].lower()}")

        if weaknesses:
            summary_parts.append(f" Primary area for improvement: {weaknesses[0].lower()}")

        return "".join(summary_parts)


# Singleton instance
resume_review_service = ResumeReviewService()
