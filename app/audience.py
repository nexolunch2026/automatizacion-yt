"""LO QUE PIDE TU AUDIENCIA: leer los comentarios de tus vídeos y sacar ideas.

Con la clave gratuita de YouTube Data API se leen los comentarios más relevantes de los
últimos vídeos del canal. Gemini los resume en: preguntas que se repiten, temas que la
gente pide (ideas de vídeo con demanda real), lo que gusta, lo que molesta y un texto
para el comentario fijado del próximo vídeo. Además escribe borradores de respuesta para
los comentarios con más «me gusta» que aún no tienen respuesta (para copiar y pegar en
YouTube: el programa no publica nada). Se guarda el último informe.
"""

import json
from datetime import datetime

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Video
from app.settings_store import get_api_key, get_setting, set_setting

KEY = "audience_report"
API = "https://www.googleapis.com/youtube/v3/commentThreads"
VIDEOS = 10  # últimos vídeos que se leen
PER_VIDEO = 50  # comentarios por vídeo (los más relevantes)
MAX_CHARS = 280  # cada comentario, recortado
TO_ANSWER = 5  # comentarios sin respuesta para los que se escribe un borrador


class Comment(BaseModel):
    video: str
    text: str
    likes: int = 0
    video_id: str = ""
    comment_id: str = ""
    replies: int = 0  # respuestas que ya tiene


class Reply(BaseModel):
    n: int = Field(description="Número del comentario SIN RESPONDER al que contesta")
    reply: str = Field(description="El borrador de respuesta")


class Report(BaseModel):
    summary: str = Field(description="Qué dice la audiencia en 2–3 frases")
    questions: list[str] = Field(description="Hasta 5 preguntas que la gente repite")
    requests: list[str] = Field(
        description="Hasta 5 temas de vídeo que la gente pide o que encajan con lo que pide, "
        "escritos como tema de vídeo concreto"
    )
    liked: list[str] = Field(description="Hasta 3 cosas que gustan")
    complaints: list[str] = Field(description="Hasta 3 quejas o cosas a mejorar")
    pinned: str = Field(
        description="Texto para el comentario fijado del próximo vídeo: responde a la "
        "pregunta más repetida e invita a comentar con una pregunta concreta"
    )
    replies: list[Reply] = Field(
        default_factory=list,
        description="Un borrador por cada comentario de la lista SIN RESPONDER, con su "
        "número; sáltate el spam y los insultos",
    )


class NoKey(Exception):
    pass


class KeyProblem(ValueError):
    """YouTube rechaza la clave (cuota agotada, clave mala o API sin activar)."""


def _download(video_id: str, key: str, limit: int = PER_VIDEO) -> dict:
    with httpx.Client(timeout=15) as client:
        response = client.get(
            API,
            params={
                "part": "snippet",
                "videoId": video_id,
                "maxResults": limit,
                "order": "relevance",
                "textFormat": "plainText",
                "key": key,
            },
        )
    if response.status_code == 403:
        try:
            reason = response.json()["error"]["errors"][0]["reason"]
        except (ValueError, KeyError, IndexError, TypeError):
            reason = ""
        if reason == "commentsDisabled":  # ese vídeo no deja comentar
            return {"items": []}
        raise KeyProblem(
            "YouTube no deja usar tu clave ahora mismo: puede que se haya acabado la cuota "
            "de hoy o que la clave de YouTube no tenga activada la «YouTube Data API v3». "
            f"Prueba mañana o revisa la clave. (Motivo: {reason or 'desconocido'})"
        )
    response.raise_for_status()
    return response.json()


def comments_of(video_id: str, title: str, key: str) -> list[Comment]:
    data = _download(video_id, key)
    found = []
    for item in data.get("items", []):
        top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        text = " ".join(str(top.get("textDisplay", "")).split())[:MAX_CHARS]
        if text:
            found.append(
                Comment(
                    video=title,
                    text=text,
                    likes=int(top.get("likeCount", 0)),
                    video_id=video_id,
                    comment_id=str(item.get("id", "")),
                    replies=int(item.get("snippet", {}).get("totalReplyCount", 0)),
                )
            )
    return found


def collect(db: Session, key: str) -> list[Comment]:
    videos = db.scalars(select(Video).order_by(Video.published.desc()).limit(VIDEOS)).all()
    comments: list[Comment] = []
    for video in videos:
        try:
            comments += comments_of(video.video_id, video.title or video.video_id, key)
        except httpx.HTTPError:
            continue  # un vídeo que falla no para el resto
    return sorted(comments, key=lambda c: c.likes, reverse=True)


def to_answer(comments: list[Comment]) -> list[Comment]:
    """Los comentarios con más «me gusta» que aún no tienen ninguna respuesta."""
    return [c for c in comments if c.replies == 0 and c.comment_id][:TO_ANSWER]


def prompt(about: str, comments: list[Comment], pending: list[Comment] | None = None) -> str:
    lines = "\n".join(f"- [{c.video}] ({c.likes} me gusta) {c.text}" for c in comments[:300])
    answer = ""
    if pending:
        numbered = "\n".join(f"{i}. [{c.video}] {c.text}" for i, c in enumerate(pending, 1))
        answer = f"""

Comentarios SIN RESPONDER (escribe en «replies» una respuesta para cada uno, con su número):
{numbered}
Cada respuesta: 1–2 frases, cercana, en el idioma del comentario, como el creador del
canal. Da las gracias o responde la duda solo con lo que sepas de los comentarios y del
vídeo; si no sabes la respuesta, dilo con naturalidad o invita a seguir el canal. Sin
enlaces, sin inventar datos y sin pedir «suscríbete» en cada una."""
    return f"""Eres el analista de audiencia de {about}
Estos son comentarios reales de sus vídeos (los más relevantes primero):
{lines}

Resume en español qué dice la audiencia: preguntas que se repiten, temas de vídeo que
piden (o que encajan claramente con lo que piden), lo que gusta, lo que molesta, y un texto
corto y cercano para el comentario fijado del próximo vídeo. Usa solo lo que dicen los
comentarios: no inventes. Ignora el spam y los insultos.{answer}"""


def analyze(db: Session, ai, now: datetime | None = None) -> dict:
    from app import profile

    key = get_api_key(db, "youtube")
    if not key:
        raise NoKey("Hace falta la clave gratuita de YouTube para leer los comentarios.")
    comments = collect(db, key)
    if not comments:
        raise ValueError("Aún no hay comentarios en tus vídeos (o no encontré tus vídeos).")
    pending = to_answer(comments)
    report = ai.generate_json(prompt(profile.about(db), comments, pending), Report)
    # Cada borrador va con el número de su comentario: así nunca acaba debajo de otro.
    drafts = {r.n: r.reply.strip() for r in report.replies if r.reply.strip()}
    answers = [
        {
            "video": c.video,
            "text": c.text,
            "likes": c.likes,
            "reply": drafts[n],
            "url": f"https://www.youtube.com/watch?v={c.video_id}&lc={c.comment_id}",
        }
        for n, c in enumerate(pending, 1)
        if n in drafts
    ]
    data = {
        **report.model_dump(exclude={"replies"}),
        "answers": answers,
        "unanswered": len(pending),
        "comments": len(comments),
        "date": (now or datetime.now()).strftime("%d/%m/%Y %H:%M"),
    }
    set_setting(db, KEY, json.dumps(data, ensure_ascii=False))
    return data


def last_report(db: Session) -> dict | None:
    try:
        return json.loads(get_setting(db, KEY) or "null")
    except ValueError:
        return None


def ideas_hint(db: Session) -> str:
    """Los temas que pide la audiencia, para orientar las ideas de vídeo."""
    report = last_report(db)
    if not report or not report.get("requests"):
        return ""
    return "Temas que PIDE la audiencia del canal en los comentarios (prioridad): " + " | ".join(
        report["requests"][:5]
    )
