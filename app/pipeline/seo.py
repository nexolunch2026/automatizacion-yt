"""SEO ENGINE: título, descripción con capítulos y fuentes, etiquetas, hashtags y comentario
fijado, listos para copiar en YouTube.

Los capítulos se calculan con los tiempos reales de la narración (si ya está grabada) para
que coincidan con el vídeo. YouTube exige que el primero empiece en 0:00, que haya al menos
3 y que cada uno dure 10 s o más.
"""

from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import Project
from app.pipeline.context import research_summary
from app.pipeline.render import PAUSE
from app.providers.ai import AIProvider

WORDS_PER_SECOND = 2.5
MIN_CHAPTER_SECONDS = 10
DESCRIPTION_LIMIT = 5000
TAGS_LIMIT = 500


class SeoDraft(BaseModel):
    titles: list[str] = Field(description="3 títulos alternativos, máximo 70 caracteres")
    description_intro: str = Field(
        description="2–3 frases: gancho y qué descubrirá el espectador, sin relleno"
    )
    tags: list[str] = Field(description="10–15 etiquetas relevantes, sin repetir")
    hashtags: list[str] = Field(description="3 hashtags, sin espacios")
    pinned_comment: str = Field(
        description="Comentario fijado con una pregunta que invite a opinar"
    )
    category: str = Field(description="Categoría de YouTube sugerida (ej. Educación)")


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def paragraph_starts(script: dict, voice: dict | None) -> tuple[dict[str, float], float]:
    """Momento en que empieza cada párrafo en el vídeo (real si hay voz grabada) y el
    momento en que termina la narración."""
    takes = {t["paragraph_id"]: t["seconds"] for t in (voice or {}).get("takes", [])}
    starts, t = {}, 0.0
    for section in script.get("sections", []):
        for paragraph in section["paragraphs"]:
            starts[paragraph["id"]] = t
            seconds = takes.get(paragraph["id"])
            if seconds is None:
                seconds = len(paragraph["text"].split()) / WORDS_PER_SECOND
            t += seconds + PAUSE
    return starts, max(t - PAUSE, 0.0)


def build_chapters(script: dict, voice: dict | None) -> list[tuple[float, str]]:
    """Capítulos: la introducción (gancho, promesa, intro) en 0:00 y luego cada sección.
    Las secciones muy cortas se unen a la anterior; la llamada final no es capítulo."""
    starts, total = paragraph_starts(script, voice)
    chapters: list[tuple[float, str]] = []
    for section in script.get("sections", []):
        if not section["paragraphs"] or section["kind"] == "cta":
            continue
        start = starts[section["paragraphs"][0]["id"]]
        if section["kind"] in ("hook", "promise", "intro"):
            if not chapters:
                chapters.append((0.0, "Introducción"))
            continue
        title = (section.get("title") or "").strip() or "Parte"
        if chapters and start - chapters[-1][0] < MIN_CHAPTER_SECONDS:
            continue  # demasiado cerca del anterior: se queda dentro de él
        chapters.append((start, title))
    if chapters and chapters[0][0] != 0:
        chapters[0] = (0.0, chapters[0][1])
    # El último capítulo también necesita 10 s hasta el final.
    if len(chapters) > 1 and total - chapters[-1][0] < MIN_CHAPTER_SECONDS:
        chapters.pop()
    return chapters if len(chapters) >= 3 else []


def build_description(
    intro: str,
    chapters: list[tuple[float, str]],
    research: dict,
    credits: str,
    hashtags: list[str],
    has_ai_images: bool,
    voice_credit: str = "",
) -> str:
    parts = [intro.strip()]
    if chapters:
        parts.append(
            "⏱️ Capítulos\n" + "\n".join(f"{format_time(t)} {title}" for t, title in chapters)
        )
    sources = research.get("sources", [])[:10]
    if sources:
        parts.append("📚 Fuentes\n" + "\n".join(f"- {s['title']}: {s['uri']}" for s in sources))
    if credits:
        parts.append("🖼️ " + credits)
    if has_ai_images:
        parts.append("Algunas imágenes de este vídeo son ilustraciones generadas con IA.")
    if voice_credit:
        parts.append(voice_credit)
    if hashtags:
        parts.append(" ".join(hashtags))
    text = "\n\n".join(p for p in parts if p)
    return text[: DESCRIPTION_LIMIT - 1] if len(text) >= DESCRIPTION_LIMIT else text


def voice_credit(voice: dict | None) -> str:
    """El plan gratis de ElevenLabs pide citarlos. Si no se sabe el plan, se cita igual."""
    voice = voice or {}
    if voice.get("provider") == "elevenlabs" and voice.get("eleven_tier", "free") in ("free", ""):
        return "🎙️ Voz creada con ElevenLabs (elevenlabs.io)."
    return ""


def clean_tags(tags: list[str]) -> list[str]:
    """Sin repetidos, sin «#» ni comas, y dentro del límite de 500 caracteres de YouTube."""
    result, seen, total = [], set(), 0
    for tag in tags:
        tag = tag.replace("#", "").replace(",", " ").strip()
        key = tag.lower()
        if not tag or key in seen or total + len(tag) + 1 > TAGS_LIMIT:
            continue
        seen.add(key)
        result.append(tag)
        total += len(tag) + 1
    return result


def clean_hashtags(hashtags: list[str]) -> list[str]:
    result = []
    for tag in hashtags[:3]:
        word = "".join(ch for ch in tag.replace("#", "") if ch.isalnum() or ch == "_")
        if word:
            result.append(f"#{word}")
    return result


def _prompt(project: Project, script: dict, research: dict, title: str) -> str:
    sections = "\n".join(
        f"- {s.get('title', '')}: " + " ".join(p["text"] for p in s["paragraphs"])[:300]
        for s in script.get("sections", [])
    )
    return f"""Eres experto en SEO de YouTube para canales de documentales en {project.language}.
Vídeo: «{title}» (tipo {project.video_type}).

Prepara:
- 3 títulos alternativos (máx. 70 caracteres), atractivos pero honestos: nada que el vídeo
  no cumpla. No inventes cifras de visitas ni de CTR.
- Una introducción para la descripción (2–3 frases): gancho y qué descubrirá el espectador.
  Natural, sin repetir palabras clave a la fuerza.
- 10–15 etiquetas, 3 hashtags y un comentario fijado con una pregunta que invite a opinar.
- La categoría de YouTube más adecuada.
Usa solo datos que aparezcan en el guion o la investigación.

GUION (resumen por secciones):
{sections}

INVESTIGACIÓN:
{research_summary(research)[:3000]}"""


def run_seo(
    project: Project,
    script: dict,
    research: dict,
    voice: dict | None,
    credits: str,
    has_ai_images: bool,
    ai: AIProvider,
    progress: Callable[[int, str], None],
) -> dict:
    progress(20, "Preparando título, descripción y etiquetas")
    title = script.get("title") or project.title
    draft = ai.generate_json(_prompt(project, script, research, title), SeoDraft)
    chapters = build_chapters(script, voice)
    hashtags = clean_hashtags(draft.hashtags)
    titles = [title] + [t.strip() for t in draft.titles if t.strip() and t.strip() != title]
    progress(100, "Textos de publicación listos")
    return {
        "titles": [t[:100] for t in titles[:4]],
        "description": build_description(
            draft.description_intro,
            chapters,
            research,
            credits,
            hashtags,
            has_ai_images,
            voice_credit(voice),
        ),
        "chapters": [{"time": format_time(t), "title": name} for t, name in chapters],
        "chapters_exact": bool(voice),
        "tags": clean_tags(draft.tags),
        "hashtags": hashtags,
        "pinned_comment": draft.pinned_comment.strip(),
        "category": draft.category.strip(),
    }
