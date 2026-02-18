"""
Resume Parser Coordinator — orchestrates the full AI-powered parsing pipeline.

Pipeline:
1. TextCleaner: normalize raw text
2. SpacyNerPipeline: detect language, sections, extract entities
3. EscoSkillMatcher: semantic skill matching against ESCO taxonomy
4. LanguageProficiencyDetector: CEFR-level language detection
5. Assemble final ResumeParseResponse

Public API: parse_resume(resume_text, document_id) -> ResumeParseResponse
"""

import logging
from typing import List, Optional

from app.schemas.resume_parser import (
    ParsedContact,
    ParsedEducation,
    ParsedExperience,
    ParsedSkills,
    ParsedSummary,
    ResumeParseResponse,
)

logger = logging.getLogger(__name__)


class ResumeParserCoordinator:
    """Orchestrates the AI-powered resume parsing pipeline."""

    # Exposed for backward compatibility (used by resume_review_service)
    SECTION_PATTERNS = {
        "summary": r"(?i)^(?:summary|profile|objective|about\s*me|professional\s*(?:summary|profile)|career\s*objective|resumen|perfil|perfil\s*profesional|objetivo|sobre\s*m[ií]|resumen\s*profesional|objetivo\s*profesional|extracto|descripci[oó]n)[\s:]*$",
        "experience": r"(?i)^(?:experience|work\s*experience|employment|professional\s*experience|work\s*history|career\s*history|experiencia|experiencia\s*laboral|experiencia\s*profesional|historial\s*laboral|empleo|trayectoria\s*profesional|trayectoria\s*laboral)[\s:]*$",
        "education": r"(?i)^(?:education|academic|qualifications|academic\s*background|educational\s*background|educaci[oó]n|formaci[oó]n|formaci[oó]n\s*acad[eé]mica|estudios|preparaci[oó]n\s*acad[eé]mica|t[ií]tulos)[\s:]*$",
        "skills": r"(?i)^(?:skills|technical\s*skills|core\s*competencies|competencies|technologies|expertise|proficiencies|habilidades|aptitudes|competencias|conocimientos|habilidades\s*t[eé]cnicas|tecnolog[ií]as|destrezas|capacidades)[\s:]*$",
        "certifications": r"(?i)^(?:certifications?|certificates?|licenses?|credentials|certificaciones?|certificados?|licencias?|credenciales|acreditaciones?)[\s:]*$",
        "projects": r"(?i)^(?:projects|personal\s*projects|key\s*projects|proyectos|proyectos\s*personales|proyectos\s*principales|portafolio)[\s:]*$",
        "languages": r"(?i)^(?:languages|language\s*skills|idiomas|lenguas|competencias\s*ling[uü][ií]sticas)[\s:]*$",
    }

    def __init__(self):
        self._text_cleaner = None
        self._ner_pipeline = None
        self._skill_matcher = None
        self._lang_detector = None

    def _ensure_initialized(self):
        """Lazy-initialize all sub-components on first use."""
        if self._text_cleaner is not None:
            return

        from app.services.resume_parser.text_cleaner import TextCleaner
        from app.services.resume_parser.spacy_ner_pipeline import SpacyNerPipeline
        from app.services.resume_parser.esco_skill_matcher import EscoSkillMatcher
        from app.services.resume_parser.language_proficiency import LanguageProficiencyDetector

        self._text_cleaner = TextCleaner()
        self._ner_pipeline = SpacyNerPipeline()
        self._skill_matcher = EscoSkillMatcher()
        self._lang_detector = LanguageProficiencyDetector()

    def parse_resume(
        self,
        resume_text: str,
        document_id: Optional[str] = None,
    ) -> ResumeParseResponse:
        """
        Parse resume text and extract structured information.

        Args:
            resume_text: The raw text content of the resume
            document_id: Optional document ID for logging

        Returns:
            ResumeParseResponse with all extracted data
        """
        if not resume_text or not resume_text.strip():
            logger.warning(f"Empty resume text provided for document {document_id}")
            return ResumeParseResponse(
                confidence_score=0.0,
                parsing_method="spacy_esco",
                sections_found=[],
            )

        self._ensure_initialized()

        try:
            return self._run_pipeline(resume_text, document_id)
        except Exception as e:
            logger.error(f"Resume parsing pipeline failed for {document_id}: {e}", exc_info=True)
            # Return a minimal response rather than crashing
            return ResumeParseResponse(
                raw_text=resume_text[:5000],
                confidence_score=0.0,
                parsing_method="spacy_esco",
                sections_found=[],
            )

    def _run_pipeline(
        self,
        resume_text: str,
        document_id: Optional[str],
    ) -> ResumeParseResponse:
        """Execute the full parsing pipeline."""

        # 1. Clean text
        cleaned_text = self._text_cleaner.clean(resume_text)

        # 2. Detect language
        language = self._ner_pipeline.detect_language(cleaned_text)

        # 3. Process with SpaCy
        doc = self._ner_pipeline.process(cleaned_text, language)

        # 4. Detect sections
        sections = self._ner_pipeline.detect_sections(cleaned_text)
        sections_found = list(sections.keys())

        # 5. Extract contact info
        header_lines = cleaned_text.split("\n")[:20]
        contact = self._ner_pipeline.extract_contact(doc, cleaned_text, header_lines)

        # 6. Extract summary
        summary = self._ner_pipeline.extract_summary(doc, cleaned_text, sections)

        # 7. Extract experience
        experience = self._ner_pipeline.extract_experience(doc, sections)

        # 8. Extract education
        education = self._ner_pipeline.extract_education(doc, sections)

        # 9. Match skills using ESCO
        noun_chunks = self._ner_pipeline.get_noun_chunks(doc)
        skill_items = self._ner_pipeline.get_skill_section_items(sections)
        skills = self._skill_matcher.match_skills(
            cleaned_text,
            noun_chunks=noun_chunks,
            skill_section_items=skill_items,
            language=language,
            experiences=experience,
            education=education,
        )

        # 10. Detect language proficiencies
        proficiencies, languages_list = self._lang_detector.detect(
            cleaned_text, sections, language
        )

        # 11. Merge language data into skills
        skills = ParsedSkills(
            technical_skills=skills.technical_skills,
            soft_skills=skills.soft_skills,
            languages=languages_list,
            language_proficiencies=proficiencies,
            certifications=skills.certifications,
            all_skills=skills.all_skills,
        )

        # 12. Calculate confidence score
        confidence = self._calculate_confidence(
            contact, summary, experience, education, skills
        )

        logger.info(
            f"Parsed resume {document_id}: "
            f"lang={language}, sections={sections_found}, "
            f"experience={len(experience)}, education={len(education)}, "
            f"skills={len(skills.all_skills)}, languages={len(languages_list)}, "
            f"confidence={confidence:.2f}"
        )

        return ResumeParseResponse(
            contact=contact,
            summary=summary,
            experience=experience,
            education=education,
            skills=skills,
            raw_text=resume_text[:5000] if len(resume_text) > 5000 else resume_text,
            confidence_score=confidence,
            parsing_method="spacy_esco",
            sections_found=sections_found,
        )

    def _calculate_confidence(
        self,
        contact: ParsedContact,
        summary: ParsedSummary,
        experience: List[ParsedExperience],
        education: List[ParsedEducation],
        skills: ParsedSkills,
    ) -> float:
        """
        Calculate confidence score for the parsing result.

        Weights: contact 15%, experience 30%, education 20%, skills 25%, summary 10%
        """
        score = 0.0

        # Contact (15%)
        contact_score = 0.0
        if contact.full_name:
            contact_score += 0.4
        if contact.email:
            contact_score += 0.3
        if contact.phone:
            contact_score += 0.15
        if contact.linkedin or contact.github:
            contact_score += 0.15
        score += contact_score * 0.15

        # Experience (30%)
        exp_score = 0.0
        if experience:
            exp_score = min(len(experience) / 3.0, 1.0)
            # Bonus for well-structured entries
            well_structured = sum(
                1 for e in experience
                if e.title != "Unknown Position" and e.company != "Unknown Company"
            )
            if experience:
                exp_score *= 0.5 + 0.5 * (well_structured / len(experience))
        score += exp_score * 0.30

        # Education (20%)
        edu_score = 0.0
        if education:
            edu_score = min(len(education) / 2.0, 1.0)
            well_structured = sum(
                1 for e in education
                if e.degree != "Degree" and e.institution != "Institution"
            )
            if education:
                edu_score *= 0.5 + 0.5 * (well_structured / len(education))
        score += edu_score * 0.20

        # Skills (25%)
        skill_score = 0.0
        if skills.all_skills:
            skill_score = min(len(skills.all_skills) / 10.0, 1.0)
        score += skill_score * 0.25

        # Summary (10%)
        summary_score = 0.0
        if summary.summary:
            summary_score += 0.6
        if summary.headline:
            summary_score += 0.4
        score += summary_score * 0.10

        return min(score, 1.0)
