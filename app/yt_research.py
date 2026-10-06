"""«INVESTIGAR EN YOUTUBE»: busca vídeos sobre un tema, los ve con Gemini y lo resume.

1. Busca los vídeos (4–20 min, los más relevantes): con la clave de YouTube si la hay; si
   no, en la página pública de búsqueda; y si eso falla, con la búsqueda de Google de
   Gemini. Cada vídeo se comprueba (oEmbed) para no ver enlaces inventados.
2. Gemini ve cada vídeo y guarda una lección en «🎓 Aprender» (como al pegar un enlace).
3. Junta todas las lecciones en un informe: lo que repiten los que saben, qué hacer en el
   canal, lo que no conviene e ideas de vídeo.

Va por detrás (lo hace el trabajador del programa cuando no hay otras tareas) porque ver
varios vídeos tarda unos minutos. JARVIS avisa por Telegram al terminar.
"""

import html
import json
import logging
import re
import secrets
from collections.abc import Callable
from datetime import datetime

import httpx
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import learning
from app.providers.ai import ProviderError
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

KEY = "yt_research"
MAX_REPORTS = 20
DEFAULT_COUNT = 3
MAX_COUNT = 5
SUGGESTED = [
    "cómo crear un canal faceless de documentales",
    "monetizar un canal faceless en YouTube",
    "guiones para documentales de YouTube que retienen",
    "edición de vídeos faceless con IA",
    "Shorts faceless que consiguen suscriptores",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}
VIDEO_FILTER = "EgQQARgD"  # en la búsqueda de YouTube: solo vídeos de 4 a 20 minutos
RENDERER = re.compile(r'"videoRenderer":\{"videoId":"([\w-]{11})"')
TEXT = r'"((?:[^"\\]|\\.)*)"'
ID = re.compile(r"^[\w-]{11}$")


class Report(BaseModel):
    summary: str = Field(description="Qué se aprende de estos vídeos, en 3–4 frases sencillas")
    top_tips: list[str] = Field(
        description="Los 4–8 consejos más útiles, sobre todo los que repiten varios vídeos"
    )
    apply: list[str] = Field(description="3–6 acciones concretas para el canal, en orden")
    careful: list[str] = Field(description="Lo que no conviene o es arriesgado (o [])")
    ideas: list[str] = Field(description="Ideas de vídeo para el canal (o [])")


# ---------------------------------------------------------------- guardar


def reports(db: Session) -> list[dict]:
    try:
        return json.loads(get_setting(db, KEY) or "[]")
    except ValueError:
        return []


def _save(db: Session, items: list[dict]) -> None:
    set_setting(db, KEY, json.dumps(items[:MAX_REPORTS], ensure_ascii=False))


def _update(db: Session, report_id: str, **changes) -> dict | None:
    items = reports(db)
    for item in items:
        if item["id"] == report_id:
            item.update(changes)
            _save(db, items)
            return item
    return None


def queue(db: Session, topic: str, count: int = DEFAULT_COUNT) -> dict:
    """Apunta la investigación; el trabajador la hace en cuanto puede."""
    topic = " ".join(topic.split())[:120]
    if not topic:
        raise ValueError("Falta el tema")
    item = {
        "id": secrets.token_hex(4),
        "topic": topic,
        "count": max(1, min(int(count), MAX_COUNT)),
        "status": "queued",
        "message": "En cola",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "videos": [],
    }
    _save(db, [item, *reports(db)])
    return item


def busy(db: Session) -> bool:
    return any(r["status"] in ("queued", "working") for r in reports(db))


def delete(db: Session, report_id: str) -> None:
    _save(db, [r for r in reports(db) if r["id"] != report_id])


def recover_interrupted(db: Session) -> None:
    """Si el programa se cerró a medias, se vuelve a empezar."""
    items = reports(db)
    for item in items:
        if item["status"] == "working":
            item.update(status="queued", message="Reanudando tras un cierre")
    _save(db, items)


# ---------------------------------------------------------------- buscar


def _get(url: str, **params) -> httpx.Response:
    with httpx.Client(timeout=15, headers=HEADERS, follow_redirects=True) as client:
        r = client.get(url, params=params or None)
        r.raise_for_status()
        return r


def _unquote(text: str) -> str:
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text


def parse_search_page(page: str, limit: int) -> list[dict]:
    """Vídeos de la página de resultados de YouTube (sin clave)."""
    found: list[dict] = []
    for match in RENDERER.finditer(page):
        vid = match.group(1)
        if any(v["id"] == vid for v in found):
            continue
        chunk = page[match.end() : match.end() + 8000]
        title = re.search(r'"title":\{"runs":\[\{"text":' + TEXT, chunk)
        channel = re.search(r'"ownerText":\{"runs":\[\{"text":' + TEXT, chunk)
        length = re.search(r'"lengthText":\{.{0,300}?"simpleText":' + TEXT, chunk)
        found.append(
            {
                "id": vid,
                "title": _unquote(title.group(1)) if title else "",
                "channel": _unquote(channel.group(1)) if channel else "",
                "length": length.group(1) if length else "",
            }
        )
        if len(found) >= limit:
            break
    return found


def search_api(topic: str, key: str, limit: int) -> list[dict]:
    data = _get(
        "https://www.googleapis.com/youtube/v3/search",
        part="snippet",
        q=topic,
        type="video",
        videoDuration="medium",
        relevanceLanguage="es",
        maxResults=limit,
        key=key,
    ).json()
    return [
        {
            "id": item["id"]["videoId"],
            "title": html.unescape(item["snippet"]["title"]),
            "channel": html.unescape(item["snippet"]["channelTitle"]),
            "length": "",
        }
        for item in data.get("items", [])
    ]


def search_page(topic: str, limit: int) -> list[dict]:
    page = _get(
        "https://www.youtube.com/results", search_query=topic, sp=VIDEO_FILTER, hl="es"
    ).text
    return parse_search_page(page, limit)


def oembed(video_id: str) -> dict | None:
    """Título y canal del vídeo; None si no existe o no es público."""
    try:
        data = _get(
            "https://www.youtube.com/oembed",
            url=f"https://www.youtube.com/watch?v={video_id}",
            format="json",
        ).json()
    except (httpx.HTTPError, ValueError):
        return None
    return {"id": video_id, "title": data.get("title", ""), "channel": data.get("author_name", "")}


def search_with_ai(topic: str, ai, limit: int) -> list[dict]:
    """Último recurso: la búsqueda de Google de Gemini. Se comprueba cada enlace."""
    answer = ai.grounded_research(
        f"Busca en YouTube {limit + 3} vídeos útiles y recientes (de 4 a 20 minutos, mejor "
        f"en español) sobre: {topic}. Devuelve SOLO la lista de enlaces completos de "
        "YouTube (https://www.youtube.com/watch?v=…), uno por línea. No inventes enlaces."
    )
    text = answer.text + " " + " ".join(s.url for s in answer.sources)
    found: list[dict] = []
    for match in learning.YOUTUBE_LINK.finditer(text):
        vid = match.group(1)
        if any(v["id"] == vid for v in found):
            continue
        info = oembed(vid)
        if info:
            found.append({**info, "length": ""})
        if len(found) >= limit:
            break
    return found


def find_videos(db: Session, topic: str, ai, limit: int) -> list[dict]:
    attempts: list[tuple[str, Callable[[], list[dict]]]] = []
    key = get_api_key(db, "youtube")
    if key:
        attempts.append(("API de YouTube", lambda: search_api(topic, key, limit)))
    attempts.append(("búsqueda de YouTube", lambda: search_page(topic, limit)))
    attempts.append(("búsqueda de Google", lambda: search_with_ai(topic, ai, limit)))
    for name, attempt in attempts:
        try:
            found = [v for v in attempt() if ID.match(v.get("id", ""))]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, ProviderError) as exc:
            log.warning("Investigar en YouTube: falló la %s: %s", name, exc)
            continue
        if found:
            return found[:limit]
    return []


# ---------------------------------------------------------------- investigar


def report_prompt(topic: str, items: list[dict]) -> str:
    notes = "\n\n".join(
        f"VÍDEO {i}: «{x['title']}» ({x.get('channel', '')})\n{x['summary']}\n"
        + "\n".join(f"- {g}" for g in x.get("good", []) + x.get("apply", []))
        + ("\nOjo: " + "; ".join(x["careful"]) if x.get("careful") else "")
        for i, x in enumerate(items, 1)
    )
    return f"""Eres el asesor de «Anatomía De Una Marca», un canal de YouTube en español sin
rostro (faceless) de documentales sobre marcas que suben y caen. Lo lleva Simón,
principiante, con poco tiempo y presupuesto mínimo.

Ha investigado en YouTube: «{topic}». Estas son las notas de cada vídeo visto:

{notes}

Junta todo en un informe en español sencillo. Da más peso a lo que repiten varios vídeos.
Ten en cuenta que YouTube no monetiza el «contenido no auténtico» (vídeos en serie sin
aportación propia) y que las promesas de dinero rápido suelen ser engañosas.
No inventes nada que no esté en las notas."""


def run(db: Session, report_id: str, ai) -> dict:
    """Busca, ve los vídeos y escribe el informe. Devuelve el informe guardado."""
    item = _update(db, report_id, status="working", message="Buscando vídeos en YouTube")
    if item is None:
        raise ValueError("Esa investigación ya no existe")
    found = find_videos(db, item["topic"], ai, item["count"])
    if not found:
        raise ProviderError("No encontré vídeos sobre eso en YouTube. Prueba con otras palabras.")
    known = {x["url"]: x for x in learning.lessons(db)}
    watched, videos = [], []
    for i, video in enumerate(found, 1):
        url = f"https://www.youtube.com/watch?v={video['id']}"
        _update(db, report_id, message=f"Viendo el vídeo {i} de {len(found)}: {video['title']}")
        try:
            lesson = known.get(url) or learning.learn(db, url, ai)
        except ProviderError as exc:
            if exc.transient and not watched:
                raise
            log.warning("No se pudo ver %s: %s", url, exc)
            videos.append({**video, "url": url, "lesson_id": None})
            continue
        watched.append(lesson)
        videos.append({**video, "url": url, "lesson_id": lesson["id"]})
    if not watched:
        raise ProviderError("No pude ver ninguno de los vídeos encontrados. Prueba más tarde.")
    _update(db, report_id, message="Escribiendo el informe", videos=videos)
    report = ai.generate_json(report_prompt(item["topic"], watched), Report)
    return _update(
        db,
        report_id,
        status="done",
        message="Terminado",
        videos=videos,
        finished=datetime.now().strftime("%Y-%m-%d %H:%M"),
        **report.model_dump(),
    )


def process_next(db: Session, get_ai: Callable[[Session], object]) -> bool:
    """Para el trabajador: hace la siguiente investigación pendiente (si hay)."""
    pending = [r for r in reports(db) if r["status"] == "queued"]
    if not pending:
        return False
    item = pending[-1]  # la más antigua primero
    try:
        run(db, item["id"], get_ai(db))
    except ProviderError as exc:
        _update(db, item["id"], status="failed", message=str(exc))
    except Exception as exc:  # noqa: BLE001 — debe quedar registrado y no repetirse sin fin
        log.exception("Fallo inesperado investigando en YouTube")
        _update(db, item["id"], status="failed", message=f"Error inesperado: {exc}")
    return True


def unnotified(db: Session) -> list[dict]:
    """Investigaciones terminadas (o fallidas) que JARVIS aún no ha contado."""
    items = reports(db)
    done = [r for r in items if r["status"] in ("done", "failed") and not r.get("notified")]
    if done:
        for r in done:
            r["notified"] = True
        _save(db, items)
    return done


def report_text(item: dict) -> str:
    if item["status"] == "failed":
        return f"No pude terminar la investigación «{item['topic']}»: {item['message']}"
    seen = [v for v in item.get("videos", []) if v.get("lesson_id")]
    parts = [f"Investigué «{item['topic']}» viendo {len(seen)} vídeos de YouTube.", item["summary"]]
    if item.get("top_tips"):
        parts.append(
            "✅ Lo que más se repite:\n" + "\n".join(f"• {x}" for x in item["top_tips"][:6])
        )
    if item.get("apply"):
        parts.append("👉 Para tu canal:\n" + "\n".join(f"• {x}" for x in item["apply"][:5]))
    if item.get("careful"):
        parts.append("⚠️ Ojo:\n" + "\n".join(f"• {x}" for x in item["careful"][:3]))
    if seen:
        parts.append("🎬 Vídeos vistos:\n" + "\n".join(f"• {v['title']}" for v in seen))
    return "\n\n".join(parts)
