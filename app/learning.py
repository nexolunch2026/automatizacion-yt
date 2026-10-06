"""APRENDER DE UN VÍDEO: Gemini ve un vídeo de YouTube y saca lo útil para el canal.

El creador pega el enlace (en la página «Aprender» o por Telegram a JARVIS). Gemini lo ve
desde su ordenador y devuelve lo bueno, cómo aplicarlo a su canal y lo que no
conviene (por las normas de YouTube). Las lecciones marcadas con «Aplicar en mis guiones»
se tienen en cuenta al escribir los guiones nuevos.
"""

import json
import re
import secrets
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

KEY = "lessons"
MAX_LESSONS = 60
MAX_ACTIVE_RULES = 8
YOUTUBE_LINK = re.compile(
    r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/|live/|embed/)|youtu\.be/)"
    r"([\w-]{11})"
)


class Lesson(BaseModel):
    title: str = Field(description="Título del vídeo")
    channel: str = Field(description="Nombre del canal, si se ve")
    summary: str = Field(description="De qué trata, en 2–3 frases sencillas")
    good: list[str] = Field(description="Lo bueno: 3–7 consejos concretos y útiles del vídeo")
    apply: list[str] = Field(
        description="Cómo aplicarlo al canal: 2–5 acciones concretas, cada una en una frase"
    )
    careful: list[str] = Field(
        description="Lo que no conviene o es arriesgado con las normas de YouTube (o [])"
    )
    ideas: list[str] = Field(description="Ideas de vídeo para el canal que salen de aquí (o [])")


def find_link(text: str) -> str | None:
    """El enlace normalizado del primer vídeo de YouTube que haya en el texto."""
    match = YOUTUBE_LINK.search(text or "")
    return f"https://www.youtube.com/watch?v={match.group(1)}" if match else None


def prompt(about: str) -> str:
    return f"""Mira este vídeo de YouTube entero. Eres el asesor de
{about} Es principiante, con poco tiempo y presupuesto mínimo, y usa un
programa que investiga, escribe el guion, pone voz, imágenes y monta el vídeo.

Responde en español sencillo, sin jerga:
- summary: de qué trata el vídeo.
- good: lo bueno y útil, en consejos concretos (no generalidades).
- apply: cómo aplicarlo a SU canal, en acciones concretas.
- careful: lo que no conviene. Ten en cuenta que YouTube desmonetiza el «contenido no
  auténtico» (vídeos hechos en serie, sin análisis propio), que comprar suscriptores o
  visitas está prohibido y que las promesas de «monetizar en días» suelen ser engañosas.
- ideas: ideas de vídeo para el canal que se le ocurran a partir de este vídeo.
No inventes nada que no salga en el vídeo."""


def lessons(db: Session) -> list[dict]:
    try:
        return json.loads(get_setting(db, KEY) or "[]")
    except ValueError:
        return []


def _save(db: Session, items: list[dict]) -> None:
    set_setting(db, KEY, json.dumps(items[:MAX_LESSONS], ensure_ascii=False))


def learn(db: Session, url: str, ai, now: datetime | None = None) -> dict:
    """Ve el vídeo con la IA y guarda la lección (la más nueva, la primera)."""
    from app import profile

    lesson = ai.watch_video(url, prompt(profile.about(db)), Lesson)
    item = {
        "id": secrets.token_hex(4),
        "url": url,
        "date": (now or datetime.now()).strftime("%Y-%m-%d"),
        "apply_in_scripts": False,
        **lesson.model_dump(),
    }
    items = [x for x in lessons(db) if x["url"] != url]  # si se repite, se rehace
    _save(db, [item, *items])
    return item


def toggle_apply(db: Session, lesson_id: str) -> bool | None:
    items = lessons(db)
    for item in items:
        if item["id"] == lesson_id:
            item["apply_in_scripts"] = not item.get("apply_in_scripts")
            _save(db, items)
            return item["apply_in_scripts"]
    return None


def delete(db: Session, lesson_id: str) -> None:
    _save(db, [x for x in lessons(db) if x["id"] != lesson_id])


def script_rules(db: Session) -> list[str]:
    """Las acciones de las lecciones marcadas para los guiones (las más nuevas primero)."""
    rules = []
    for item in lessons(db):
        if item.get("apply_in_scripts"):
            rules += [a.strip() for a in item.get("apply", []) if a.strip()]
    return rules[:MAX_ACTIVE_RULES]


def lesson_text(item: dict) -> str:
    """La lección en texto corto (para JARVIS)."""
    parts = [f"«{item['title']}»" + (f" — {item['channel']}" if item.get("channel") else "")]
    parts.append(item["summary"])
    if item.get("good"):
        parts.append("✅ Lo bueno:\n" + "\n".join(f"• {x}" for x in item["good"][:5]))
    if item.get("apply"):
        parts.append("👉 Para tu canal:\n" + "\n".join(f"• {x}" for x in item["apply"][:4]))
    if item.get("careful"):
        parts.append("⚠️ Ojo:\n" + "\n".join(f"• {x}" for x in item["careful"][:3]))
    return "\n\n".join(parts)
