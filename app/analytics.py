"""RENDIMIENTO: JARVIS aprende de los resultados del canal.

- Cada pocas horas guarda una «foto» de las visitas, «me gusta» y comentarios de cada
  vídeo publicado (con la clave de YouTube, de todos; sin clave, de los últimos 15).
- Enlaza cada vídeo de YouTube con su proyecto (por el título, o con el enlace que
  pegues en la página Publicación).
- Celebra los hitos (100, 500, 1.000 visitas… o suscriptores) en la pantalla y por Telegram.
- Con Gemini analiza qué funcionó, qué mejorar y qué temas hacer después.
"""

import difflib
import json
import logging
import re
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import info
from app.models import Project, Video, VideoStat
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

REFRESH_HOURS = 3
RETRY_MINUTES = 30
VIEW_MILESTONES = [100, 500, 1000, 5000, 10_000, 50_000, 100_000, 500_000, 1_000_000]
SUB_MILESTONES = [10, 50, 100, 250, 500, 1000, 2500, 5000, 10_000, 50_000, 100_000]
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})")


def parse_video_id(text: str) -> str | None:
    text = text.strip()
    if re.fullmatch(r"[\w-]{11}", text):
        return text
    match = VIDEO_ID.search(text)
    return match.group(1) if match else None


# ---------------------------------------------------------------- recoger datos


def fetch_videos(db: Session) -> dict:
    """Suscriptores y vídeos del canal (todos los posibles) con sus cifras de ahora."""
    handle = info.channel_handle(db)
    key = get_api_key(db, "youtube")
    if key:
        return info.fetch_youtube_api(handle, key, limit=50)
    return info.fetch_youtube_public(handle, limit=15)


def _norm(text: str) -> str:
    from app.assistant import normalize

    return re.sub(r"[^\w ]", "", normalize(text)).strip()


def _project_titles(db: Session, project: Project) -> list[str]:
    from app import jobs

    titles = [project.title, project.topic]
    seo = jobs.get_result(db, project.id, "publish") or {}
    titles += seo.get("titles", [])
    script = jobs.get_result(db, project.id, "script") or {}
    if script.get("title"):
        titles.append(script["title"])
    return [t for t in titles if t]


def link_projects(db: Session) -> None:
    """Enlaza por el título los vídeos que aún no tienen proyecto."""
    unlinked = db.scalars(select(Video).where(Video.project_id.is_(None))).all()
    if not unlinked:
        return
    taken = {v.project_id for v in db.scalars(select(Video)) if v.project_id}
    projects = [p for p in db.scalars(select(Project)) if p.id not in taken]
    for video in unlinked:
        best, score = None, 0.0
        for project in projects:
            for title in _project_titles(db, project):
                ratio = difflib.SequenceMatcher(None, _norm(video.title), _norm(title)).ratio()
                if ratio > score:
                    best, score = project, ratio
        if best and score >= 0.8:
            video.project_id = best.id
            projects.remove(best)
    db.commit()


def _celebrate(db: Session, text: str, now: datetime) -> None:
    from app import agenda

    agenda.add_reminder(db, text, now, kind="milestone")


def _check_milestones(db: Session, video: Video, views: int, now: datetime) -> None:
    done = set(json.loads(video.milestones or "[]"))
    reached = [m for m in VIEW_MILESTONES if views >= m and m not in done]
    if not reached:
        return
    from app.skills import number

    # Solo se celebra el mayor (si un vídeo pasa de 90 a 600 visitas, no se avisa dos veces).
    _celebrate(db, f"«{video.title}» ha pasado las {number(max(reached))} visitas", now)
    video.milestones = json.dumps(sorted(done | set(reached)))


def _check_subscribers(db: Session, subs: int | None, now: datetime) -> None:
    if subs is None:
        return
    history = json.loads(get_setting(db, "subs_history") or "[]")
    today = now.strftime("%Y-%m-%d")
    if history and history[-1][0] == today:
        history[-1][1] = subs
    else:
        history.append([today, subs])
    set_setting(db, "subs_history", json.dumps(history[-400:]))
    done = set(json.loads(get_setting(db, "subs_milestones") or "[]"))
    reached = [m for m in SUB_MILESTONES if subs >= m and m not in done]
    if reached:
        from app.skills import number

        top = max(reached)
        extra = " ¡Meta de monetización conseguida!" if top >= 1000 > max(done, default=0) else ""
        _celebrate(db, f"El canal llegó a {number(top)} suscriptores.{extra}", now)
        set_setting(db, "subs_milestones", json.dumps(sorted(done | set(reached))))


def refresh(db: Session, now: datetime | None = None) -> int:
    """Guarda las cifras de ahora de todos los vídeos. Devuelve cuántos vídeos leyó."""
    now = now or datetime.now()
    data = fetch_videos(db)
    for item in data.get("latest", []):
        if not item.get("id"):
            continue
        video = db.get(Video, item["id"])
        if video is None:
            video = Video(video_id=item["id"], title=item["title"], published=item["published"])
            db.add(video)
        video.title, video.published = item["title"], item["published"] or video.published
        last = db.scalar(
            select(VideoStat)
            .where(VideoStat.video_id == item["id"])
            .order_by(VideoStat.taken_at.desc())
            .limit(1)
        )
        if last is None or now - last.taken_at >= timedelta(minutes=50):
            db.add(
                VideoStat(
                    video_id=item["id"],
                    taken_at=now,
                    views=item["views"],
                    likes=item.get("likes"),
                    comments=item.get("comments"),
                )
            )
        db.flush()
        _check_milestones(db, video, item["views"], now)
    _check_subscribers(db, data.get("subscribers"), now)
    db.commit()
    link_projects(db)
    set_setting(db, "analytics_last", now.isoformat(timespec="seconds"))
    return len(data.get("latest", []))


def maybe_refresh(db: Session, now: datetime | None = None) -> bool:
    """Cada pocas horas (lo llama el trabajador cuando no tiene tareas)."""
    now = now or datetime.now()
    due = get_setting(db, "analytics_next")
    if due and datetime.fromisoformat(due) > now:
        return False
    try:
        refresh(db, now)
        wait = timedelta(hours=REFRESH_HOURS)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning("No se pudieron leer las cifras del canal: %s", exc)
        db.rollback()
        wait = timedelta(minutes=RETRY_MINUTES)
    set_setting(db, "analytics_next", (now + wait).isoformat(timespec="seconds"))
    return True


# ---------------------------------------------------------------- resumen


def _views_at(stats: list[VideoStat], moment: datetime) -> int | None:
    """Visitas en un momento dado (la foto más cercana anterior), si se tomó."""
    before = [s for s in stats if s.taken_at <= moment]
    if not before or (moment - before[-1].taken_at) > timedelta(hours=12):
        return None
    return before[-1].views


def video_rows(db: Session, now: datetime | None = None) -> list[dict]:
    from app import jobs

    now = now or datetime.now()
    rows = []
    for video in db.scalars(select(Video).order_by(Video.published.desc())):
        stats = db.scalars(
            select(VideoStat)
            .where(VideoStat.video_id == video.video_id)
            .order_by(VideoStat.taken_at)
        ).all()
        if not stats:
            continue
        last = stats[-1]
        try:  # «2026-10-03T15:00» (UTC, de YouTube) o solo la fecha
            published = datetime.fromisoformat(video.published[:16])
            if "T" in video.published:
                published += datetime.now().astimezone().utcoffset() or timedelta()  # hora local
        except ValueError:
            published = stats[0].taken_at
        days = max((now - published).total_seconds() / 86400, 1 / 24)
        project = db.get(Project, video.project_id) if video.project_id else None
        thumb = (jobs.get_result(db, project.id, "thumbnail") or {}) if project else {}
        chosen = thumb.get("selected")
        daily = {}
        for s in stats:  # una cifra por día para la mini gráfica
            daily[s.taken_at.strftime("%Y-%m-%d")] = s.views
        rows.append(
            {
                "video_id": video.video_id,
                "title": video.title,
                "url": f"https://www.youtube.com/watch?v={video.video_id}",
                "published": video.published[:10],
                "days": round(days, 1),
                "age": f"hace {round(days * 24)} h" if days < 1 else f"hace {round(days)} días",
                "views": last.views,
                "likes": last.likes,
                "comments": last.comments,
                "like_rate": round(last.likes / last.views * 100, 1)
                if last.likes is not None and last.views
                else None,
                "views_per_day": round(last.views / days, 1),
                "views_48h": _views_at(stats, published + timedelta(hours=48)),
                "ctr": video.ctr,
                "retention": video.retention,
                "project_id": project.id if project else None,
                "project": project.title if project else None,
                "topic": project.topic if project else None,
                "thumb_text": thumb["variants"][chosen]["text"]
                if chosen is not None and thumb.get("variants")
                else None,
                "history": list(daily.items())[-30:],
            }
        )
    if rows:
        average = sum(r["views_per_day"] for r in rows) / len(rows)
        for r in rows:
            r["vs_average"] = round(r["views_per_day"] / average * 100) if average else None
    return rows


# ---------------------------------------------------------------- análisis con IA


class Insight(BaseModel):
    summary: str = Field(description="2–3 frases: cómo va el canal, sin adornos")
    worked: list[str] = Field(description="Lo que funcionó y por qué (basado en los datos)")
    improve: list[str] = Field(description="Lo que conviene cambiar")
    next_steps: list[str] = Field(description="3 acciones concretas para los próximos vídeos")
    topic_ideas: list[str] = Field(description="5 temas de vídeo en la línea de lo que funciona")


def _prompt(db: Session, rows: list[dict]) -> str:
    lines = []
    for r in rows[:20]:
        extra = []
        if r["ctr"] is not None:
            extra.append(f"CTR {r['ctr']} %")
        if r["retention"] is not None:
            extra.append(f"visto en promedio {r['retention']} %")
        if r["views_48h"] is not None:
            extra.append(f"{r['views_48h']} visitas en 48 h")
        lines.append(
            f"- «{r['title']}» (publicado {r['published']}, {r['age']}): "
            f"{r['views']} visitas, {r['views_per_day']}/día, {r['likes'] or 0} me gusta, "
            f"{r['comments'] or 0} comentarios"
            + (f", miniatura «{r['thumb_text']}»" if r["thumb_text"] else "")
            + (f", {', '.join(extra)}" if extra else "")
        )
    subs = json.loads(get_setting(db, "subs_history") or "[]")
    growth = f"Suscriptores: {subs[0][1]} → {subs[-1][1]} desde {subs[0][0]}." if subs else ""
    from app import profile

    return f"""Eres analista de YouTube para {profile.about(db)}
Es un canal nuevo. Con estos datos reales, di qué funciona y qué mejorar.
Sé honesto y concreto; con pocos vídeos o pocos días, dilo y no saques conclusiones
fuertes. No inventes datos que no estén aquí. En español, frases cortas.
Referencias útiles: un CTR de 4–10 % es normal; si la gente ve menos del 30 %, el
inicio del vídeo engancha poco.

{growth}
VÍDEOS:
{chr(10).join(lines)}"""


def analyze(db: Session, ai, now: datetime | None = None) -> dict:
    rows = video_rows(db, now)
    if not rows:
        raise ValueError("Aún no hay vídeos con datos.")
    insight = ai.generate_json(_prompt(db, rows), Insight)
    data = {**insight.model_dump(), "date": (now or datetime.now()).strftime("%d/%m/%Y %H:%M")}
    set_setting(db, "analytics_insight", json.dumps(data, ensure_ascii=False))
    return data


def last_insight(db: Session) -> dict | None:
    raw = get_setting(db, "analytics_insight")
    return json.loads(raw) if raw else None


def performance_hint(db: Session) -> str:
    """Una línea con lo que mejor funciona, para orientar las ideas de vídeo."""
    rows = sorted(video_rows(db), key=lambda r: r["views_per_day"], reverse=True)
    if len(rows) < 2:
        return ""
    best = ", ".join(f"«{r['title']}»" for r in rows[:3])
    return f"Los vídeos del canal que mejor funcionan (visitas por día): {best}."
