"""
Language proficiency detection with CEFR level mapping.

Detects language names and proficiency levels from resume text,
supporting both English and Spanish resume formats.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

from app.schemas.resume_parser import ParsedLanguageProficiency

logger = logging.getLogger(__name__)

# CEFR level mapping: proficiency descriptor → (level_name, cefr_code)
PROFICIENCY_MAP: Dict[str, Tuple[str, str]] = {
    # English descriptors
    "native": ("Native", "C2"),
    "native speaker": ("Native", "C2"),
    "mother tongue": ("Native", "C2"),
    "first language": ("Native", "C2"),
    "bilingual": ("Native", "C2"),
    "fluent": ("Fluent", "C1"),
    "proficient": ("Fluent", "C1"),
    "full professional": ("Fluent", "C1"),
    "professional": ("Fluent", "C1"),
    "advanced": ("Advanced", "B2"),
    "upper intermediate": ("Advanced", "B2"),
    "intermediate": ("Intermediate", "B1"),
    "conversational": ("Intermediate", "B1"),
    "pre-intermediate": ("Basic", "A2"),
    "basic": ("Basic", "A2"),
    "elementary": ("Basic", "A2"),
    "beginner": ("Beginner", "A1"),
    "novice": ("Beginner", "A1"),
    # Spanish descriptors
    "nativo": ("Native", "C2"),
    "nativa": ("Native", "C2"),
    "lengua materna": ("Native", "C2"),
    "bilingüe": ("Native", "C2"),
    "bilingue": ("Native", "C2"),
    "fluido": ("Fluent", "C1"),
    "fluida": ("Fluent", "C1"),
    "profesional": ("Fluent", "C1"),
    "avanzado": ("Advanced", "B2"),
    "avanzada": ("Advanced", "B2"),
    "intermedio": ("Intermediate", "B1"),
    "intermedia": ("Intermediate", "B1"),
    "básico": ("Basic", "A2"),
    "basico": ("Basic", "A2"),
    "básica": ("Basic", "A2"),
    "basica": ("Basic", "A2"),
    "elemental": ("Basic", "A2"),
    "principiante": ("Beginner", "A1"),
}

# Direct CEFR codes
CEFR_CODES = {"A1", "A2", "B1", "B2", "C1", "C2"}

# Known language names (English and Spanish variants)
LANGUAGE_NAMES: Dict[str, str] = {
    # English names
    "english": "English", "spanish": "Spanish", "french": "French",
    "german": "German", "italian": "Italian", "portuguese": "Portuguese",
    "chinese": "Chinese", "mandarin": "Mandarin", "cantonese": "Cantonese",
    "japanese": "Japanese", "korean": "Korean", "russian": "Russian",
    "arabic": "Arabic", "hindi": "Hindi", "bengali": "Bengali",
    "urdu": "Urdu", "dutch": "Dutch", "swedish": "Swedish",
    "polish": "Polish", "turkish": "Turkish", "vietnamese": "Vietnamese",
    "thai": "Thai", "indonesian": "Indonesian", "malay": "Malay",
    "tagalog": "Tagalog", "hebrew": "Hebrew", "greek": "Greek",
    "czech": "Czech", "danish": "Danish", "finnish": "Finnish",
    "norwegian": "Norwegian", "romanian": "Romanian", "hungarian": "Hungarian",
    "catalan": "Catalan", "basque": "Basque", "galician": "Galician",
    # Spanish names
    "inglés": "English", "ingles": "English",
    "español": "Spanish", "espanol": "Spanish", "castellano": "Spanish",
    "francés": "French", "frances": "French",
    "alemán": "German", "aleman": "German",
    "italiano": "Italian",
    "portugués": "Portuguese", "portugues": "Portuguese",
    "chino": "Chinese", "mandarín": "Mandarin", "mandarin": "Mandarin",
    "japonés": "Japanese", "japones": "Japanese",
    "coreano": "Korean",
    "ruso": "Russian",
    "árabe": "Arabic", "arabe": "Arabic",
    "hindú": "Hindi", "hindu": "Hindi",
    "holandés": "Dutch", "holandes": "Dutch",
    "sueco": "Swedish",
    "polaco": "Polish",
    "turco": "Turkish",
    "catalán": "Catalan", "catalan": "Catalan",
    "vasco": "Basque", "euskera": "Basque",
    "gallego": "Galician",
}

# Patterns for extracting language + proficiency pairs
# Format: "Language (Level)", "Language - Level", "Language: Level", "Language – Level"
LANG_PROFICIENCY_PATTERN = re.compile(
    r"(?P<language>[A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)?)"
    r"\s*"
    r"(?:"
    r"\((?P<level_paren>[^)]+)\)"         # English (Native)
    r"|[-–—]\s*(?P<level_dash>[^,\n]+)"   # Spanish - B2
    r"|:\s*(?P<level_colon>[^,\n]+)"      # French: Intermediate
    r")",
    re.IGNORECASE
)

# Pattern for standalone CEFR code near a language name
CEFR_PATTERN = re.compile(r"\b([A-C][12])\b")


class LanguageProficiencyDetector:
    """Detects language names and proficiency levels from resume text."""

    def detect(
        self,
        text: str,
        sections: Optional[Dict[str, str]] = None,
        resume_language: str = "en",
    ) -> Tuple[List[ParsedLanguageProficiency], List[str]]:
        """
        Detect languages and proficiency levels from resume text.

        Args:
            text: Full resume text
            sections: Dict of detected sections (keys like "languages")
            resume_language: Detected language of the resume ("en", "es")

        Returns:
            Tuple of (language_proficiencies, language_names_list)
            where language_names_list is backward-compatible List[str]
        """
        proficiencies: List[ParsedLanguageProficiency] = []
        seen_languages = set()

        # Prefer language section if available
        search_text = text
        if sections:
            lang_section = sections.get("languages", "")
            if lang_section:
                search_text = lang_section

        # Extract language + proficiency pairs
        for match in LANG_PROFICIENCY_PATTERN.finditer(search_text):
            lang_raw = match.group("language").strip()
            level_raw = (
                match.group("level_paren")
                or match.group("level_dash")
                or match.group("level_colon")
                or ""
            ).strip()

            lang_normalized = self._normalize_language(lang_raw)
            if not lang_normalized:
                continue

            if lang_normalized.lower() in seen_languages:
                continue
            seen_languages.add(lang_normalized.lower())

            level_name, cefr = self._parse_level(level_raw)
            proficiencies.append(ParsedLanguageProficiency(
                language=lang_normalized,
                level=level_name,
                cefr=cefr,
            ))

        # Scan for language names mentioned without explicit level
        for lang_key, lang_name in LANGUAGE_NAMES.items():
            if lang_name.lower() in seen_languages:
                continue
            # Word boundary match in text
            pattern = re.compile(r"\b" + re.escape(lang_key) + r"\b", re.IGNORECASE)
            if pattern.search(search_text):
                seen_languages.add(lang_name.lower())
                proficiencies.append(ParsedLanguageProficiency(
                    language=lang_name,
                    level="Unknown",
                    cefr=None,
                ))

        # Backward-compatible language list
        languages_list = [p.language for p in proficiencies]

        return proficiencies, languages_list

    def _normalize_language(self, raw: str) -> Optional[str]:
        """Normalize a language name to its canonical English form."""
        key = raw.lower().strip()
        return LANGUAGE_NAMES.get(key)

    def _parse_level(self, raw: str) -> Tuple[str, Optional[str]]:
        """
        Parse a proficiency level string into (level_name, cefr_code).

        Handles: "Native", "B2", "Fluent (C1)", "Avanzado", etc.
        """
        if not raw:
            return ("Unknown", None)

        raw_lower = raw.lower().strip()

        # Check for direct CEFR code
        cefr_match = CEFR_PATTERN.search(raw)
        if cefr_match:
            cefr = cefr_match.group(1).upper()
            # Also try to get the descriptive level
            remaining = CEFR_PATTERN.sub("", raw_lower).strip(" ()-–—:/")
            if remaining in PROFICIENCY_MAP:
                level_name, _ = PROFICIENCY_MAP[remaining]
                return (level_name, cefr)
            # Map CEFR code to level name
            cefr_to_level = {
                "C2": "Native", "C1": "Fluent", "B2": "Advanced",
                "B1": "Intermediate", "A2": "Basic", "A1": "Beginner",
            }
            return (cefr_to_level.get(cefr, "Unknown"), cefr)

        # Check proficiency descriptors
        if raw_lower in PROFICIENCY_MAP:
            return PROFICIENCY_MAP[raw_lower]

        # Partial match: check if any descriptor is contained in the raw string
        for descriptor, (level_name, cefr) in PROFICIENCY_MAP.items():
            if descriptor in raw_lower:
                return (level_name, cefr)

        return ("Unknown", None)
