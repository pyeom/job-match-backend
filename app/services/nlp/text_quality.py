from pydantic import BaseModel
from typing import Literal
import re


class TextQualityResult(BaseModel):
    token_count: int
    word_count: int
    language: str
    quality_score: float
    is_too_short: bool
    meets_recommended_length: bool
    social_desirability_initial_flag: bool
    feedback_message: str
    completeness_level: Literal["insufficient", "minimal", "good", "excellent"]


class TextQualityValidator:
    MIN_TOKENS = 30
    RECOMMENDED_TOKENS = 80
    GENERIC_PHRASES = [
        "soy responsable", "me comprometo", "trabajo en equipo",
        "soy proactivo", "tengo experiencia en"
    ]

    def validate(self, text: str, question_code: str) -> TextQualityResult:
        words = text.split()
        word_count = len(words)
        token_count = word_count  # simple approximation

        is_too_short = token_count < self.MIN_TOKENS
        meets_recommended = word_count >= self.RECOMMENDED_TOKENS

        text_lower = text.lower()
        generic_count = sum(1 for phrase in self.GENERIC_PHRASES if phrase in text_lower)
        social_desirability_flag = generic_count >= 2

        score = 0.0
        if word_count >= 80:
            score += 0.30
        elif word_count >= 50:
            score += 0.20

        if word_count > 0:
            unique_words = len(set(w.lower() for w in words))
            ttr = unique_words / word_count
            if ttr >= 0.45:
                score += 0.20

        if social_desirability_flag:
            score -= 0.30

        if re.search(r'\d+', text):
            score += 0.10

        action_verbs = [
            'implementé', 'desarrollé', 'lideré', 'gestioné', 'coordiné',
            'logré', 'diseñé', 'creé', 'aumenté', 'reduje', 'mejoré',
            'implementar', 'trabajé', 'hice', 'ayudé',
        ]
        if any(v in text_lower for v in action_verbs):
            score += 0.20

        score = max(0.0, min(1.0, score))

        if is_too_short:
            level = "insufficient"
            feedback = "Tu respuesta es muy corta. Por favor escribe al menos 30 palabras para un análisis válido."
        elif word_count < 50:
            level = "minimal"
            feedback = "Tu respuesta es válida pero breve. Te recomendamos al menos 80 palabras para un análisis más preciso."
        elif word_count < 80:
            level = "good"
            feedback = "Buena respuesta. Puedes agregar más detalle para mejorar el análisis."
        else:
            level = "excellent"
            feedback = "¡Excelente respuesta! Tienes suficiente detalle para un análisis completo."

        return TextQualityResult(
            token_count=token_count,
            word_count=word_count,
            language="es",
            quality_score=score,
            is_too_short=is_too_short,
            meets_recommended_length=meets_recommended,
            social_desirability_initial_flag=social_desirability_flag,
            feedback_message=feedback,
            completeness_level=level,
        )
