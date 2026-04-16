from __future__ import annotations
from typing import Optional
from app.schemas.mala import QuestionBlock, QuestionSchema

MALA_QUESTIONS: list[QuestionSchema] = [
    QuestionSchema(
        code="P1",
        block=QuestionBlock.A,
        block_name="Identidad Profesional",
        text="Cuéntame el momento en tu carrera en que más has sentido que estabas en tu elemento. ¿Qué hacías? ¿Qué tenía de especial?",
        guidance="Describe la situación con detalle: qué hacías, cómo te sentías, qué características tenía ese trabajo.",
        min_words_recommended=80,
        time_guidance_seconds=180,
        order_in_block=1,
    ),
    QuestionSchema(
        code="P2",
        block=QuestionBlock.A,
        block_name="Identidad Profesional",
        text="¿Qué trabajo te han pedido hacer que sentiste que no era para ti? Sin mencionar nombres, ¿qué tenía ese trabajo que te generaba esa sensación?",
        guidance="Describe qué tipo de tarea o rol te generaba esa sensación y por qué.",
        min_words_recommended=70,
        time_guidance_seconds=150,
        order_in_block=2,
    ),
    QuestionSchema(
        code="P3",
        block=QuestionBlock.A,
        block_name="Identidad Profesional",
        text="Si tuvieras que describirle a alguien tu forma de trabajar en tres aspectos concretos, sin usar adjetivos como 'responsable' o 'comprometido', ¿qué dirías?",
        guidance="Usa ejemplos de acciones concretas, no adjetivos genéricos.",
        min_words_recommended=80,
        time_guidance_seconds=180,
        order_in_block=3,
    ),
    QuestionSchema(
        code="P4",
        block=QuestionBlock.B,
        block_name="Situaciones Conductuales",
        text="Cuéntame de un proyecto o tarea que salió muy diferente a lo que planificaste. ¿Cómo llegaste a ese resultado?",
        guidance="Describe la situación, qué pasó diferente y qué hiciste concretamente.",
        min_words_recommended=100,
        time_guidance_seconds=240,
        order_in_block=1,
    ),
    QuestionSchema(
        code="P5",
        block=QuestionBlock.B,
        block_name="Situaciones Conductuales",
        text="Descríbeme una situación en que hayas tenido que convencer a alguien de algo en lo que no creía inicialmente. ¿Cómo lo hiciste y cuál fue el resultado?",
        guidance="Describe la estrategia que usaste y qué pasó finalmente.",
        min_words_recommended=100,
        time_guidance_seconds=240,
        order_in_block=2,
    ),
    QuestionSchema(
        code="P6",
        block=QuestionBlock.B,
        block_name="Situaciones Conductuales",
        text="Piensa en el equipo más efectivo en que has trabajado. ¿Qué lo hacía funcionar? ¿Y cuál fue tu rol específico en ese funcionamiento?",
        guidance="Describe qué hacía especial a ese equipo y qué aportabas tú.",
        min_words_recommended=90,
        time_guidance_seconds=210,
        order_in_block=3,
    ),
    QuestionSchema(
        code="P7",
        block=QuestionBlock.B,
        block_name="Situaciones Conductuales",
        text="Cuéntame de una vez que hayas cometido un error importante en tu trabajo. ¿Qué pasó, qué hiciste y qué cambió en ti después?",
        guidance="Sé específico/a sobre el error, tus acciones y el aprendizaje.",
        min_words_recommended=100,
        time_guidance_seconds=240,
        order_in_block=4,
    ),
    QuestionSchema(
        code="P8",
        block=QuestionBlock.C,
        block_name="Dilemas Situacionales",
        text="Tu equipo lleva semanas trabajando duro en un proyecto. Descubres que una decisión que tomaste hace un mes tiene un error que podría impactar el resultado. Tu jefe no lo sabe. ¿Qué haces y por qué?",
        guidance="Describe paso a paso qué harías y el razonamiento detrás.",
        min_words_recommended=80,
        time_guidance_seconds=180,
        order_in_block=1,
    ),
    QuestionSchema(
        code="P9",
        block=QuestionBlock.C,
        block_name="Dilemas Situacionales",
        text="Tienes que priorizar: terminar una tarea urgente prometida a tu jefe, o apoyar a un colega que claramente está sobrepasado con algo crítico para el equipo. No puedes hacer las dos cosas. ¿Qué decides?",
        guidance="Explica tu razonamiento y qué factores pesan más en tu decisión.",
        min_words_recommended=70,
        time_guidance_seconds=150,
        order_in_block=2,
    ),
    QuestionSchema(
        code="P10",
        block=QuestionBlock.C,
        block_name="Dilemas Situacionales",
        text="Tu empresa lanza un producto que personalmente sientes que no está listo, pero la dirección decidió hacerlo así por presión de mercado. Tú tienes que ejecutarlo. ¿Cómo manejas eso internamente y hacia afuera?",
        guidance="Describe cómo gestionarías la situación contigo mismo y con tu equipo/clientes.",
        min_words_recommended=80,
        time_guidance_seconds=180,
        order_in_block=3,
    ),
    QuestionSchema(
        code="P11",
        block=QuestionBlock.D,
        block_name="Reflexión Futura",
        text="¿En qué tipo de problema o desafío profesional te gustaría estar trabajando dentro de 3 años? Sé lo más específico que puedas.",
        guidance="Describe el tipo de problema, contexto o industria, no solo el cargo.",
        min_words_recommended=70,
        time_guidance_seconds=150,
        order_in_block=1,
    ),
    QuestionSchema(
        code="P12",
        block=QuestionBlock.D,
        block_name="Reflexión Futura",
        text="¿Qué te haría abandonar un trabajo que paga bien? Y al contrario: ¿qué te haría quedarte en un trabajo que paga menos de lo que podrías ganar en otro lado?",
        guidance="Sé honesto/a: describe los motivadores reales que pesarían en esa decisión.",
        min_words_recommended=80,
        time_guidance_seconds=180,
        order_in_block=2,
    ),
]

_BY_CODE: dict[str, QuestionSchema] = {q.code: q for q in MALA_QUESTIONS}

_BLOCK_ORDER = [QuestionBlock.A, QuestionBlock.B, QuestionBlock.C, QuestionBlock.D]


def get_question_by_code(code: str) -> Optional[QuestionSchema]:
    return _BY_CODE.get(code)


def get_questions_by_block(block: QuestionBlock) -> list[QuestionSchema]:
    return sorted(
        [q for q in MALA_QUESTIONS if q.block == block],
        key=lambda q: q.order_in_block,
    )


def get_next_question(answered_codes: list[str]) -> Optional[QuestionSchema]:
    answered_set = set(answered_codes)
    for block in _BLOCK_ORDER:
        for question in get_questions_by_block(block):
            if question.code not in answered_set:
                return question
    return None
