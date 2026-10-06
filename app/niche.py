"""FICHA DEL NICHO: lo que hace distinto a cada canal, para que sirva cualquier nicho.

Cada canal tiene su nicho (el del canal o, si está vacío, el del perfil). La ficha dice
cómo son sus vídeos, para quién, con qué tono, qué estructuras de guion le van, cuál es su
sección final fija, cómo deben ser sus títulos y miniaturas, qué noticias le sirven de
ideas y qué riesgos tiene con la monetización.

- Canales de marcas y empresas: la ficha de siempre (escrita a mano, sin gastar IA).
- Cualquier otro nicho: Gemini la crea UNA vez y se guarda. Si no hay Gemini, se usa una
  ficha general que vale para cualquier documental o vídeo narrado.
"""

import json
import logging
import re
import unicodedata

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

KEY = "niche_kit:{}"


class Structure(BaseModel):
    key: str = ""
    name: str = Field(description="Nombre corto de la estructura, p. ej. «Cronológica»")
    guide: str = Field(description="Cómo se cuenta el vídeo con esta estructura, 1–2 frases")


class Kit(BaseModel):
    niche: str = ""
    video_format: str = Field(
        description="Cómo son los vídeos de este nicho (documental narrado, lista o top, "
        "explicación, relato…), en una frase"
    )
    audience: str = Field(description="Para quién son, en una frase")
    tone: str = Field(description="Tono de la narración, en una frase")
    structures: list[Structure] = Field(
        description="4 o 5 estructuras de guion DISTINTAS que funcionan en este nicho"
    )
    closing_name: str = Field(
        description="Nombre de la sección fija con la que acaban todos los vídeos del canal "
        "(su firma), p. ej. «La lección de la marca», «Lo que nadie te cuenta»"
    )
    closing_guide: str = Field(description="Qué se dice en esa sección final, en 1–2 frases")
    title_tips: list[str] = Field(description="3–5 consejos de títulos que funcionan en el nicho")
    thumbnail_tips: list[str] = Field(description="2–3 consejos de miniaturas para el nicho")
    idea_formats: list[str] = Field(description="5–6 formatos de vídeo distintos para el nicho")
    news_query: str = Field(
        description="Búsqueda para Google Noticias que encuentre noticias que sirvan de ideas "
        "de vídeo en este nicho (palabras clave con OR)"
    )
    fact_topic: str = Field(
        description="Sobre qué contar un «dato curioso del día», en 5–10 palabras"
    )
    avoid: list[str] = Field(
        description="2–4 riesgos de este nicho con las normas de YouTube o los anunciantes"
    )


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(ch for ch in plain if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:30] or "estructura"


def _brand_kit() -> Kit:
    from app.pipeline.script import STRUCTURES

    return Kit(
        niche="marcas y empresas",
        video_format="Documental narrado sobre la historia de una marca o empresa",
        audience="Curiosos de los negocios y las historias de empresas, de 18 a 45 años",
        tone="Documental, con tensión y análisis propio, apto para anunciantes",
        structures=[Structure(key=k, name=n, guide=g) for k, (n, g) in STRUCTURES.items()],
        closing_name="La lección de la marca",
        closing_guide="Una idea práctica y propia que el espectador pueda aplicar.",
        title_tips=[
            "60 caracteres como mucho, con la marca y lo más intrigante al principio",
            "Crea una pregunta en la cabeza, no la respondas",
        ],
        thumbnail_tips=[
            "El texto (2–4 palabras) añade algo que el título no dice; nunca lo repite",
            "Muestra la emoción o el resultado",
        ],
        idea_formats=[
            "ascenso y caída",
            "«los 5 errores»",
            "rivalidad entre dos marcas",
            "el juicio o escándalo",
            "«qué habría pasado si»",
            "la resurrección",
        ],
        news_query='(quiebra OR "cierra tiendas" OR despidos OR crisis OR "en bancarrota" OR '
        '"deja de vender" OR "pierde mercado") empresa marca',
        fact_topic="la historia de una marca o empresa conocida",
        avoid=["Nada de afirmar delitos no probados: presenta lo discutido como discutido"],
    )


def _general_kit(niche: str) -> Kit:
    return Kit(
        niche=niche,
        video_format=f"Vídeo narrado sin rostro sobre {niche}",
        audience=f"Gente curiosa interesada en {niche}",
        tone="Cercano y claro, con ritmo y algo de misterio, apto para anunciantes",
        structures=[
            Structure(
                key="cronologia",
                name="Cronológica",
                guide="Cuenta la historia en orden, deteniéndote en el momento que lo cambió todo.",
            ),
            Structure(
                key="lista",
                name="Lista / top",
                guide="Cada sección de desarrollo es un punto de la lista, de menos a más "
                "sorprendente; el clímax es el número uno.",
            ),
            Structure(
                key="pregunta",
                name="La gran pregunta",
                guide="Plantea una pregunta al principio, recorre las posibles respuestas y "
                "revela la mejor en el clímax.",
            ),
            Structure(
                key="investigacion",
                name="Investigación",
                guide="Empieza por el final sorprendente y reconstruye, como un detective, "
                "cómo se llegó hasta ahí.",
            ),
            Structure(
                key="antes_despues",
                name="Antes y después",
                guide="Cómo era al principio, qué lo transformó y cómo quedó; el giro es el "
                "momento del cambio.",
            ),
        ],
        closing_name="La idea clave",
        closing_guide="Resume en una idea propia y útil lo que el espectador se lleva.",
        title_tips=[
            "60 caracteres como mucho, con lo más intrigante al principio",
            "Crea una pregunta en la cabeza, no la respondas",
            "Honesto: nada que el vídeo no cumpla",
        ],
        thumbnail_tips=[
            "El texto (2–4 palabras) añade algo que el título no dice; nunca lo repite",
            "Una sola imagen clara con emoción o contraste",
        ],
        idea_formats=[
            "historia completa",
            "top o lista",
            "misterio sin resolver",
            "«qué habría pasado si»",
            "explicación de un fenómeno",
            "antes y después",
        ],
        news_query=niche,
        fact_topic=niche,
        avoid=["Lenguaje apto para anunciantes: sin palabrotas ni detalles gráficos"],
    )


def is_brands(niche: str) -> bool:
    plain = slug(niche)
    return "marca" in plain or "empresa" in plain


def niche_of(db: Session, channel) -> str:
    from app import profile

    return (getattr(channel, "niche", "") or "").strip() or profile.get(db)["niche"]


def _stored(db: Session, channel) -> Kit | None:
    if channel is None:
        return None
    try:
        data = json.loads(get_setting(db, KEY.format(channel.id)) or "null")
        return Kit.model_validate(data) if data else None
    except ValueError:
        return None


def kit_for(db: Session, channel) -> Kit:
    """La ficha del canal (sin gastar IA): la guardada, la de marcas o la general."""
    niche = niche_of(db, channel)
    stored = _stored(db, channel)
    if stored and stored.niche == niche:
        return stored
    if is_brands(niche):
        return _brand_kit().model_copy(update={"niche": niche})
    return _general_kit(niche)


def has_own_kit(db: Session, channel) -> bool:
    stored = _stored(db, channel)
    return bool(stored and stored.niche == niche_of(db, channel))


def prompt(niche: str, language: str) -> str:
    return f"""Eres experto en canales de YouTube sin rostro (faceless) que monetizan.
Un creador principiante va a empezar un canal sobre: «{niche}», en {language}.
Los vídeos los hace un programa: investiga con fuentes, escribe un guion narrado, pone voz,
imágenes y lo monta (de 8 a 20 minutos, y Shorts).

Crea la FICHA DEL NICHO en español: cómo deben ser sus vídeos, para quién, el tono, 4 o 5
estructuras de guion distintas que funcionen en este nicho (para que el canal no parezca
hecho en serie: YouTube no monetiza el «contenido no auténtico»), la sección final fija
que será la firma del canal, consejos de títulos y miniaturas, formatos de vídeo, una
búsqueda de noticias que dé ideas, el tema del dato curioso y los riesgos del nicho con
las normas de YouTube y los anunciantes. Concreto y realista, sin promesas de dinero."""


def generate(db: Session, channel, ai) -> Kit:
    """Gemini crea la ficha del nicho del canal y se guarda (una vez por nicho)."""
    niche = niche_of(db, channel)
    language = getattr(channel, "language", "") or "Español"
    kit = ai.generate_json(prompt(niche, language), Kit)
    seen: set[str] = set()
    structures = []
    for s in kit.structures[:6]:
        if not s.name.strip() or not s.guide.strip():
            continue
        key = slug(s.name)
        while key in seen:
            key += "_2"
        seen.add(key)
        structures.append(s.model_copy(update={"key": key}))
    if len(structures) < 2:  # una ficha sin estructuras útiles no sirve
        structures = _general_kit(niche).structures
    kit = kit.model_copy(update={"niche": niche, "structures": structures})
    set_setting(db, KEY.format(channel.id), kit.model_dump_json())
    return kit


def ensure(db: Session, channel, ai) -> Kit:
    """La ficha del canal; si es un nicho nuevo (no de marcas), la crea con la IA.
    Si la IA falla, la general: nunca para la producción del vídeo."""
    from app.providers.ai import ProviderError

    if channel is None or has_own_kit(db, channel) or is_brands(niche_of(db, channel)):
        return kit_for(db, channel)
    try:
        return generate(db, channel, ai)
    except ProviderError:
        return kit_for(db, channel)
    except Exception:  # noqa: BLE001 — una ficha rara no puede parar un vídeo
        log.exception("No se pudo crear la ficha del nicho")
        return kit_for(db, channel)


def structure(kit: Kit, key: str) -> Structure | None:
    return next((s for s in kit.structures if s.key == key), None)


def strategy_tips(kit: Kit) -> str:
    lines = [f"Lo que funciona en este nicho ({kit.niche}): {kit.video_format}."]
    lines += [f"- Títulos: {t}" for t in kit.title_tips]
    lines += [f"- Miniatura: {t}" for t in kit.thumbnail_tips]
    lines.append("- El gancho entra directo en el momento de más tensión, sin presentaciones.")
    return "\n".join(lines)


def script_notes(kit: Kit) -> str:
    lines = [f"Nicho del canal: {kit.niche}. Público: {kit.audience}. Tono: {kit.tone}."]
    if kit.avoid:
        lines.append("Cuidado en este nicho: " + "; ".join(kit.avoid))
    return "\n".join(lines)


def closing_guide(kit: Kit) -> str:
    return (
        f"Cierra con la sección fija del canal, «{kit.closing_name}»: {kit.closing_guide} "
        "(es la firma del canal)."
    )


def main_channel(db: Session):
    """El canal con el que se trabaja: el del último vídeo o, si no, el primero."""
    from sqlalchemy import select

    from app.models import Channel, Project

    last = db.scalar(select(Project).order_by(Project.id.desc()).limit(1))
    if last:
        return last.channel
    return db.scalar(select(Channel).order_by(Channel.id).limit(1))


def main_kit(db: Session) -> Kit:
    """La ficha del canal principal (o la del perfil si aún no hay canales)."""
    return kit_for(db, main_channel(db))
