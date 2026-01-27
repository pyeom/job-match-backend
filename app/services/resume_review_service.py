"""
AI-powered resume review service.

This service analyzes resumes and provides actionable improvement suggestions.
It evaluates structure, content, keywords, formatting, and relevance to target jobs.
"""

from typing import Optional, List, Dict, Set
from uuid import UUID
import re
import logging

from app.schemas.resume_review import (
    ResumeReviewResponse,
    ResumeSection,
    KeywordAnalysis
)
from app.models.document import Document
from app.models.job import Job

logger = logging.getLogger(__name__)


class ResumeReviewService:
    """Service for analyzing resumes and generating improvement suggestions."""

    # Common resume sections to look for
    EXPECTED_SECTIONS = {
        "contact", "summary", "objective", "experience", "work", "employment",
        "education", "skills", "projects", "certifications", "achievements",
        "awards", "publications", "languages"
    }

    # Keywords indicating quantified achievements
    QUANTIFICATION_KEYWORDS = [
        r'\d+%', r'\$\d+', r'\d+\+', r'\d+x', r'\d+ million', r'\d+ billion',
        r'\d+ thousand', r'increased', r'decreased', r'reduced', r'improved',
        r'grew', r'generated', r'saved', r'achieved'
    ]

    # Contact information patterns
    CONTACT_PATTERNS = [
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # Phone number
        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # Phone with area code
    ]

    # Action verbs for strong resume writing
    STRONG_ACTION_VERBS = {
        "led", "managed", "developed", "created", "implemented", "designed",
        "achieved", "improved", "increased", "reduced", "launched", "built",
        "established", "coordinated", "directed", "executed", "optimized",
        "streamlined", "delivered", "drove", "spearheaded", "initiated"
    }

    def analyze_resume(
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

            # Calculate overall score
            overall_score = self._calculate_overall_score(
                structure_score,
                content_score,
                formatting_score,
                relevance_score
            )

            # Generate insights
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

            # Generate executive summary
            summary = self._generate_summary(
                overall_score, strengths, weaknesses, target_job
            )

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
        """Detect major sections in the resume."""
        sections = {}
        current_section = "header"
        current_content = []

        for line in lines:
            line_lower = line.lower().strip()

            # Check if line is a section header
            is_section_header = False
            for section_keyword in self.EXPECTED_SECTIONS:
                if section_keyword in line_lower and len(line.split()) <= 3:
                    # Save previous section
                    if current_content:
                        sections[current_section] = '\n'.join(current_content)

                    # Start new section
                    current_section = section_keyword
                    current_content = []
                    is_section_header = True
                    break

            if not is_section_header and line.strip():
                current_content.append(line)

        # Save last section
        if current_content:
            sections[current_section] = '\n'.join(current_content)

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
        """Analyze education section."""
        score = 0.7
        strengths = []
        weaknesses = []
        suggestions = []

        # Check for degree information
        has_degree = bool(re.search(
            r'\b(bachelor|master|phd|doctorate|associate|b\.s\.|m\.s\.|b\.a\.|m\.a\.)\b',
            content, re.IGNORECASE
        ))

        if has_degree:
            strengths.append("Includes degree information")
            score += 0.15
        else:
            suggestions.append("Clearly state your degree type (Bachelor's, Master's, etc.)")

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
