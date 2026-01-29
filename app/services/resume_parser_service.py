"""
Resume Parser Service - AI-powered extraction of structured data from resumes.

Uses a hybrid approach combining:
- Regex patterns for structured data (emails, phones, dates, URLs)
- NLP techniques for section detection and entity extraction
- Keyword matching for skills and technologies
- Heuristics for experience and education extraction
"""

import re
import logging
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

from app.schemas.resume_parser import (
    ResumeParseResponse,
    ParsedContact,
    ParsedSummary,
    ParsedExperience,
    ParsedEducation,
    ParsedSkills,
)

logger = logging.getLogger(__name__)


class ResumeParserService:
    """Service for parsing resume text and extracting structured information."""

    # Common section headers (English and Spanish)
    SECTION_PATTERNS = {
        "summary": r"(?i)^(?:summary|profile|objective|about\s*me|professional\s*summary|career\s*objective|resumen|perfil|objetivo|sobre\s*m[ií]|resumen\s*profesional|objetivo\s*profesional|extracto|descripci[oó]n)[\s:]*$",
        "experience": r"(?i)^(?:experience|work\s*experience|employment|professional\s*experience|work\s*history|career\s*history|experiencia|experiencia\s*laboral|experiencia\s*profesional|historial\s*laboral|empleo|trayectoria\s*profesional|trayectoria\s*laboral)[\s:]*$",
        "education": r"(?i)^(?:education|academic|qualifications|academic\s*background|educational\s*background|educaci[oó]n|formaci[oó]n|formaci[oó]n\s*acad[eé]mica|estudios|preparaci[oó]n\s*acad[eé]mica|t[ií]tulos)[\s:]*$",
        "skills": r"(?i)^(?:skills|technical\s*skills|core\s*competencies|competencies|technologies|expertise|proficiencies|habilidades|aptitudes|competencias|conocimientos|habilidades\s*t[eé]cnicas|tecnolog[ií]as|destrezas|capacidades)[\s:]*$",
        "certifications": r"(?i)^(?:certifications?|certificates?|licenses?|credentials|certificaciones?|certificados?|licencias?|credenciales|acreditaciones?)[\s:]*$",
        "projects": r"(?i)^(?:projects|personal\s*projects|key\s*projects|proyectos|proyectos\s*personales|proyectos\s*principales|portafolio)[\s:]*$",
        "languages": r"(?i)^(?:languages|language\s*skills|idiomas|lenguas|competencias\s*ling[uü][ií]sticas)[\s:]*$",
    }

    # Regex patterns for contact extraction
    EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    PHONE_PATTERN = r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}"
    LINKEDIN_PATTERN = r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+"
    GITHUB_PATTERN = r"(?:https?://)?(?:www\.)?github\.com/[\w-]+"
    PORTFOLIO_PATTERN = r"(?:https?://)?(?:www\.)?(?:portfolio|[\w-]+)\.(?:com|io|dev|me|co)/?"

    # Technical skills keywords
    TECHNICAL_SKILLS = {
        # Programming Languages
        "python", "javascript", "typescript", "java", "c++", "c#", "ruby", "go", "golang",
        "rust", "swift", "kotlin", "php", "scala", "perl", "r", "matlab", "dart", "lua",
        "objective-c", "groovy", "clojure", "elixir", "haskell", "erlang", "f#",
        # Frontend
        "react", "react.js", "reactjs", "vue", "vue.js", "vuejs", "angular", "angularjs",
        "svelte", "next.js", "nextjs", "nuxt", "gatsby", "html", "css", "sass", "scss",
        "less", "tailwind", "bootstrap", "material-ui", "chakra", "styled-components",
        "webpack", "vite", "parcel", "babel", "jquery", "redux", "mobx", "zustand",
        # Backend
        "node.js", "nodejs", "express", "fastapi", "django", "flask", "spring", "spring boot",
        "rails", "ruby on rails", "asp.net", ".net", "laravel", "symfony", "gin", "echo",
        "fiber", "nestjs", "koa", "hapi", "fastify", "graphql", "rest", "restful",
        # Mobile
        "react native", "flutter", "swift", "swiftui", "kotlin", "android", "ios",
        "xamarin", "ionic", "cordova", "expo",
        # Databases
        "sql", "mysql", "postgresql", "postgres", "mongodb", "redis", "elasticsearch",
        "dynamodb", "cassandra", "oracle", "sqlite", "mariadb", "neo4j", "couchdb",
        "firebase", "supabase", "prisma", "sequelize", "sqlalchemy", "typeorm",
        # Cloud & DevOps
        "aws", "amazon web services", "azure", "gcp", "google cloud", "docker", "kubernetes",
        "k8s", "terraform", "ansible", "jenkins", "gitlab ci", "github actions", "circleci",
        "travis ci", "nginx", "apache", "linux", "unix", "bash", "shell", "powershell",
        # Data & ML
        "machine learning", "deep learning", "tensorflow", "pytorch", "keras", "scikit-learn",
        "pandas", "numpy", "scipy", "matplotlib", "seaborn", "jupyter", "spark", "hadoop",
        "kafka", "airflow", "mlflow", "huggingface", "nlp", "computer vision", "opencv",
        # Tools
        "git", "github", "gitlab", "bitbucket", "jira", "confluence", "slack", "figma",
        "sketch", "adobe xd", "postman", "swagger", "openapi", "vs code", "intellij",
        "vim", "emacs",
    }

    # Soft skills keywords
    SOFT_SKILLS = {
        "leadership", "communication", "teamwork", "problem solving", "problem-solving",
        "analytical", "critical thinking", "time management", "project management",
        "agile", "scrum", "kanban", "collaboration", "mentoring", "coaching",
        "presentation", "negotiation", "conflict resolution", "adaptability",
        "creativity", "innovation", "attention to detail", "decision making",
        "strategic thinking", "customer service", "interpersonal", "multitasking",
        "organization", "planning", "prioritization", "self-motivated", "initiative",
    }

    # Languages
    SPOKEN_LANGUAGES = {
        "english", "spanish", "french", "german", "chinese", "mandarin", "cantonese",
        "japanese", "korean", "portuguese", "italian", "russian", "arabic", "hindi",
        "bengali", "urdu", "dutch", "swedish", "polish", "turkish", "vietnamese",
        "thai", "indonesian", "malay", "tagalog", "hebrew", "greek", "czech",
    }

    # Education degree patterns (English and Spanish)
    DEGREE_PATTERNS = [
        # English degrees
        r"(?i)(ph\.?d\.?|doctor(?:ate)?)\s*(?:of|in)?\s*(\w+(?:\s+\w+)*)?",
        r"(?i)(master'?s?|m\.?s\.?|m\.?a\.?|m\.?b\.?a\.?|m\.?eng\.?)\s*(?:of|in)?\s*(\w+(?:\s+\w+)*)?",
        r"(?i)(bachelor'?s?|b\.?s\.?|b\.?a\.?|b\.?eng\.?|b\.?tech\.?)\s*(?:of|in)?\s*(\w+(?:\s+\w+)*)?",
        r"(?i)(associate'?s?|a\.?s\.?|a\.?a\.?)\s*(?:of|in)?\s*(\w+(?:\s+\w+)*)?",
        # Spanish degrees
        r"(?i)(doctorado|doctor|ph\.?d\.?)\s*(?:en)?\s*(\w+(?:\s+\w+)*)?",
        r"(?i)(maestr[ií]a|master|mag[ií]ster|m\.?s\.?c\.?)\s*(?:en)?\s*(\w+(?:\s+\w+)*)?",
        r"(?i)(licenciatura|licenciado|ingenier[ií]a|ingeniero|grado)\s*(?:en)?\s*(\w+(?:\s+\w+)*)?",
        r"(?i)(t[eé]cnico|tecnicatura|diplomado)\s*(?:en)?\s*(\w+(?:\s+\w+)*)?",
    ]

    # Date patterns (English and Spanish)
    DATE_PATTERNS = [
        # English months
        r"(?i)(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*[,.]?\s*(\d{4})",
        # Spanish months
        r"(?i)(ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|abr(?:il)?|may(?:o)?|jun(?:io)?|jul(?:io)?|ago(?:sto)?|sep(?:t(?:iembre)?)?|oct(?:ubre)?|nov(?:iembre)?|dic(?:iembre)?)\s*[,.]?\s*(\d{4})",
        r"(\d{1,2})[/\-](\d{4})",
        r"(\d{4})\s*[-–]\s*(\d{4}|present|current|now|actual|actualidad|presente)",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        self.email_regex = re.compile(self.EMAIL_PATTERN)
        self.phone_regex = re.compile(self.PHONE_PATTERN)
        self.linkedin_regex = re.compile(self.LINKEDIN_PATTERN)
        self.github_regex = re.compile(self.GITHUB_PATTERN)

    def parse_resume(
        self,
        resume_text: str,
        document_id: Optional[str] = None
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
                parsing_method="hybrid",
                sections_found=[]
            )

        # Clean and normalize text
        cleaned_text = self._clean_text(resume_text)
        lines = cleaned_text.split("\n")

        # Detect sections
        sections = self._detect_sections(lines)
        sections_found = list(sections.keys())

        # Extract data
        contact = self._extract_contact(cleaned_text, lines[:20])  # Header usually in first 20 lines
        summary = self._extract_summary(sections.get("summary", ""), lines[:30])
        experience = self._extract_experience(sections.get("experience", ""))
        education = self._extract_education(sections.get("education", ""))
        skills = self._extract_skills(cleaned_text, sections.get("skills", ""))

        # Calculate confidence score
        confidence = self._calculate_confidence(contact, summary, experience, education, skills)

        logger.info(
            f"Parsed resume {document_id}: "
            f"sections={sections_found}, "
            f"experience={len(experience)}, "
            f"education={len(education)}, "
            f"skills={len(skills.all_skills)}, "
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
            parsing_method="hybrid",
            sections_found=sections_found
        )

    def _clean_text(self, text: str) -> str:
        """Clean and normalize resume text."""
        # Remove excessive whitespace
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\r", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove common artifacts
        text = re.sub(r"[•●○◦▪▫]", "-", text)
        return text.strip()

    def _detect_sections(self, lines: List[str]) -> Dict[str, str]:
        """Detect and extract resume sections."""
        sections = {}
        current_section = "header"
        current_content = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                current_content.append("")
                continue

            # Check if line is a section header
            section_found = None
            for section_name, pattern in self.SECTION_PATTERNS.items():
                if re.match(pattern, line_stripped):
                    section_found = section_name
                    break

            if section_found:
                # Save previous section
                if current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = section_found
                current_content = []
            else:
                current_content.append(line)

        # Save last section
        if current_content:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_contact(self, full_text: str, header_lines: List[str]) -> ParsedContact:
        """Extract contact information."""
        header_text = "\n".join(header_lines)

        # Extract email
        email_match = self.email_regex.search(full_text)
        email = email_match.group(0) if email_match else None

        # Extract phone
        phone_match = self.phone_regex.search(full_text)
        phone = phone_match.group(0) if phone_match else None

        # Extract LinkedIn
        linkedin_match = self.linkedin_regex.search(full_text)
        linkedin = linkedin_match.group(0) if linkedin_match else None

        # Extract GitHub
        github_match = self.github_regex.search(full_text)
        github = github_match.group(0) if github_match else None

        # Extract name (usually first non-empty line in header)
        full_name = None
        for line in header_lines[:5]:
            line = line.strip()
            # Skip lines that look like contact info
            if line and not self.email_regex.search(line) and not self.phone_regex.search(line):
                if not re.match(r"^[\d\s\-\(\)\+]+$", line):  # Not just phone
                    if len(line.split()) <= 4:  # Name usually 1-4 words
                        full_name = line
                        break

        # Extract location (look for city, state patterns)
        location = None
        location_pattern = r"([A-Z][a-zA-Z\s]+,\s*[A-Z]{2}(?:\s+\d{5})?)"
        location_match = re.search(location_pattern, header_text)
        if location_match:
            location = location_match.group(1).strip()

        return ParsedContact(
            email=email,
            phone=phone,
            full_name=full_name,
            location=location,
            linkedin=linkedin,
            github=github,
            portfolio=None
        )

    def _extract_summary(self, section_text: str, header_lines: List[str]) -> ParsedSummary:
        """Extract professional summary and headline."""
        summary_text = section_text.strip() if section_text else None

        # Try to extract headline from header or summary
        headline = None
        if summary_text:
            # First sentence or line might be headline
            first_line = summary_text.split("\n")[0].strip()
            if len(first_line) < 100:  # Headlines are usually short
                headline = first_line

        # Look for headline in header (often after name)
        if not headline:
            for i, line in enumerate(header_lines[1:6]):  # Skip name, check next few lines
                line = line.strip()
                if line and not self.email_regex.search(line) and not self.phone_regex.search(line):
                    if not re.match(r"^[\d\s\-\(\)\+]+$", line):
                        if len(line) < 80 and len(line) > 10:
                            # Check if it looks like a title (English and Spanish)
                            title_words = [
                                # English
                                "engineer", "developer", "manager", "analyst", "designer",
                                "architect", "specialist", "consultant", "director", "lead",
                                # Spanish
                                "ingeniero", "desarrollador", "programador", "gerente", "analista",
                                "diseñador", "arquitecto", "especialista", "consultor", "director",
                                "líder", "coordinador", "jefe", "técnico", "administrador"
                            ]
                            if any(word in line.lower() for word in title_words):
                                headline = line
                                break

        return ParsedSummary(
            summary=summary_text,
            headline=headline
        )

    def _extract_experience(self, section_text: str) -> List[ParsedExperience]:
        """Extract work experience entries."""
        if not section_text:
            return []

        experiences = []
        lines = section_text.split("\n")

        current_exp = None
        current_description = []

        for line in lines:
            line = line.strip()
            if not line:
                if current_exp and current_description:
                    current_exp["description"] = " ".join(current_description).strip()
                    current_description = []
                continue

            # Check for date patterns indicating new experience entry
            date_match = None
            for pattern in self.DATE_PATTERNS:
                match = re.search(pattern, line)
                if match:
                    date_match = match
                    break

            # Check if line looks like a job title/company header
            is_header = bool(date_match) or self._looks_like_job_header(line)

            if is_header and current_exp:
                # Save previous experience
                if current_description:
                    current_exp["description"] = " ".join(current_description).strip()
                experiences.append(ParsedExperience(**current_exp))
                current_exp = None
                current_description = []

            if is_header:
                # Parse the header line
                title, company = self._parse_job_header(line)
                start_date, end_date, is_current = self._parse_dates(line)

                current_exp = {
                    "title": title or "Unknown Position",
                    "company": company or "Unknown Company",
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_current": is_current,
                    "location": None,
                    "description": None
                }
            elif current_exp:
                # Add to description
                if line.startswith("-") or line.startswith("•"):
                    line = line[1:].strip()
                current_description.append(line)

        # Save last experience
        if current_exp:
            if current_description:
                current_exp["description"] = " ".join(current_description).strip()
            experiences.append(ParsedExperience(**current_exp))

        return experiences

    def _looks_like_job_header(self, line: str) -> bool:
        """Check if a line looks like a job title/company header."""
        # Common patterns in job headers (English and Spanish)
        patterns = [
            # English job titles
            r"(?i)(engineer|developer|manager|analyst|designer|director|lead|specialist|consultant|intern|associate)",
            # Spanish job titles
            r"(?i)(ingeniero|desarrollador|programador|gerente|analista|dise[ñn]ador|director|l[ií]der|especialista|consultor|practicante|asistente|coordinador|jefe|supervisor|t[eé]cnico|arquitecto|administrador)",
            r"@|at\s+[A-Z]",  # "at Company"
            r"[A-Z][a-z]+\s*[-|]\s*[A-Z]",  # "Title - Company" or "Title | Company"
            r"(?i)\s+en\s+[A-Z]",  # "en Empresa" (Spanish "at Company")
        ]
        for pattern in patterns:
            if re.search(pattern, line):
                return True
        return False

    def _parse_job_header(self, line: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse job title and company from a header line."""
        # Remove date portions
        for pattern in self.DATE_PATTERNS:
            line = re.sub(pattern, "", line)

        # Common separators
        separators = [" at ", " @ ", " - ", " | ", ", "]
        for sep in separators:
            if sep in line:
                parts = line.split(sep, 1)
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()

        return line.strip(), None

    def _parse_dates(self, line: str) -> Tuple[Optional[str], Optional[str], bool]:
        """Parse start/end dates from a line."""
        line_lower = line.lower()
        # Check for current position indicators (English and Spanish)
        is_current = any(word in line_lower for word in [
            "present", "current", "now",  # English
            "actual", "actualidad", "presente", "vigente"  # Spanish
        ])

        dates = []
        for pattern in self.DATE_PATTERNS:
            matches = re.findall(pattern, line)
            dates.extend(matches)

        start_date = None
        end_date = None

        if dates:
            if isinstance(dates[0], tuple):
                start_date = " ".join(str(d) for d in dates[0] if d).strip()
            else:
                start_date = str(dates[0]).strip()

            if len(dates) > 1:
                if isinstance(dates[1], tuple):
                    end_date = " ".join(str(d) for d in dates[1] if d).strip()
                else:
                    end_date = str(dates[1]).strip()

        if is_current:
            end_date = None

        return start_date, end_date, is_current

    def _extract_education(self, section_text: str) -> List[ParsedEducation]:
        """Extract education entries."""
        if not section_text:
            return []

        education = []
        lines = section_text.split("\n")

        current_edu = None
        current_description = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for degree patterns
            degree_match = None
            for pattern in self.DEGREE_PATTERNS:
                match = re.search(pattern, line)
                if match:
                    degree_match = match
                    break

            # Check for institution keywords (English and Spanish)
            is_institution = any(word in line.lower() for word in [
                # English
                "university", "college", "institute", "school", "academy",
                # Spanish
                "universidad", "colegio", "instituto", "escuela", "academia",
                "facultad", "politécnico", "politecnico", "tecnológico", "tecnologico"
            ])

            if degree_match or is_institution:
                # Save previous education
                if current_edu:
                    if current_description:
                        current_edu["description"] = " ".join(current_description).strip()
                    education.append(ParsedEducation(**current_edu))
                    current_description = []

                degree = degree_match.group(0) if degree_match else None
                institution = None
                field_of_study = None

                # Try to extract institution
                if is_institution:
                    institution = line
                    if degree:
                        institution = line.replace(degree, "").strip(" -,|")

                # Parse dates
                start_date, end_date, _ = self._parse_dates(line)

                # Look for GPA
                gpa = None
                gpa_match = re.search(r"(?i)gpa[:\s]*(\d+\.?\d*)", line)
                if gpa_match:
                    gpa = gpa_match.group(1)

                current_edu = {
                    "degree": degree or "Degree",
                    "institution": institution or "Institution",
                    "field_of_study": field_of_study,
                    "start_date": start_date,
                    "end_date": end_date,
                    "gpa": gpa,
                    "description": None
                }
            elif current_edu:
                current_description.append(line)

        # Save last education
        if current_edu:
            if current_description:
                current_edu["description"] = " ".join(current_description).strip()
            education.append(ParsedEducation(**current_edu))

        return education

    def _extract_skills(self, full_text: str, skills_section: str) -> ParsedSkills:
        """Extract and categorize skills."""
        text_to_search = f"{full_text}\n{skills_section}".lower()

        technical = []
        soft = []
        languages = []
        certifications = []

        # Extract technical skills
        for skill in self.TECHNICAL_SKILLS:
            if skill.lower() in text_to_search:
                # Use proper casing
                technical.append(skill.title() if skill.islower() else skill)

        # Extract soft skills
        for skill in self.SOFT_SKILLS:
            if skill.lower() in text_to_search:
                soft.append(skill.title())

        # Extract languages
        for lang in self.SPOKEN_LANGUAGES:
            if lang.lower() in text_to_search:
                languages.append(lang.title())

        # Look for certifications
        cert_patterns = [
            r"(?i)(aws\s+certified[\w\s-]*)",
            r"(?i)(azure[\w\s-]*certified)",
            r"(?i)(google\s+cloud[\w\s-]*)",
            r"(?i)(pmp|project management professional)",
            r"(?i)(cpa|certified public accountant)",
            r"(?i)(cissp|cism|ceh)",
            r"(?i)(scrum\s*master)",
            r"(?i)(six\s*sigma[\w\s-]*)",
        ]
        for pattern in cert_patterns:
            matches = re.findall(pattern, full_text)
            certifications.extend([m.strip() for m in matches if m])

        # Deduplicate while preserving order
        technical = list(dict.fromkeys(technical))
        soft = list(dict.fromkeys(soft))
        languages = list(dict.fromkeys(languages))
        certifications = list(dict.fromkeys(certifications))

        all_skills = technical + soft

        return ParsedSkills(
            technical_skills=technical[:30],  # Limit to 30
            soft_skills=soft[:15],
            languages=languages[:10],
            certifications=certifications[:10],
            all_skills=all_skills[:50]
        )

    def _calculate_confidence(
        self,
        contact: ParsedContact,
        summary: ParsedSummary,
        experience: List[ParsedExperience],
        education: List[ParsedEducation],
        skills: ParsedSkills
    ) -> float:
        """Calculate confidence score for the parsing result."""
        score = 0.0
        max_score = 10.0

        # Contact info (2 points max)
        if contact.full_name:
            score += 0.5
        if contact.email:
            score += 0.5
        if contact.phone:
            score += 0.5
        if contact.linkedin or contact.github:
            score += 0.5

        # Summary (1 point max)
        if summary.summary:
            score += 0.5
        if summary.headline:
            score += 0.5

        # Experience (3 points max)
        if experience:
            score += min(len(experience), 3) * 1.0

        # Education (2 points max)
        if education:
            score += min(len(education), 2) * 1.0

        # Skills (2 points max)
        if skills.all_skills:
            score += min(len(skills.all_skills) / 10, 2.0)

        return min(score / max_score, 1.0)


# Singleton instance
resume_parser_service = ResumeParserService()
