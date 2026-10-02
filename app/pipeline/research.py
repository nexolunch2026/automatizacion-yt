"""RESEARCH ENGINE: investiga el tema y produce un informe con fuentes.

Regla principal: nunca inventar fuentes. Las fuentes salen solo de las búsquedas reales
de Gemini; un dato que no se puede asociar a una fuente pasa a «por verificar».
"""

from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import Project
from app.providers.ai import AIProvider


class Fact(BaseModel):
    text: str = Field(description="Afirmación concreta y breve")
    sources: list[int] = Field(description="Números de las fuentes que la respaldan, ej. [1, 3]")


class Angle(BaseModel):
    title: str
    description: str


class ResearchBrief(BaseModel):
    context: str = Field(description="Contexto general en 3–5 frases")
    key_facts: list[Fact]
    timeline: list[Fact] = Field(description="Fechas y acontecimientos en orden cronológico")
    people: list[Fact] = Field(description="Personas u organizaciones relevantes y su papel")
    figures: list[Fact] = Field(description="Cifras importantes")
    angles: list[Angle] = Field(description="3–5 enfoques posibles para el vídeo")
    controversial: list[str] = Field(description="Puntos discutidos o con versiones distintas")
    needs_verification: list[str] = Field(description="Datos dudosos o sin fuente clara")


def _research_prompt(project: Project) -> str:
    return f"""Investiga a fondo este tema para un vídeo de YouTube de tipo «{project.video_type}»
y duración «{project.duration}». Idioma de la respuesta: {project.language}.

Tema: {project.topic}

Busca en varias fuentes fiables y reúne: contexto, hechos principales, fechas,
personas u organizaciones implicadas, cifras, acontecimientos, puntos controvertidos
y datos que conviene verificar. Si las fuentes se contradicen, dilo.
Usa solo información que aparezca en las fuentes; no inventes nada."""


def _structure_prompt(project: Project, text: str, n_sources: int) -> str:
    return f"""Convierte esta investigación en un informe estructurado en {project.language}.

La investigación cita fuentes con marcas [n]. Hay {n_sources} fuentes, numeradas de 1 a
{n_sources}. Para cada dato, copia en «sources» los números de las marcas que lo
respaldan en el texto. Si un dato no tiene marca, no lo pongas en los hechos: ponlo en
«needs_verification». No añadas información que no esté en el texto.

INVESTIGACIÓN:
{text}"""


def _clean_facts(facts: list[Fact], n_sources: int, unverified: list[str]) -> list[dict]:
    """Quita números de fuente inexistentes y manda a «por verificar» lo que se queda sin fuente."""
    kept = []
    for fact in facts:
        valid = sorted({s for s in fact.sources if 1 <= s <= n_sources})
        if valid:
            kept.append({"text": fact.text, "sources": valid})
        else:
            unverified.append(f"{fact.text} (sin fuente)")
    return kept


def run_research(project: Project, ai: AIProvider, progress: Callable[[int, str], None]) -> dict:
    progress(10, "Buscando información en internet")
    grounded = ai.grounded_research(_research_prompt(project))
    n = len(grounded.sources)

    progress(60, "Organizando el informe")
    brief = ai.generate_json(_structure_prompt(project, grounded.text, n), ResearchBrief)

    unverified = list(brief.needs_verification)
    data = {
        "context": brief.context,
        "key_facts": _clean_facts(brief.key_facts, n, unverified),
        "timeline": _clean_facts(brief.timeline, n, unverified),
        "people": _clean_facts(brief.people, n, unverified),
        "figures": _clean_facts(brief.figures, n, unverified),
        "angles": [a.model_dump() for a in brief.angles],
        "controversial": brief.controversial,
        "needs_verification": unverified,
        "sources": [
            {"n": i + 1, "title": s.title, "uri": s.uri} for i, s in enumerate(grounded.sources)
        ],
        "queries": grounded.queries,
        "provider": ai.name,
    }
    if n == 0:
        data["warning"] = (
            "La búsqueda no devolvió fuentes. Todo el informe queda pendiente de verificar."
        )
    progress(100, "Informe listo")
    return data
