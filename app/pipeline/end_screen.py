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
