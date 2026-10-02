"""SCRIPT ENGINE: escribe el guion y permite reescribir párrafos sueltos."""

import time
import uuid
from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import WORDS_BY_DURATION, Project
from app.pipeline.context import research_summary
from app.providers.ai import AIProvider, ProviderError

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


class OutlineSection(BaseModel):
    title: str
    key_points: list[str] = Field(description="2–4 ideas o datos que cubrirá esta sección")


class Outline(BaseModel):
    sections: list[OutlineSection]


class SectionDraft(BaseModel):
    paragraphs: list[Paragraph]


# Reparto del total de palabras entre las partes del guion.
SHARES = {
    "hook": 0.04,
    "promise": 0.04,
    "intro": 0.08,
    "development": 0.62,  # se reparte entre varias secciones de desarrollo
    "climax": 0.12,
    "conclusion": 0.07,
    "cta": 0.03,
}
DEVELOPMENT_SECTIONS = {"3–5 min": 2, "5–10 min": 3, "10–15 min": 4, "15–30 min": 6}
MIN_SHARE_OK = 0.75  # si una sección queda por debajo del 75 % de su objetivo, se alarga
SLEEP = time.sleep  # se reemplaza en los tests


def plan_sections(duration: str) -> list[dict]:
    """Lista de secciones con su objetivo de palabras según la duración del vídeo."""
    total = WORDS_BY_DURATION.get(duration, 1100)
    if duration == "Short":
        return [
            {"kind": "hook", "words": round(total * 0.2)},
            {"kind": "development", "words": round(total * 0.65)},
            {"kind": "cta", "words": max(round(total * 0.15), 10)},
        ]
    dev = DEVELOPMENT_SECTIONS.get(duration, 3)
    plan = []
    for kind, share in SHARES.items():
        if kind == "development":
            plan += [{"kind": kind, "words": round(total * share / dev)} for _ in range(dev)]
        else:
            plan.append({"kind": kind, "words": max(round(total * share), 15)})
    return plan


def _brief(project: Project, concept: dict, title: str, params: dict) -> str:
    return f"""Vídeo de YouTube faceless en {project.language}, tipo «{project.video_type}».
Título: {title}
Enfoque: {concept["angle"]} — {concept["summary"]}
Promesa al espectador: {concept["promise"]}
Gancho sugerido: {concept["hook"]}
Audiencia: {concept["audience"]}
{_style(params)}"""


RULES = """Reglas:
- Solo texto para narrar en voz alta: sin acotaciones, sin «[música]», sin emojis.
- Frases claras y con ritmo; párrafos de 2–4 frases.
- Usa SOLO datos de la investigación y pon en «sources» los números entre corchetes de
  los datos que uses. Lo controvertido, preséntalo como discutido. Lo no verificado, no
  lo afirmes.
- Nada de relleno ni de repetir lo ya contado."""


def _outline_prompt(brief: str, plan: list[dict], research: dict) -> str:
    slots = "\n".join(
        f"{i}. {SECTION_LABELS[p['kind']]} (~{p['words']} palabras)" for i, p in enumerate(plan, 1)
    )
    return f"""{brief}

Haz el ESQUEMA del guion. Tiene exactamente {len(plan)} secciones, en este orden:
{slots}

Para cada sección da un título corto y 2–4 ideas o datos de la investigación que
cubrirá. Las secciones de desarrollo deben tratar aspectos distintos, sin repetirse, y
avanzar hacia el clímax.

INVESTIGACIÓN:
{research_summary(research)}"""


def _section_prompt(
    brief: str, outline: list[dict], index: int, previous_text: str, research: dict
) -> str:
    section = outline[index]
    overview = "\n".join(
        f"{'→ ' if i == index else '   '}{i + 1}. {s['label']}: {s['title']}"
        for i, s in enumerate(outline)
    )
    paragraphs = max(1, round(section["words"] / 60))
    return f"""{brief}

Estás escribiendo el guion por partes. Esquema completo (la flecha marca la parte actual):
{overview}

ESCRIBE AHORA SOLO la sección {index + 1}: «{section["label"]}: {section["title"]}».
Ideas a cubrir: {"; ".join(section["key_points"])}
Extensión: unas {section["words"]} palabras (unos {paragraphs} párrafos). Es importante
llegar a esa extensión con contenido real de la investigación.

Lo último que se ha narrado (continúa desde ahí, sin repetirlo):
{previous_text or "(es el comienzo del vídeo)"}

{RULES}

INVESTIGACIÓN:
{research_summary(research)}"""


def _expand_prompt(brief: str, section: dict, draft: list[dict], research: dict) -> str:
    current = "\n\n".join(p["text"] for p in draft)
    words = sum(len(p["text"].split()) for p in draft)
    return f"""{brief}

Esta sección del guion («{section["label"]}: {section["title"]}») tiene {words} palabras y
debería tener unas {section["words"]}. Reescríbela completa con esa extensión, añadiendo
detalles, contexto y datos de la investigación (sin inventar ni repetir).

TEXTO ACTUAL:
{current}

{RULES}

INVESTIGACIÓN:
{research_summary(research)}"""


def _with_retries(fn, attempts: int = 3, wait_seconds: float = 20):
    """Reintenta dentro de la misma tarea los errores temporales (límite por minuto…),
    para no perder las secciones ya escritas."""
    for attempt in range(attempts):
        try:
            return fn()
        except ProviderError as exc:
            if not exc.transient or attempt == attempts - 1:
                raise
            SLEEP(wait_seconds * (attempt + 1))
    raise AssertionError("inalcanzable")


def _valid_sources(sources: list[int], n_sources: int) -> list[int]:
    return sorted({n for n in sources if 1 <= n <= n_sources})


def _paragraphs(draft: SectionDraft, n_sources: int) -> list[dict]:
    return [
        {
            "id": uuid.uuid4().hex[:8],
            "text": p.text.strip(),
            "sources": _valid_sources(p.sources, n_sources),
        }
        for p in draft.paragraphs
        if p.text.strip()
    ]


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
    """Escribe el guion en dos pasos: un esquema con objetivo de palabras por sección y
    luego cada sección por separado (alargándola si se queda corta). Así los modelos
    rápidos llegan a la duración pedida."""
    selected = strategy["selected"]
    concept = strategy["concepts"][selected["concept"]]
    title = concept["titles"][selected.get("title", 0)]["title"]
    brief = _brief(project, concept, title, params)
    n_sources = len(research.get("sources", []))
    plan = plan_sections(project.duration)

    progress(8, "Preparando el esquema del guion")
    outline_result = _with_retries(
        lambda: ai.generate_json(_outline_prompt(brief, plan, research), Outline)
    )
    outline = []
    for i, slot in enumerate(plan):
        item = outline_result.sections[i] if i < len(outline_result.sections) else None
        outline.append(
            {
                **slot,
                "label": SECTION_LABELS[slot["kind"]],
                "title": (item.title if item else "") or SECTION_LABELS[slot["kind"]],
                "key_points": (item.key_points if item else []) or ["continúa la historia"],
            }
        )

    sections, previous_text = [], ""
    for i, section in enumerate(outline):
        progress(
            round(12 + 85 * i / len(outline)),
            f"Escribiendo la sección {i + 1} de {len(outline)}: {section['label']}",
        )
        prompt = _section_prompt(brief, outline, i, previous_text, research)
        draft = _paragraphs(
            _with_retries(lambda p=prompt: ai.generate_json(p, SectionDraft)), n_sources
        )
        words = sum(len(p["text"].split()) for p in draft)
        if draft and words < section["words"] * MIN_SHARE_OK:
            prompt = _expand_prompt(brief, section, draft, research)
            longer = _paragraphs(
                _with_retries(lambda p=prompt: ai.generate_json(p, SectionDraft)), n_sources
            )
            if sum(len(p["text"].split()) for p in longer) > words:
                draft = longer
        sections.append({"kind": section["kind"], "title": section["title"], "paragraphs": draft})
        previous_text = "\n\n".join(p["text"] for p in draft[-2:]) or previous_text

    progress(100, "Guion listo")
    data = {
        "title": title,
        "sections": sections,
        "params": params,
        "based_on": {"concept": selected["concept"], "title": selected.get("title", 0)},
        "target_words": WORDS_BY_DURATION.get(project.duration, 1100),
    }
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
