"""Unit tests for MALA schemas and TextQualityValidator."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.mala import MalaResponseCreate
from app.services.nlp.text_quality import TextQualityValidator


class TestMalaResponseCreate:
    def test_rejects_text_shorter_than_10_chars(self):
        with pytest.raises(ValidationError):
            MalaResponseCreate(question_code="P1", response_text="short")

    def test_rejects_invalid_question_code_p0(self):
        with pytest.raises(ValidationError):
            MalaResponseCreate(
                question_code="P0",
                response_text="This is a valid response text for testing purposes.",
            )

    def test_rejects_invalid_question_code_p13(self):
        with pytest.raises(ValidationError):
            MalaResponseCreate(
                question_code="P13",
                response_text="This is a valid response text for testing purposes.",
            )

    def test_rejects_invalid_question_code_x1(self):
        with pytest.raises(ValidationError):
            MalaResponseCreate(
                question_code="X1",
                response_text="This is a valid response text for testing purposes.",
            )

    def test_rejects_empty_question_code(self):
        with pytest.raises(ValidationError):
            MalaResponseCreate(
                question_code="",
                response_text="This is a valid response text for testing purposes.",
            )

    @pytest.mark.parametrize("code", [f"P{i}" for i in range(1, 13)])
    def test_accepts_valid_question_codes_p1_to_p12(self, code: str):
        obj = MalaResponseCreate(
            question_code=code,
            response_text="This is a valid response text for testing purposes.",
        )
        assert obj.question_code == code


class TestTextQualityValidator:
    def setup_method(self):
        self.validator = TextQualityValidator()

    def test_short_text_is_too_short(self):
        text = "Esta es una respuesta muy corta."
        result = self.validator.validate(text, "P1")
        assert result.is_too_short is True
        assert result.completeness_level == "insufficient"

    def test_generic_text_flags_social_desirability(self):
        text = (
            "Soy responsable y trabajo en equipo. "
            "Me comprometo con los proyectos que se me asignan. "
            "Soy proactivo y siempre entrego resultados. "
            "Tengo experiencia en muchos proyectos y soy muy trabajador. "
            "Siempre cumplo con mis responsabilidades y me esfuerzo al máximo. "
            "Considero que el trabajo en equipo es fundamental para el éxito."
        )
        result = self.validator.validate(text, "P3")
        assert result.social_desirability_initial_flag is True

    def test_good_long_text_has_high_quality_score(self):
        text = (
            "Implementé un sistema de gestión de proyectos que aumentó la productividad del equipo en un 35%. "
            "Desarrollé una metodología ágil adaptada a las necesidades específicas de nuestra empresa. "
            "Lideré un equipo de 8 personas durante 18 meses, logrando reducir el tiempo de entrega en un 20%. "
            "Diseñé procesos de revisión de código que mejoraron la calidad del software significativamente. "
            "Coordiné con diferentes departamentos para asegurar la alineación de objetivos y recursos. "
            "Trabajé directamente con los clientes para entender sus necesidades y traducirlas en requisitos técnicos. "
            "Creé dashboards de seguimiento que permitieron identificar cuellos de botella en tiempo real."
        )
        result = self.validator.validate(text, "P4")
        assert result.quality_score >= 0.50
        assert result.meets_recommended_length is True
