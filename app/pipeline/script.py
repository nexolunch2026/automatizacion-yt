"""SCRIPT ENGINE: escribe el guion y permite reescribir párrafos sueltos."""

import uuid
from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import WORDS_BY_DURATION, Project
from app.pipeline.context import research_summary
from app.providers.ai import AIProvider

SECTION_LABELS = {
    "hook": "Gancho",
    "promise": "Promesa",
    "intro": "Introducción",
    "development": "Desarrollo",
    "climax": "Clímax",
    "conclusion": "Conclusión",
    "cta": "Llamada a la acción",
}


class Paragraph(BaseModel):
    text: str = Field(description="Texto que se narrará, tal cual")
    sources: list[int] = Field(description="Números de fuente de los datos usados, o []")


class Section(BaseModel):
    kind: str = Field(description="hook, promise, intro, development, climax, conclusion o cta")
    title: str
    paragraphs: list[Paragraph]


class Script(BaseModel):
    title: str
    sections: list[Section]


class Rewrite(BaseModel):
    text: str
    sources: list[int]


def default_params() -> dict:
    return {"tone": "Documental", "drama": "Medio", "technical": "Bajo"}


def _style(params: dict) -> str:
    return (
        f"Tono: {params.get('tone', 'Documental')}. "
        f"Nivel de dramatismo: {params.get('drama', 'Medio')}. "
        f"Nivel técnico: {params.get('technical', 'Bajo')}."
    )


def _prompt(project: Project, research: dict, concept: dict, title: str, params: dict) -> str:
    words = WORDS_BY_DURATION.get(project.duration, 1100)
    return f"""Escribe el guion de narración de un vídeo de YouTube faceless en {project.language}.

Título: {title}
Enfoque: {concept["angle"]} — {concept["summary"]}
Promesa al espectador: {concept["promise"]}
Gancho sugerido: {concept["hook"]}
Audiencia: {concept["audience"]}
{_style(params)}
Extensión total: unas {words} palabras de narración.

Estructura en este orden (usa exactamente estos valores en «kind»):
hook (5–15 s que enganchen), promise (qué va a descubrir), intro, development (puede
haber varias secciones development), climax, conclusion, cta (breve y natural).

Reglas:
- Solo texto para narrar en voz alta: sin acotaciones, sin «[música]», sin emojis.
- Frases claras y con ritmo; párrafos de 2–4 frases.
- Usa SOLO datos de la investigación y pon en «sources» los números entre corchetes de
  los datos que uses. Lo controvertido, preséntalo como discutido. Lo no verificado, no
  lo afirmes.
- Nada de relleno ni repeticiones.

INVESTIGACIÓN:
{research_summary(research)}"""


def _valid_sources(sources: list[int], n_sources: int) -> list[int]:
    return sorted({n for n in sources if 1 <= n <= n_sources})


def _with_ids(script: Script, n_sources: int) -> dict:
    sections = []
    for section in script.sections:
        kind = section.kind if section.kind in SECTION_LABELS else "development"
        sections.append(
            {
                "kind": kind,
                "title": section.title or SECTION_LABELS[kind],
                "paragraphs": [
                    {
                        "id": uuid.uuid4().hex[:8],
                        "text": p.text.strip(),
                        "sources": _valid_sources(p.sources, n_sources),
                    }
                    for p in section.paragraphs
                    if p.text.strip()
                ],
            }
        )
    return {"title": script.title, "sections": sections}


def word_count(script: dict) -> int:
    return sum(len(p["text"].split()) for s in script.get("sections", []) for p in s["paragraphs"])


def with_stats(script: dict) -> dict:
    words = word_count(script)
    script["words"] = words
    script["minutes"] = round(words / 150, 1)
    return script


def run_script(
    project: Project,
    research: dict,
    strategy: dict,
    ai: AIProvider,
    params: dict,
    progress: Callable[[int, str], None],
) -> dict:
    selected = strategy["selected"]
    concept = strategy["concepts"][selected["concept"]]
    title = concept["titles"][selected.get("title", 0)]["title"]
    progress(20, "Escribiendo el guion")
    script = ai.generate_json(_prompt(project, research, concept, title, params), Script)
    progress(100, "Guion listo")
    data = _with_ids(script, len(research.get("sources", [])))
    data["title"] = title
    data["params"] = params
    data["based_on"] = {"concept": selected["concept"], "title": selected.get("title", 0)}
    return with_stats(data)


REWRITE_ACTIONS = {
    "regenerate": "Reescribe este párrafo de otra forma, manteniendo la idea y los datos.",
    "expand": "Alarga este párrafo (más o menos el doble) con detalles de la investigación.",
    "summarize": "Resume este párrafo a la mitad, sin perder lo importante.",
    "tone": "Reescribe este párrafo con este tono: {tone}.",
}


def find_paragraph(script: dict, paragraph_id: str) -> tuple[dict, int, int] | None:
    for si, section in enumerate(script["sections"]):
        for pi, paragraph in enumerate(section["paragraphs"]):
            if paragraph["id"] == paragraph_id:
                return paragraph, si, pi
    return None


def rewrite_paragraph(
    project: Project,
    research: dict,
    script: dict,
    paragraph_id: str,
    action: str,
    ai: AIProvider,
    tone: str | None = None,
) -> dict:
    """Reescribe un único párrafo usando los de alrededor como contexto."""
    found = find_paragraph(script, paragraph_id)
    if found is None:
        raise KeyError(paragraph_id)
    paragraph, si, pi = found
    flat = [p for s in script["sections"] for p in s["paragraphs"]]
    index = next(i for i, p in enumerate(flat) if p["id"] == paragraph_id)
    before = flat[index - 1]["text"] if index > 0 else "(inicio del vídeo)"
    after = flat[index + 1]["text"] if index + 1 < len(flat) else "(final del vídeo)"
    instruction = REWRITE_ACTIONS[action].format(tone=tone or "más cercano")

    prompt = f"""Estás editando el guion del vídeo «{script["title"]}» en {project.language}.
{_style(script.get("params", default_params()))}

{instruction}
Solo texto para narrar; usa únicamente datos de la investigación y pon en «sources» los
números de fuente que uses.

PÁRRAFO ANTERIOR: {before}
PÁRRAFO A CAMBIAR: {paragraph["text"]}
PÁRRAFO SIGUIENTE: {after}

INVESTIGACIÓN:
{research_summary(research)}"""
    result = ai.generate_json(prompt, Rewrite)
    paragraph["text"] = result.text.strip()
    paragraph["sources"] = _valid_sources(result.sources, len(research.get("sources", [])))
    return with_stats(script)
