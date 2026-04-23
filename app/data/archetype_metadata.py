from __future__ import annotations

# Only non-translatable visual properties live here.
# All display strings (name, strengths, risks, ideal_cultures, matching_note)
# are stored in the frontend i18n locale files under archetypes.<id>.*.
ARCHETYPE_METADATA: dict[str, dict] = {
    "ejecutor_alto_impacto":    {"emoji": "🚀", "color": "#2E8B57"},
    "conector_relacional":      {"emoji": "🤝", "color": "#B22222"},
    "estratega_visionario":     {"emoji": "🔭", "color": "#6A0DAD"},
    "experto_analitico":        {"emoji": "🔬", "color": "#1A3A5C"},
    "adaptador_resiliente":     {"emoji": "🌊", "color": "#E07B39"},
    "lider_empatico":           {"emoji": "💡", "color": "#F5A623"},
    "emprendedor_interno":      {"emoji": "⚡", "color": "#2C3E50"},
    "constructor_sistemas":     {"emoji": "⚙️", "color": "#2F4F2F"},
    "explorador_epistemologico":{"emoji": "🧬", "color": "#1E8E8E"},
}
