"""
LLM-powered resume extractor using Qwen (via DashScope's OpenAI-compatible endpoint).

Falls back silently to None when:
- DASHSCOPE_API_KEY is not configured
- The API call fails for any reason
- The response cannot be parsed as valid JSON with the expected schema

This extractor is intentionally synchronous — the coordinator runs it inside
asyncio.to_thread alongside the other pipeline components.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# JSON schema — defined once, shared across all language prompts
_SCHEMA = (
    '{"contact":{"full_name":str|null,"email":str|null,"phone":str|null,'
    '"linkedin":str|null,"github":str|null,"location":str|null},'
    '"summary":str|null,"headline":str|null,'
    '"experience":[{"title":str,"company":str,"start_date":"YYYY-MM"|null,'
    '"end_date":"YYYY-MM"|null,"is_current":bool,"description":str|null}],'
    '"education":[{"degree":str,"institution":str,"field_of_study":str|null,'
    '"start_date":"YYYY-MM"|null,"end_date":"YYYY-MM"|null,"gpa":str|null}],'
    '"skills":[str]}'
)

# i18n strings for the system prompt — only the parts that differ per language.
# Field names in the schema are always English (parsed programmatically).
_I18N: Dict[str, Dict[str, str]] = {
    "en": {
        "intro": "You are a resume parser. Output ONLY valid JSON — no markdown, no prose.",
        "schema_label": "Schema:",
        "rules": (
            "Rules: extract values verbatim as they appear in the resume — do NOT translate. "
            "Dates as YYYY-MM or YYYY. is_current=true only for ongoing roles. "
            "skills are raw strings from the resume. null for unknown fields. "
            "Arrays present but may be empty."
        ),
    },
    "es": {
        "intro": "Eres un extractor de currículums. Responde SOLO con JSON válido — sin markdown, sin texto adicional.",
        "schema_label": "Esquema:",
        "rules": (
            "Reglas: extrae los valores tal como aparecen en el currículum — NO traduzcas nada. "
            "Fechas en formato YYYY-MM o YYYY. is_current=true solo para puestos vigentes. "
            "skills son cadenas exactas del currículum. null para campos desconocidos. "
            "Los arrays deben estar presentes aunque estén vacíos."
        ),
    },
    "pt": {
        "intro": "Você é um extrator de currículos. Responda APENAS com JSON válido — sem markdown, sem texto adicional.",
        "schema_label": "Esquema:",
        "rules": (
            "Regras: extraia os valores exatamente como aparecem no currículo — NÃO traduza nada. "
            "Datas no formato YYYY-MM ou YYYY. is_current=true apenas para cargos em andamento. "
            "skills são strings brutas do currículo. null para campos desconhecidos. "
            "Arrays devem estar presentes mesmo que vazios."
        ),
    },
}

_DEFAULT_LANGUAGE = "en"

# Optimization 1: 30-day TTL for LLM result cache
_LLM_CACHE_TTL = 2_592_000  # 30 days in seconds


def _get_system_prompt(language: str) -> str:
    """Compose the system prompt from i18n strings for the given language code."""
    lang = language.lower().split("-")[0].split("_")[0]  # normalise pt-BR → pt
    strings = _I18N.get(lang, _I18N[_DEFAULT_LANGUAGE])
    return f"{strings['intro']}\n\n{strings['schema_label']}\n{_SCHEMA}\n\n{strings['rules']}"

# Optimization 1: 30-day TTL for LLM result cache
_LLM_CACHE_TTL = 2_592_000  # 30 days in seconds


@dataclass
class LLMExtractedData:
    """Typed container for the structured data returned by Qwen."""

    contact: Dict[str, Optional[str]] = field(default_factory=dict)
    summary: Optional[str] = None
    headline: Optional[str] = None
    experience: List[Dict[str, Any]] = field(default_factory=list)
    education: List[Dict[str, Any]] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)


class LLMResumeExtractor:
    """
    Extracts structured resume data using Qwen (qwen-plus) via DashScope.

    Usage::

        extractor = LLMResumeExtractor()
        result = extractor.extract(cleaned_text)
        if result is not None:
            # merge result into pipeline output
    """

    def __init__(self) -> None:
        self._client = None       # lazy-initialized OpenAI client
        self._redis_client = None # lazy-initialized sync Redis client

    def _get_client(self):
        """Return a cached OpenAI client pointed at DashScope, or None if unconfigured."""
        if self._client is not None:
            return self._client

        from app.core.config import settings

        if not settings.dashscope_api_key:
            return None

        try:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.dashscope_api_key,
                base_url=DASHSCOPE_BASE_URL,
            )
            return self._client
        except Exception as exc:
            logger.warning("Failed to initialise DashScope client: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Optimization 1: sync Redis client for cache (lazy-initialized)
    # ------------------------------------------------------------------

    def _get_redis(self):
        """Return a lazy-initialized sync Redis client, or None on error."""
        if self._redis_client is not None:
            return self._redis_client
        try:
            import redis as sync_redis
            from app.core.config import settings

            self._redis_client = sync_redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            return self._redis_client
        except Exception as exc:
            logger.warning("Failed to initialise sync Redis client: %s", exc)
            return None

    def _cache_get(self, key: str) -> Optional[LLMExtractedData]:
        """Read a cached LLMExtractedData by key. Returns None on miss or error."""
        try:
            r = self._get_redis()
            if r is None:
                return None
            raw = r.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            return self._map_to_dataclass(data)
        except Exception as exc:
            logger.debug("LLM cache read error (ignored): %s", exc)
            return None

    def _cache_set(self, key: str, result: LLMExtractedData) -> None:
        """Write an LLMExtractedData to cache. Silently ignores errors."""
        try:
            r = self._get_redis()
            if r is None:
                return
            payload = json.dumps(
                {
                    "contact": result.contact,
                    "summary": result.summary,
                    "headline": result.headline,
                    "experience": result.experience,
                    "education": result.education,
                    "skills": result.skills,
                }
            )
            r.set(key, payload, ex=_LLM_CACHE_TTL)
        except Exception as exc:
            logger.debug("LLM cache write error (ignored): %s", exc)

    # ------------------------------------------------------------------
    # Optimization 4: smart input trimming
    # ------------------------------------------------------------------

    @staticmethod
    def _build_llm_input(text: str, sections: Optional[Dict[str, List[str]]]) -> str:
        """
        Build a focused excerpt of the resume for the LLM.

        When sections are available the result contains:
        - The first 30 lines of the text (header/contact block)
        - For each detected section: heading + first 15 content lines

        The combined result is capped at 3,500 chars.

        When no sections are provided, falls back to the first 3,500 chars.
        """
        CAP = 3_500

        if not sections:
            return text[:CAP]

        lines = text.split("\n")
        header_lines = lines[:30]
        parts: List[str] = ["\n".join(header_lines)]

        for heading, content_lines in sections.items():
            section_block = heading + "\n" + "\n".join(content_lines[:15])
            parts.append(section_block)

        combined = "\n\n".join(parts)
        return combined[:CAP]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        text: str,
        sections: Optional[Dict[str, List[str]]] = None,
        language: str = _DEFAULT_LANGUAGE,
    ) -> Optional[LLMExtractedData]:
        """
        Call Qwen and return structured extraction results.

        Returns None on any error so the caller can fall back gracefully.

        Args:
            text: Cleaned resume text (output of TextCleaner).
            sections: Optional dict from SpaCy section detector (heading -> lines).
            language: ISO-639-1 language code detected by SpaCy (e.g. "en", "es", "pt").
        """
        try:
            return self._extract_inner(text, sections, language)
        except Exception as exc:
            logger.warning("LLM resume extraction failed (returning None): %s", exc)
            return None

    def _extract_inner(
        self,
        text: str,
        sections: Optional[Dict[str, List[str]]],
        language: str,
    ) -> Optional[LLMExtractedData]:
        from app.core.config import settings
        client = self._get_client()
        if client is None:
            return None

        # Normalise language code and select the matching prompt
        lang = language.lower().split("-")[0].split("_")[0]
        system_prompt = _get_system_prompt(lang)

        # Optimization 1: cache key includes language so different prompts don't collide
        cache_key = f"resume_llm:{lang}:" + hashlib.sha256(text.encode()).hexdigest()[:64]
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("LLM resume cache hit for key %s…", cache_key[:24])
            return cached

        # Optimization 4: build a targeted, token-efficient input
        llm_input = self._build_llm_input(text, sections)

        response = client.chat.completions.create(
            model=settings.qwen_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": llm_input},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        raw = response.choices[0].message.content
        if not raw:
            logger.warning("LLM returned empty content")
            return None

        data = json.loads(raw)
        result = self._map_to_dataclass(data)

        # Optimization 1: store result in cache (fire-and-forget, errors ignored)
        self._cache_set(cache_key, result)

        return result

    @staticmethod
    def _map_to_dataclass(data: Dict[str, Any]) -> LLMExtractedData:
        """Map the raw JSON dict to a typed LLMExtractedData instance."""

        contact_raw = data.get("contact") or {}
        contact: Dict[str, Optional[str]] = {
            "full_name": contact_raw.get("full_name") or None,
            "email": contact_raw.get("email") or None,
            "phone": contact_raw.get("phone") or None,
            "linkedin": contact_raw.get("linkedin") or None,
            "github": contact_raw.get("github") or None,
            "location": contact_raw.get("location") or None,
        }

        experience: List[Dict[str, Any]] = []
        for exp in data.get("experience") or []:
            if not isinstance(exp, dict):
                continue
            experience.append(
                {
                    "title": str(exp.get("title") or "Unknown Position"),
                    "company": str(exp.get("company") or "Unknown Company"),
                    "start_date": exp.get("start_date") or None,
                    "end_date": exp.get("end_date") or None,
                    "is_current": bool(exp.get("is_current", False)),
                    "description": exp.get("description") or None,
                }
            )

        education: List[Dict[str, Any]] = []
        for edu in data.get("education") or []:
            if not isinstance(edu, dict):
                continue
            education.append(
                {
                    "degree": str(edu.get("degree") or "Degree"),
                    "institution": str(edu.get("institution") or "Institution"),
                    "field_of_study": edu.get("field_of_study") or None,
                    "start_date": edu.get("start_date") or None,
                    "end_date": edu.get("end_date") or None,
                    "gpa": edu.get("gpa") or None,
                }
            )

        raw_skills = data.get("skills") or []
        skills = [str(s) for s in raw_skills if isinstance(s, (str, int, float)) and str(s).strip()]

        return LLMExtractedData(
            contact=contact,
            summary=data.get("summary") or None,
            headline=data.get("headline") or None,
            experience=experience,
            education=education,
            skills=skills,
        )
