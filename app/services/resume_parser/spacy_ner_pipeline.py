"""
SpaCy NER pipeline for resume entity extraction.

Uses SpaCy's transformer-based models (en_core_web_trf, es_core_news_lg) with
custom EntityRuler patterns for resume-specific entities (EMAIL, PHONE, LINKEDIN,
GITHUB, JOB_TITLE, DEGREE). Handles section detection, contact extraction,
experience/education grouping, and summary extraction.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.resume_parser import (
    ParsedContact,
    ParsedEducation,
    ParsedExperience,
    ParsedSummary,
)

logger = logging.getLogger(__name__)

# Section header patterns (English and Spanish)
SECTION_PATTERNS = {
    "summary": re.compile(
        r"(?i)^(?:summary|profile|objective|about\s*me|professional\s*(?:summary|profile)|"
        r"career\s*objective|resumen|perfil|perfil\s*profesional|objetivo|sobre\s*m[ií]|"
        r"resumen\s*profesional|objetivo\s*profesional|extracto|descripci[oó]n)[\s:]*$"
    ),
    "experience": re.compile(
        r"(?i)^(?:experience|work\s*experience|employment|professional\s*experience|"
        r"work\s*history|career\s*history|experiencia|experiencia\s*laboral|"
        r"experiencia\s*profesional|historial\s*laboral|empleo|"
        r"trayectoria\s*profesional|trayectoria\s*laboral)[\s:]*$"
    ),
    "education": re.compile(
        r"(?i)^(?:education|academic|qualifications|academic\s*background|"
        r"educational\s*background|educaci[oó]n|formaci[oó]n|"
        r"formaci[oó]n\s*acad[eé]mica|estudios|preparaci[oó]n\s*acad[eé]mica|"
        r"t[ií]tulos)[\s:]*$"
    ),
    "skills": re.compile(
        r"(?i)^(?:skills|technical\s*skills|core\s*competencies|competencies|"
        r"technologies|expertise|proficiencies|habilidades|aptitudes|competencias|"
        r"conocimientos|habilidades\s*t[eé]cnicas|tecnolog[ií]as|destrezas|capacidades|"
        r"aptitudes\s*principales|herramientas|conocimientos\s*t[eé]cnicos|"
        r"herramientas\s*y\s*tecnolog[ií]as|stack\s*tecnol[oó]gico|tech\s*stack)[\s:]*$"
    ),
    "certifications": re.compile(
        r"(?i)^(?:certifications?|certificates?|licenses?|credentials|"
        r"certificaciones?|certificados?|licencias?|credenciales|acreditaciones?)[\s:]*$"
    ),
    "projects": re.compile(
        r"(?i)^(?:projects|personal\s*projects|key\s*projects|proyectos|"
        r"proyectos\s*personales|proyectos\s*principales|portafolio)[\s:]*$"
    ),
    "languages": re.compile(
        r"(?i)^(?:languages|language\s*skills|idiomas|lenguas|"
        r"competencias\s*ling[uü][ií]sticas)[\s:]*$"
    ),
}

# Custom entity patterns for EntityRuler
EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
PHONE_PATTERN = r"(?:\+\d{1,3}[-.\s]?)?(?:\(?\d{1,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}"
LINKEDIN_PATTERN = r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+"
GITHUB_PATTERN = r"(?:https?://)?(?:www\.)?github\.com/[\w-]+"
PORTFOLIO_PATTERN = r"(?:https?://)?(?:www\.)?[\w-]+\.(?:com|io|dev|me|co|net|org)/?"

# Date patterns
DATE_PATTERNS = [
    re.compile(
        r"(?i)(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\s*[,.]?\s*(\d{4})"
    ),
    re.compile(
        r"(?i)(ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|abr(?:il)?|may(?:o)?|jun(?:io)?|"
        r"jul(?:io)?|ago(?:sto)?|sep(?:t(?:iembre)?)?|oct(?:ubre)?|nov(?:iembre)?|"
        r"dic(?:iembre)?)\s*[,.]?\s*(\d{4})"
    ),
    re.compile(r"(\d{1,2})[/\-](\d{4})"),
    re.compile(r"(\d{4})\s*[-–]\s*(\d{4}|present|current|now|actual|actualidad|presente)", re.IGNORECASE),
]

# Common job title keywords for header detection
JOB_TITLE_KEYWORDS = [
    # English
    "engineer", "developer", "programmer", "architect", "manager", "director",
    "analyst", "designer", "consultant", "specialist", "coordinator", "lead",
    "senior", "junior", "principal", "staff", "intern", "associate", "vp",
    "head of", "chief", "officer", "administrator", "technician", "scientist",
    "researcher",
    # Spanish
    "ingeniero", "desarrollador", "programador", "arquitecto", "gerente",
    "director", "analista", "diseñador", "consultor", "especialista",
    "coordinador", "líder", "técnico", "científico", "investigador",
    "jefe", "supervisor", "administrador", "practicante", "asistente",
]

# Degree patterns — word boundaries (\b) prevent matching inside words.
# Group 1 captures the full degree name (including qualifiers like "Civil"),
# group 2 captures optional field of study after "in"/"en"/"of".
DEGREE_PATTERNS_RE = [
    re.compile(r"(?i)\b(ph\.?d\.?|doctorate?)\b(?:\s+(?:of|in)\s+(\w+(?:\s+\w+)*))?"),
    re.compile(r"(?i)\b(master'?s?|m\.s\.?|m\.a\.?|m\.b\.a\.?|m\.eng\.?)\b(?:\s+(?:of|in)\s+(\w+(?:\s+\w+)*))?"),
    re.compile(r"(?i)\b(bachelor'?s?|b\.s\.?|b\.a\.?|b\.eng\.?|b\.tech\.?)\b(?:\s+(?:of|in)\s+(\w+(?:\s+\w+)*))?"),
    re.compile(r"(?i)\b(associate'?s?|a\.s\.?|a\.a\.?)\b(?:\s+(?:of|in)\s+(\w+(?:\s+\w+)*))?"),
    re.compile(r"(?i)\b(doctorado|doctor)\b(?:\s+en\s+(\w+(?:\s+\w+)*))?"),
    re.compile(r"(?i)\b(maestr[ií]a|mag[ií]ster|m\.s\.c\.?)\b(?:\s+en\s+(\w+(?:\s+\w+)*))?"),
    # Spanish degrees: capture degree + qualifier (e.g. "Ingenieria Civil Informatica")
    # Stops at separator (- | ,) or end of line
    re.compile(r"(?i)\b((?:ingenier[ií]a|licenciatura|grado)(?:\s+\w+)*?)(?:\s*[-–—|,]\s|\s*$)"),
    re.compile(r"(?i)\b(t[eé]cnico|tecnicatura|diplomado)\b(?:\s+en\s+(\w+(?:\s+\w+)*))?"),
]

# GPA pattern
GPA_PATTERN = re.compile(r"(?i)(?:gpa|promedio|nota)[:\s]*(\d+\.?\d*)\s*(?:/\s*(\d+\.?\d*))?")

# Institution keywords
INSTITUTION_KEYWORDS = [
    "university", "college", "institute", "school", "academy",
    "universidad", "colegio", "instituto", "escuela", "academia",
    "facultad", "politécnico", "politecnico", "tecnológico", "tecnologico",
]


class SpacyNerPipeline:
    """SpaCy-based NER pipeline for resume parsing."""

    def __init__(self):
        self._nlp = None
        self._language: Optional[str] = None
        self._loaded_model: Optional[str] = None

    def detect_language(self, text: str) -> str:
        """Detect the language of the resume text."""
        try:
            from langdetect import detect
            sample = text[:500] if len(text) > 500 else text
            lang = detect(sample)
            if lang.startswith("es"):
                return "es"
            return "en"
        except Exception:
            return "en"

    def _load_model(self, language: str):
        """Load the appropriate SpaCy model for the detected language."""
        if self._nlp is not None and self._language == language:
            return

        import spacy

        if language == "es":
            primary = settings.spacy_model_es
            fallback = "es_core_news_sm"
        else:
            primary = settings.spacy_model_en
            fallback = "en_core_web_sm"

        model_name = primary
        try:
            self._nlp = spacy.load(primary)
            logger.info(f"Loaded SpaCy model: {primary}")
        except OSError:
            logger.warning(f"SpaCy model {primary} not found, trying {fallback}")
            try:
                self._nlp = spacy.load(fallback)
                model_name = fallback
                logger.info(f"Loaded fallback SpaCy model: {fallback}")
            except OSError:
                logger.error(f"No SpaCy model available for language {language}")
                raise RuntimeError(
                    f"No SpaCy model available. Install with: "
                    f"python -m spacy download {fallback}"
                )

        self._language = language
        self._loaded_model = model_name

        # Add custom EntityRuler for resume-specific patterns
        self._add_entity_ruler()

    def _add_entity_ruler(self):
        """Add custom entity patterns to the SpaCy pipeline."""
        if self._nlp is None:
            return

        from spacy.language import Language

        # Remove existing ruler if present (for reloads)
        if "resume_ruler" in self._nlp.pipe_names:
            self._nlp.remove_pipe("resume_ruler")

        ruler = self._nlp.add_pipe("entity_ruler", name="resume_ruler", before="ner")

        patterns = [
            {"label": "EMAIL", "pattern": [{"TEXT": {"REGEX": EMAIL_PATTERN}}]},
            {"label": "PHONE", "pattern": [{"TEXT": {"REGEX": PHONE_PATTERN}}]},
            {"label": "LINKEDIN", "pattern": [{"TEXT": {"REGEX": LINKEDIN_PATTERN}}]},
            {"label": "GITHUB", "pattern": [{"TEXT": {"REGEX": GITHUB_PATTERN}}]},
        ]

        ruler.add_patterns(patterns)

    def process(self, text: str, language: str = "en"):
        """
        Process text with the SpaCy pipeline.

        Args:
            text: Cleaned resume text
            language: Language code

        Returns:
            SpaCy Doc object
        """
        self._load_model(language)
        # Limit text length for performance (SpaCy trf models)
        max_len = 100000
        if len(text) > max_len:
            text = text[:max_len]
        return self._nlp(text)

    def detect_sections(self, text: str) -> Dict[str, str]:
        """
        Detect resume sections using pattern matching.

        Args:
            text: Cleaned resume text

        Returns:
            Dict mapping section names to their text content
        """
        lines = text.split("\n")
        sections = {}
        current_section = "header"
        current_content: List[str] = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                current_content.append("")
                continue

            # Check if line is a section header
            section_found = None
            for section_name, pattern in SECTION_PATTERNS.items():
                if pattern.match(line_stripped):
                    section_found = section_name
                    break

            # Also detect section headers by formatting heuristics
            if not section_found and self._looks_like_section_header(line_stripped):
                section_found = self._classify_header(line_stripped)

            if section_found:
                if current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                logger.debug(f"Section detected: '{section_found}' from line: '{line_stripped}'")
                current_section = section_found
                current_content = []
            else:
                current_content.append(line)

        if current_content:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _looks_like_section_header(self, line: str) -> bool:
        """Check if a line looks like a section header by formatting."""
        # All caps, short line
        if line.isupper() and len(line.split()) <= 4 and len(line) < 40:
            return True
        # Ends with colon, short
        if line.endswith(":") and len(line.split()) <= 4:
            return True
        return False

    def _classify_header(self, line: str) -> Optional[str]:
        """Try to classify an unrecognized header into a known section."""
        line_lower = line.lower().rstrip(":")
        for section_name, pattern in SECTION_PATTERNS.items():
            if pattern.match(line_lower):
                return section_name
        return None

    def extract_contact(self, doc, text: str, header_lines: Optional[List[str]] = None) -> ParsedContact:
        """
        Extract contact information using SpaCy entities + regex.

        Args:
            doc: SpaCy Doc object
            text: Full resume text
            header_lines: First ~20 lines of the resume

        Returns:
            ParsedContact with extracted info
        """
        if header_lines is None:
            header_lines = text.split("\n")[:20]

        header_text = "\n".join(header_lines)

        # Email
        email = None
        email_match = re.search(EMAIL_PATTERN, text)
        if email_match:
            email = email_match.group(0)

        # Phone
        phone = None
        phone_match = re.search(PHONE_PATTERN, text)
        if phone_match:
            phone = phone_match.group(0)

        # LinkedIn
        linkedin = None
        linkedin_match = re.search(LINKEDIN_PATTERN, text)
        if linkedin_match:
            linkedin = linkedin_match.group(0)

        # GitHub
        github = None
        github_match = re.search(GITHUB_PATTERN, text)
        if github_match:
            github = github_match.group(0)

        # Portfolio — only match URLs with protocol or www prefix
        portfolio = None
        portfolio_url_pattern = r"(?:https?://|www\.)[\w.-]+\.(?:com|io|dev|me|co|net|org)(?:/[\w.-]*)?"
        portfolio_match = re.search(portfolio_url_pattern, text)
        if portfolio_match:
            candidate = portfolio_match.group(0)
            # Don't count linkedin/github as portfolio
            if "linkedin" not in candidate.lower() and "github" not in candidate.lower():
                portfolio = candidate

        # Name: prefer PERSON entity from SpaCy in header area
        full_name = None
        header_doc = doc[:min(len(doc), 100)]  # First ~100 tokens
        for ent in header_doc.ents:
            if ent.label_ == "PERSON":
                full_name = ent.text.strip()
                break

        # Fallback: first non-contact line in header
        if not full_name:
            for line in header_lines[:5]:
                line = line.strip()
                if not line:
                    continue
                if re.search(EMAIL_PATTERN, line) or re.search(PHONE_PATTERN, line):
                    continue
                if re.match(r"^[\d\s\-\(\)\+]+$", line):
                    continue
                if len(line.split()) <= 4 and len(line) > 1:
                    full_name = line
                    break

        # Location: GPE/LOC entity in header, or city-state pattern
        location = None
        for ent in header_doc.ents:
            if ent.label_ in ("GPE", "LOC"):
                location = ent.text.strip()
                break

        if not location:
            loc_match = re.search(r"([A-Z][a-zA-Z\s]+,\s*[A-Z]{2}(?:\s+\d{5})?)", header_text)
            if loc_match:
                location = loc_match.group(1).strip()

        return ParsedContact(
            email=email,
            phone=phone,
            full_name=full_name,
            location=location,
            linkedin=linkedin,
            github=github,
            portfolio=portfolio,
        )

    def extract_summary(
        self, doc, text: str, sections: Dict[str, str]
    ) -> ParsedSummary:
        """
        Extract professional summary and headline.

        Args:
            doc: SpaCy Doc object
            text: Full resume text
            sections: Detected sections dict

        Returns:
            ParsedSummary with summary text and headline
        """
        summary_text = sections.get("summary", "").strip() or None

        headline = None
        if summary_text:
            first_line = summary_text.split("\n")[0].strip()
            if len(first_line) < 100:
                headline = first_line

        # Try to find headline in header section
        if not headline:
            header_text = sections.get("header", "")
            header_lines = header_text.split("\n") if header_text else text.split("\n")[:10]

            for line in header_lines[1:6]:  # Skip name (first line)
                line = line.strip()
                if not line or len(line) < 10 or len(line) > 80:
                    continue
                if re.search(EMAIL_PATTERN, line) or re.search(PHONE_PATTERN, line):
                    continue
                if re.match(r"^[\d\s\-\(\)\+]+$", line):
                    continue
                line_lower = line.lower()
                if any(kw in line_lower for kw in JOB_TITLE_KEYWORDS):
                    headline = line
                    break

        return ParsedSummary(
            summary=summary_text,
            headline=headline,
        )

    def extract_experience(
        self, doc, sections: Dict[str, str]
    ) -> List[ParsedExperience]:
        """
        Extract work experience entries using SpaCy entities + heuristics.

        Args:
            doc: SpaCy Doc object
            sections: Detected sections dict

        Returns:
            List of ParsedExperience entries
        """
        section_text = sections.get("experience", "")
        if not section_text:
            return []

        experiences = []
        lines = section_text.split("\n")

        current_exp = None
        current_description: List[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for date patterns and job title keywords separately
            has_date = any(p.search(line) for p in DATE_PATTERNS)
            has_title_keyword = self._looks_like_job_header(line)

            # A line with ONLY dates (no title keyword) is metadata for
            # the current entry, not a new entry
            is_date_only_line = has_date and not has_title_keyword
            is_new_entry = has_title_keyword or (has_date and current_exp is None)

            if is_date_only_line and current_exp:
                # Attach dates to the current entry that's missing them
                start_date, end_date, is_current = self._parse_dates(line)
                if not current_exp.get("start_date"):
                    current_exp["start_date"] = start_date
                if not current_exp.get("end_date") and end_date:
                    current_exp["end_date"] = end_date
                if is_current:
                    current_exp["is_current"] = True
                    current_exp["end_date"] = None
                continue

            if is_new_entry and current_exp:
                if current_description:
                    current_exp["description"] = " ".join(current_description).strip()
                experiences.append(ParsedExperience(**current_exp))
                current_exp = None
                current_description = []

            if is_new_entry:
                title, company = self._parse_job_header(line)
                start_date, end_date, is_current = self._parse_dates(line)

                current_exp = {
                    "title": title or "Unknown Position",
                    "company": company or "Unknown Company",
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_current": is_current,
                    "location": None,
                    "description": None,
                }
            elif current_exp:
                # Description bullet or continuation
                clean_line = line.lstrip("-•* ").strip()
                if clean_line:
                    current_description.append(clean_line)

        # Save last experience
        if current_exp:
            if current_description:
                current_exp["description"] = " ".join(current_description).strip()
            experiences.append(ParsedExperience(**current_exp))

        return experiences

    def extract_education(
        self, doc, sections: Dict[str, str]
    ) -> List[ParsedEducation]:
        """
        Extract education entries using SpaCy entities + regex.

        Args:
            doc: SpaCy Doc object
            sections: Detected sections dict

        Returns:
            List of ParsedEducation entries
        """
        section_text = sections.get("education", "")
        if not section_text:
            return []

        education = []
        lines = section_text.split("\n")

        current_edu = None
        current_description: List[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for degree patterns
            degree_match = None
            for pattern in DEGREE_PATTERNS_RE:
                match = pattern.search(line)
                if match:
                    degree_match = match
                    break

            # Check for institution keywords
            is_institution = any(kw in line.lower() for kw in INSTITUTION_KEYWORDS)

            # A line with only dates (like "2019 - 2023") is metadata for current entry
            has_date = any(p.search(line) for p in DATE_PATTERNS)
            is_date_only = has_date and not degree_match and not is_institution
            if is_date_only and current_edu:
                start_date, end_date, _ = self._parse_dates(line)
                if not current_edu.get("start_date"):
                    current_edu["start_date"] = start_date
                if not current_edu.get("end_date") and end_date:
                    current_edu["end_date"] = end_date
                continue

            if degree_match or is_institution:
                if current_edu:
                    if current_description:
                        current_edu["description"] = " ".join(current_description).strip()
                    education.append(ParsedEducation(**current_edu))
                    current_description = []

                # Parse degree and field_of_study from regex match
                degree = None
                field_of_study = None
                if degree_match:
                    degree = degree_match.group(1).strip()
                    if degree_match.lastindex and degree_match.lastindex >= 2:
                        field_candidate = degree_match.group(2)
                        if field_candidate and len(field_candidate.strip()) > 2:
                            field_of_study = field_candidate.strip()
                    # Build the full degree string: "Ingenieria en Informatica"
                    if field_of_study:
                        # Detect connector ("in" or "en")
                        full_match = degree_match.group(0).strip()
                        degree = full_match

                # Parse institution: try splitting by separator
                institution = None
                if is_institution:
                    # If line has both degree and institution, split them
                    if degree:
                        # Try common separators: " - ", " | ", " , "
                        for sep in [" - ", " | ", ", "]:
                            if sep in line:
                                parts = line.split(sep)
                                for part in parts:
                                    part = part.strip()
                                    if any(kw in part.lower() for kw in INSTITUTION_KEYWORDS):
                                        institution = part
                                        break
                                break
                        if not institution:
                            institution = line.replace(degree, "").strip(" -,|")
                    else:
                        institution = line

                start_date, end_date, _ = self._parse_dates(line)

                gpa = None
                gpa_match_result = GPA_PATTERN.search(line)
                if gpa_match_result:
                    gpa = gpa_match_result.group(1)
                    if gpa_match_result.group(2):
                        gpa = f"{gpa}/{gpa_match_result.group(2)}"

                current_edu = {
                    "degree": degree or "Degree",
                    "institution": institution or "Institution",
                    "field_of_study": field_of_study,
                    "start_date": start_date,
                    "end_date": end_date,
                    "gpa": gpa,
                    "description": None,
                }
            elif current_edu:
                # Check for GPA in subsequent lines
                if not current_edu.get("gpa"):
                    gpa_match_result = GPA_PATTERN.search(line)
                    if gpa_match_result:
                        current_edu["gpa"] = gpa_match_result.group(1)
                        if gpa_match_result.group(2):
                            current_edu["gpa"] = f"{gpa_match_result.group(1)}/{gpa_match_result.group(2)}"
                        continue
                current_description.append(line)

        if current_edu:
            if current_description:
                current_edu["description"] = " ".join(current_description).strip()
            education.append(ParsedEducation(**current_edu))

        return education

    def get_noun_chunks(self, doc) -> List[str]:
        """Extract noun chunks from a SpaCy doc for skill matching."""
        chunks = []
        try:
            for chunk in doc.noun_chunks:
                text = chunk.text.strip()
                # Filter out very short or very long chunks
                if 2 < len(text) < 60:
                    chunks.append(text)
        except Exception:
            pass
        return chunks

    def get_skill_section_items(self, sections: Dict[str, str]) -> List[str]:
        """Extract individual items from skills section."""
        skills_text = sections.get("skills", "")
        if not skills_text:
            return []

        items = []
        for line in skills_text.split("\n"):
            line = line.strip().lstrip("-•* ").strip()
            if not line:
                continue

            # Strip category prefixes like "Lenguajes: Python, ..." or "Frameworks: React, ..."
            # Only strip if what follows the colon looks like skill items (not a full sentence)
            if ":" in line:
                before_colon, after_colon = line.split(":", 1)
                # If the prefix is short (a category label) and remainder has content, strip it
                if len(before_colon.split()) <= 3 and after_colon.strip():
                    line = after_colon.strip()

            # Split by common delimiters
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
            elif "|" in line:
                parts = [p.strip() for p in line.split("|")]
            elif "/" in line and len(line) < 40:
                parts = [p.strip() for p in line.split("/")]
            else:
                parts = [line]

            for part in parts:
                # Strip trailing periods
                part = part.rstrip(".")
                if part and len(part) > 1 and len(part) < 60:
                    items.append(part)

        return items

    # --- Helper methods ---

    def _looks_like_job_header(self, line: str) -> bool:
        """Check if a line looks like a job title/company header."""
        # Skip bullet points / description lines
        if line.startswith("-") or line.startswith("•") or line.startswith("*"):
            return False

        line_lower = line.lower()

        # Check for title keyword at word boundary (not inside longer words)
        has_title_keyword = False
        for kw in JOB_TITLE_KEYWORDS:
            pattern = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            if pattern.search(line_lower):
                has_title_keyword = True
                break

        has_separator = bool(re.search(r"\s+[-|–—@·]\s+", line))
        has_at = bool(re.search(r"(?i)\s+(?:at|en)\s+[A-Z]", line))

        return has_title_keyword or (has_separator and has_at)

    def _parse_job_header(self, line: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse job title and company from a header line."""
        # Remove date portions
        clean = line
        for pattern in DATE_PATTERNS:
            clean = pattern.sub("", clean)

        clean = clean.strip(" -–—|,")

        # Common separators
        for sep in [" at ", " @ ", " | ", " · ", " – ", " — ", " - ", ", "]:
            if sep in clean:
                parts = clean.split(sep, 1)
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()

        # Spanish "en"
        en_match = re.search(r"(?i)(.+?)\s+en\s+([A-Z].+)", clean)
        if en_match:
            return en_match.group(1).strip(), en_match.group(2).strip()

        return clean.strip() or None, None

    def _parse_dates(self, line: str) -> Tuple[Optional[str], Optional[str], bool]:
        """Parse start/end dates from a line."""
        line_lower = line.lower()
        is_current = any(word in line_lower for word in [
            "present", "current", "now",
            "actual", "actualidad", "presente", "vigente",
        ])

        start_date = None
        end_date = None

        # First try the year-range pattern: "2019 - 2023" or "2019 - present"
        range_pattern = DATE_PATTERNS[-1]  # (\d{4})\s*[-–]\s*(\d{4}|present|...)
        range_match = range_pattern.search(line)
        if range_match:
            start_date = range_match.group(1).strip()
            end_val = range_match.group(2).strip().lower()
            if end_val not in ("present", "current", "now", "actual", "actualidad", "presente"):
                end_date = end_val
            else:
                is_current = True
                end_date = None
            return start_date, end_date, is_current

        # Try month-year patterns
        dates = []
        for pattern in DATE_PATTERNS[:-1]:  # Skip the range pattern
            matches = pattern.findall(line)
            for match in matches:
                if isinstance(match, tuple):
                    dates.append(" ".join(str(d) for d in match if d).strip())
                else:
                    dates.append(str(match).strip())

        if dates:
            start_date = dates[0]
            if len(dates) > 1:
                end_date = dates[1]

        if is_current:
            end_date = None

        return start_date, end_date, is_current
