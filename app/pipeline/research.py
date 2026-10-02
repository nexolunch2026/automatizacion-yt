"""RESEARCH ENGINE: investiga el tema y produce un informe con fuentes.

Regla principal: nunca inventar fuentes. Las fuentes salen solo de búsquedas reales
(Google a través de Gemini o, si no está disponible, Wikipedia); un dato que no se
puede asociar a una fuente pasa a «por verificar».
"""

from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import Project
from app.providers.ai import AIProvider, GroundedText, ProviderError, Source
from app.providers.search import SearchProvider, WikipediaSearch


class Fact(BaseModel):
    text: str = Field(description="Afirmación concreta y breve")
    sources: list[int] = Field(description="Números de las fuentes que la respaldan, ej. [1, 3]")


class Angle(BaseModel):
    title: str
    description: str


class SearchQueries(BaseModel):
    queries: list[str] = Field(description="3–5 búsquedas cortas para Wikipedia")


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


def _queries_prompt(project: Project) -> str:
    return f"""Quiero investigar este tema en Wikipedia en {project.language}:

{project.topic}

Escribe de 3 a 5 búsquedas cortas (2–5 palabras cada una) que encuentren los artículos
más útiles: nombres concretos de personas, empresas, sucesos o conceptos."""


def _documents_prompt(project: Project, numbered: str, n_sources: int) -> str:
    return f"""Prepara un informe de investigación en {project.language} para un vídeo de
YouTube de tipo «{project.video_type}» sobre: {project.topic}

Usa SOLO la información de estos {n_sources} documentos de Wikipedia, numerados de 1 a
{n_sources}. Para cada dato, pon en «sources» los números de los documentos donde
aparece. Si algo no está en los documentos, no lo incluyas. Si los documentos se
contradicen, indícalo en «controversial».

{numbered}"""


def _research_with_google(
    project: Project, ai: AIProvider, progress
) -> tuple[ResearchBrief, GroundedText]:
    progress(10, "Buscando información en Google")
    grounded = ai.grounded_research(_research_prompt(project))
    progress(60, "Organizando el informe")
    prompt = _structure_prompt(project, grounded.text, len(grounded.sources))
    return ai.generate_json(prompt, ResearchBrief), grounded


def _research_with_wikipedia(
    project: Project, ai: AIProvider, search: SearchProvider, progress
) -> tuple[ResearchBrief, GroundedText]:
    progress(20, "Buscando información en Wikipedia")
    queries = ai.generate_json(_queries_prompt(project), SearchQueries).queries[:5]
    documents = search.search(queries or [project.topic], project.language)
    if not documents:
        raise ProviderError(
            "No se encontró información en Wikipedia sobre este tema. "
            "Prueba a escribir la idea con nombres más concretos."
        )
    progress(60, "Organizando el informe")
    numbered = "\n\n".join(f"[{i}] {d.title}\n{d.text}" for i, d in enumerate(documents, 1))
    brief = ai.generate_json(_documents_prompt(project, numbered, len(documents)), ResearchBrief)
    sources = [Source(title=f"Wikipedia: {d.title}", uri=d.url) for d in documents]
    return brief, GroundedText(text="", sources=sources, queries=queries)


def _should_fall_back(error: ProviderError) -> bool:
    """La búsqueda de Google falló por algo que Wikipedia puede sortear (cuota, permisos).
    Los errores temporales se reintentan, y una clave inválida no se arregla cambiando de fuente."""
    return not error.transient and "clave" not in str(error)


def run_research(
    project: Project,
    ai: AIProvider,
    progress: Callable[[int, str], None],
    search: SearchProvider | None = None,
) -> dict:
    method, fallback_reason = "google", None
    try:
        brief, grounded = _research_with_google(project, ai, progress)
    except ProviderError as exc:
        if not _should_fall_back(exc):
            raise
        method, fallback_reason = "wikipedia", str(exc)
        brief, grounded = _research_with_wikipedia(
            project, ai, search or WikipediaSearch(), progress
        )

    n = len(grounded.sources)
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
        "model": getattr(ai, "last_model", None),
        "method": method,
    }
    if fallback_reason:
        data["notice"] = (
            "La búsqueda de Google no estaba disponible con tu cuenta "
            f"({fallback_reason}), así que se usó Wikipedia como fuente."
        )
    if n == 0:
        data["warning"] = (
            "La búsqueda no devolvió fuentes. Todo el informe queda pendiente de verificar."
        )
    progress(100, "Informe listo")
    return data
