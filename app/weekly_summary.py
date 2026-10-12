"""RESUMEN DEL DOMINGO: cómo fue la semana del canal, en un mensaje.

Sin IA ni internet: usa las fotos de visitas que el programa ya guarda de cada vídeo
(Rendimiento) y el historial de suscriptores. Compara los últimos 7 días con los 7
anteriores, dice qué vídeo tiró más y da un consejo sencillo para la semana siguiente.
"""

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Video, VideoStat
from app.settings_store import get_setting

WEEK = timedelta(days=7)


def _snapshots(db: Session, now: datetime) -> dict[str, list[tuple[datetime, int]]]:
    """Las fotos de visitas de cada vídeo del último mes, de la más vieja a la más nueva."""
    found: dict[str, list[tuple[datetime, int]]] = {}
    for stat in db.scalars(
        select(VideoStat)
        .where(VideoStat.taken_at <= now, VideoStat.taken_at >= now - 5 * WEEK)
        .order_by(VideoStat.taken_at)
    ):
        found.setdefault(stat.video_id, []).append((stat.taken_at, stat.views or 0))
    return found


def _at(shots: list[tuple[datetime, int]], moment: datetime) -> int | None:
    before = [views for taken, views in shots if taken <= moment]
    return before[-1] if before else None


def _gain(shots, start: datetime, end: datetime, published: str) -> int:
    """Visitas ganadas entre dos momentos. Si el vídeo empezó a seguirse después de
    `start`, cuenta desde su primera foto (salvo que se publicara en ese tramo); un vídeo
    borrado o sin foto nueva no resta."""
    last = _at(shots, end)
    if last is None:
        return 0
    base = _at(shots, start)
    if base is None:
        base = 0 if published and published >= start.strftime("%Y-%m-%d") else shots[0][1]
    return max(0, last - base)


def _subs_at(db: Session, moment: datetime) -> int | None:
    """Suscriptores apuntados ese día o hasta 3 días antes (si no, no se sabe)."""
    day, oldest = moment.strftime("%Y-%m-%d"), (moment - timedelta(days=3)).strftime("%Y-%m-%d")
    try:
        history = json.loads(get_setting(db, "subs_history") or "[]")
        before = [int(subs) for date, subs in history if oldest <= str(date) <= day]
    except (ValueError, TypeError):
        return None
    return before[-1] if before else None


def summary(db: Session, now: datetime) -> dict | None:
    """Las cifras de la semana. None si aún no hay dos semanas de datos para comparar."""
    oldest = db.scalar(select(VideoStat.taken_at).order_by(VideoStat.taken_at).limit(1))
    newest = db.scalar(select(VideoStat.taken_at).order_by(VideoStat.taken_at.desc()).limit(1))
    if oldest is None or oldest > now - 2 * WEEK + timedelta(days=1):
        return None
    if newest < now - timedelta(days=2):  # las cifras no se actualizan: no hay qué contar
        return None
    shots = _snapshots(db, now)
    published = {v.video_id: v.published or "" for v in db.scalars(select(Video))}
    gains = {vid: _gain(seq, now - WEEK, now, published.get(vid, "")) for vid, seq in shots.items()}
    this_week = sum(gains.values())
    last_week = sum(
        _gain(seq, now - 2 * WEEK, now - WEEK, published.get(vid, "")) for vid, seq in shots.items()
    )
    best_id = max(gains, key=gains.get) if gains else None
    best = db.get(Video, best_id) if best_id and gains[best_id] > 0 else None
    subs_now = _subs_at(db, now)
    subs_before = _subs_at(db, now - WEEK)
    return {
        "views": this_week,
        "previous": last_week,
        "best": {"title": best.title, "views": gains[best_id]} if best else None,
        "subs": subs_now,
        "new_subs": subs_now - subs_before
        if subs_now is not None and subs_before is not None
        else None,
    }


def tip(data: dict) -> str:
    if data["views"] < data["previous"]:
        return (
            "La semana bajó: sube un Short con el momento más fuerte de tu mejor vídeo y "
            "que invite a verlo entero."
        )
    if data["best"]:
        return f"Lo que más tiró fue «{data['best']['title']}»: el próximo, de ese estilo."
    return "Publica tu vídeo de la semana el día de siempre: la constancia también cuenta."
