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


def brand_shared(shared: set[str], title: str) -> bool:
    """¿Alguna de las palabras en común es el nombre del título (la marca)? Se comparan
    escritas igual que `words` («Cañas» → «canas»)."""
    from app.pipeline.monetization import title_brands

    return bool(shared & {_plain(b) for b in title_brands(title)})


def _views(db: Session) -> dict[str, int]:
    latest = select(VideoStat.video_id, func.max(VideoStat.views)).group_by(VideoStat.video_id)
    return {video_id: views or 0 for video_id, views in db.execute(latest)}


RELATED_MAX = 3  # enlaces a otros vídeos del canal en la descripción
RELATED_FRESH_DAYS = 14  # solo vídeos que YouTube devolvió hace poco (no privados ni borrados)


def _short_titles(db: Session) -> set[str]:
    """Los títulos (normalizados) de todos los Shorts que ha preparado el programa."""
    from app.models import StageResult

    titles = set()
    for row in db.scalars(select(StageResult).where(StageResult.stage == "shorts")):
        for short in (row.data or {}).get("shorts") or []:
            if isinstance(short, dict) and short.get("title"):
                titles.add(_plain(str(short["title"])).strip())
    return titles


def _is_short_title(title: str, short_titles: set[str]) -> bool:
    plain = _plain(title).strip()
    # YouTube puede recortar el título: basta con que uno empiece por el otro (si es largo).
    return any(
        plain == t
        or (min(len(plain), len(t)) >= 20 and (plain.startswith(t) or t.startswith(plain)))
        for t in short_titles
    )


def channel_long_videos(db: Session, project: Project) -> list[Video]:
    """Los vídeos largos publicados del mismo canal (sin este proyecto, sin Shorts y sin
    los que YouTube ya no muestra). Los que aún no están enlazados a un proyecto solo
    cuentan si hay un único canal."""
    from datetime import datetime, timedelta

    from app.models import Channel

    single = db.scalar(select(func.count()).select_from(Channel)) == 1
    projects = list(db.scalars(select(Project)))
    channel_of = {p.id: p.channel_id for p in projects}
    short_projects = {p.id for p in projects if p.duration == "Short"}
    # Un vídeo que YouTube ya no devuelve (privado, borrado) deja de tener fotos nuevas.
    latest = select(VideoStat.video_id, func.max(VideoStat.taken_at)).group_by(VideoStat.video_id)
    last_seen = {video_id: taken for video_id, taken in db.execute(latest)}
    # Los Shorts que hizo el programa no llevan «#shorts» en el título: se reconocen por él.
    short_titles = _short_titles(db)
    fresh_from = datetime.now() - timedelta(days=RELATED_FRESH_DAYS)
    videos = []
    for v in db.scalars(select(Video)):
        if not v.title or v.project_id == project.id or "#short" in v.title.lower():
            continue
        if v.project_id in short_projects or _is_short_title(v.title, short_titles):
            continue  # un Short, aunque su título no lo diga
        seen = last_seen.get(v.video_id)
        if seen is None or seen < fresh_from:
            continue
        # Sin proyecto no se sabe su canal: solo cuenta si hay uno (aproximación).
        same = channel_of.get(v.project_id) == project.channel_id if v.project_id else single
        if same:
            videos.append(v)
    return videos


def related_links(db: Session, project: Project, limit: int = RELATED_MAX) -> list[dict]:
    """Otros vídeos largos del mismo canal para la descripción («Más historias del canal»):
    primero los que tratan un tema parecido y luego los más vistos. Sin Shorts. Los vídeos
    que aún no están enlazados a un proyecto solo cuentan si hay un único canal."""
    videos = channel_long_videos(db, project)
    mine = words(f"{project.topic or ''} {project.title or ''}")
    views = _views(db)
    videos.sort(
        key=lambda v: (len(mine & words(v.title)), views.get(v.video_id, 0), v.published or ""),
        reverse=True,
    )
    return [{"title": v.title, "url": f"https://youtu.be/{v.video_id}"} for v in videos[:limit]]


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
            related = len(shared) >= 2 or brand_shared(shared, video.title)
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
