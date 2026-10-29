"""PANTALLA FINAL: qué vídeo tuyo poner al final para que la gente siga viendo tu canal.

YouTube premia que la gente vea otro vídeo tuyo después (más tiempo en tu canal). Sin IA ni
internet: mira tus vídeos ya publicados y propone el más parecido por tema y el que más
visitas tiene, con una frase final para el guion que invite a verlo.
"""

import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, Video, VideoStat

MIN_LETTERS = 4  # palabras con contenido (no «de», «la», «que»…)
COMMON = {"como", "para", "todo", "esta", "este", "historia", "marca", "empresa", "caida"}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9ñ]+", _plain(text)) if len(w) >= MIN_LETTERS} - COMMON


def _views(db: Session) -> dict[str, int]:
    latest = select(VideoStat.video_id, func.max(VideoStat.views)).group_by(VideoStat.video_id)
    return {video_id: views or 0 for video_id, views in db.execute(latest)}


def closing_line(title: str) -> str:
    return f"Y si quieres otra historia, te dejo aquí en pantalla «{title}». Nos vemos allí."


def suggest(db: Session, project: Project) -> list[dict]:
    """Hasta 2 vídeos para la pantalla final: el más parecido y el que más visitas tiene."""
    videos = [v for v in db.scalars(select(Video)) if v.project_id != project.id and v.title]
    if not videos:
        return []
    mine = words(f"{project.topic or ''} {project.title or ''}")
    views = _views(db)
    picks: list[dict] = []
    related = max(videos, key=lambda v: (len(mine & words(v.title)), views.get(v.video_id, 0)))
    if mine & words(related.title):
        picks.append(
            {"video": related, "reason": "Trata un tema parecido: quien vea este, querrá ver ese."}
        )
    chosen = [p["video"] for p in picks]
    others = [v for v in videos if v not in chosen]
    best = max(others, key=lambda v: views.get(v.video_id, 0)) if others else None
    if best and views.get(best.video_id, 0):
        count = f"{views[best.video_id]:,}".replace(",", ".")
        picks.append({"video": best, "reason": f"Es tu vídeo con más visitas ({count})."})
    elif not picks:  # aún sin cifras ni temas parecidos: el más reciente (con fecha)
        dated = [v for v in videos if v.published]
        if dated:
            newest = max(dated, key=lambda v: v.published)
            picks.append({"video": newest, "reason": "Es tu vídeo más reciente."})
    return [
        {
            "title": p["video"].title,
            "url": f"https://youtu.be/{p['video'].video_id}",
            "reason": p["reason"],
            "line": closing_line(p["video"].title),
        }
        for p in picks
    ]


CARD_FROM = 60  # antes del primer minuto, una tarjeta se lleva a la gente demasiado pronto
CARD_UNTIL = 0.8  # el último 20 % ya lo cubre la pantalla final
TEASER_CHARS = 30  # YouTube corta el texto de la tarjeta a unos 30 caracteres


def _teaser(title: str) -> str:
    """Texto corto para la tarjeta («Mira también…» si cabe, si no el título recortado)."""
    if len(title) <= TEASER_CHARS:
        return title
    cut = title[: TEASER_CHARS - 1].rsplit(" ", 1)[0]
    return (cut or title[: TEASER_CHARS - 1]) + "…"


def card(db: Session, project: Project, script: dict | None, voice: dict | None) -> dict | None:
    """En qué minuto poner una tarjeta de YouTube que lleve a otro vídeo tuyo: donde el
    guion habla de algo parecido a ese vídeo; si no hay nada parecido, a mitad del vídeo
    con el que más visitas tiene. None si no hay guion o vídeos tuyos publicados."""
    from app.pipeline.monetization import title_brands
    from app.pipeline.seo import format_time, paragraph_starts

    if not script or not script.get("sections"):
        return None
    videos = [v for v in db.scalars(select(Video)) if v.project_id != project.id and v.title]
    if not videos:
        return None
    starts, total = paragraph_starts(script, voice)
    texts = {p["id"]: p["text"] for section in script["sections"] for p in section["paragraphs"]}
    window = [pid for pid, t in starts.items() if CARD_FROM <= t <= total * CARD_UNTIL]
    if not window:
        return None  # vídeo demasiado corto para una tarjeta
    views = _views(db)
    best = None  # (palabras en común, visitas, párrafo, vídeo, palabras)
    for pid in window:
        mine = words(texts.get(pid, ""))
        for video in videos:
            shared = mine & words(video.title)
            # Una sola palabra en común solo vale si es el nombre del título (la marca).
            related = len(shared) >= 2 or bool(shared & set(title_brands(video.title)))
            key = (len(shared), views.get(video.video_id, 0))
            if related and (best is None or key > best[0]):
                best = (key, pid, video, shared)
    if best:
        _, pid, video, shared = best
        reason = "Ahí el guion habla de " + ", ".join(f"«{w}»" for w in sorted(shared)[:3]) + "."
    else:
        video = max(videos, key=lambda v: (views.get(v.video_id, 0), v.published or ""))
        pid = min(window, key=lambda p: abs(starts[p] - total / 2))
        reason = (
            "A mitad del vídeo, con tu vídeo que más visitas tiene."
            if views.get(video.video_id)
            else "A mitad del vídeo, con tu vídeo más reciente (aún no hay cifras de visitas)."
        )
    recorded = {t.get("paragraph_id") for t in (voice or {}).get("takes") or []}
    return {
        "time": format_time(starts[pid]),
        "exact": bool(texts) and set(texts) <= recorded,  # todos los párrafos grabados
        "title": video.title,
        "url": f"https://youtu.be/{video.video_id}",
        "teaser": _teaser(video.title),
        "reason": reason,
    }
