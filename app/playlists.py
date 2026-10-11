"""LISTAS DE REPRODUCCIÓN: agrupar tus vídeos para que la gente vea varios seguidos.

Una lista bien hecha hace que YouTube reproduzca tu siguiente vídeo solo, y eso suma
tiempo de visionado (lo que cuenta para monetizar). Sin IA ni internet: agrupa los vídeos
publicados por el formato de su guion (ascenso y caída, rivalidad…) y prepara el título y
la descripción para copiar en YouTube Studio.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs, profile
from app.models import Video

MIN_VIDEOS = 2  # una lista con un solo vídeo no sirve
MAX_LISTS = 4


def _format_of(db: Session, video: Video) -> str:
    if not video.project_id:
        return ""
    script = jobs.get_result(db, video.project_id, "script") or {}
    return str(script.get("structure_name") or "").strip()


def _playlist(name: str, videos: list[Video], channel: str) -> dict:
    title = f"{name} | {channel}" if channel else name
    description = (
        f"{name}: {len(videos)} vídeos de {channel or 'este canal'}. "
        "Empieza por el primero y deja que se reproduzcan seguidos."
    )
    return {"title": title[:150], "description": description, "videos": [v.title for v in videos]}


def suggest(db: Session) -> list[dict]:
    """Hasta 4 listas: una por cada formato con 2 vídeos o más, y «Más historias» con los
    que quedan fuera (para que no se olvide ninguno)."""
    videos = sorted(  # del más viejo al más nuevo; los que no tienen fecha, al final
        (v for v in db.scalars(select(Video)) if v.title),
        key=lambda v: (not v.published, v.published or ""),
    )
    if len(videos) < MIN_VIDEOS:
        return []
    channel = profile.get(db)["channel"]
    groups: dict[str, list[Video]] = {}
    for video in videos:
        name = _format_of(db, video)
        if name:
            groups.setdefault(name, []).append(video)
    kept = [
        (name, group)
        for name, group in sorted(groups.items(), key=lambda item: -len(item[1]))
        if len(group) >= MIN_VIDEOS
    ][: MAX_LISTS - 1]
    lists = [_playlist(name, group, channel) for name, group in kept]
    used = {v.video_id for _, group in kept for v in group}
    rest = [v for v in videos if v.video_id not in used]
    if len(rest) >= MIN_VIDEOS:
        lists.append(_playlist("Más historias" if lists else "Todas las historias", rest, channel))
    return lists
