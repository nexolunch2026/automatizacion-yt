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
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import info
from app.models import Project, Video, VideoStat
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

REFRESH_HOURS = 3
RETRY_MINUTES = 30
CHECK_NAME = "revisa el nombre en JARVIS → Lo que JARVIS sabe de ti"
STALE_AFTER = timedelta(days=2)  # cifras sin actualizar más tiempo: JARVIS avisa
MAX_GAP = timedelta(hours=24)  # entre dos fotos, para estimar las visitas a una edad
STALE_MIN_FAILURES = 3  # intentos fallidos (cada 30 min) antes de avisar
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


def fetch_videos(db: Session, handle: str | None = None) -> dict:
    """Suscriptores y vídeos de un canal (por defecto, el principal) con sus cifras de ahora."""
    handle = info.channel_handle(db) if handle is None else handle
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


def _check_subscribers(
    db: Session, subs: int | None, now: datetime, suffix: str = "", name: str = "El canal"
) -> None:
    """`suffix`: vacío para el canal principal (como siempre); «:@Otro» para los demás."""
    if subs is None:
        return
    history = json.loads(get_setting(db, "subs_history" + suffix) or "[]")
    today = now.strftime("%Y-%m-%d")
    if history and history[-1][0] == today:
        history[-1][1] = subs
    else:
        history.append([today, subs])
    set_setting(db, "subs_history" + suffix, json.dumps(history[-400:]))
    done = set(json.loads(get_setting(db, "subs_milestones" + suffix) or "[]"))
    reached = [m for m in SUB_MILESTONES if subs >= m and m not in done]
    if reached:
        from app.skills import number

        top = max(reached)
        extra = " ¡Meta de monetización conseguida!" if top >= 1000 > max(done, default=0) else ""
        _celebrate(db, f"{name} llegó a {number(top)} suscriptores.{extra}", now)
        set_setting(db, "subs_milestones" + suffix, json.dumps(sorted(done | set(reached))))


def refresh(db: Session, now: datetime | None = None) -> int:
    """Guarda las cifras de ahora de todos los vídeos. Devuelve cuántos vídeos leyó."""
    now = now or datetime.now()
    handles = info.channel_handles(db) or [info.channel_handle(db)]
    read = 0
    for n, handle in enumerate(handles):
        # El principal, como siempre; si falla otro canal, no se pierde lo del principal.
        if n == 0:
            data = fetch_videos(db, handle)
        else:
            try:
                data = fetch_videos(db, handle)
            except Exception:  # noqa: BLE001 — un canal mal escrito no tumba los demás
                log.warning("No se pudo leer el canal de YouTube %s", handle, exc_info=True)
                continue
        _store(db, data, now)
        _check_subscribers(db, data.get("subscribers"), now, "" if n == 0 else f":{handle}",
                           "El canal" if n == 0 else f"El canal {handle}")  # fmt: skip
        read += len(data.get("latest", []))
    db.commit()
    set_setting(db, "analytics_last", now.isoformat(timespec="seconds"))
    for key in ("analytics_error", "analytics_error_since", "analytics_error_count"):
        set_setting(db, key, "")
    try:  # enlazar con los proyectos es un extra: las cifras ya están guardadas
        link_projects(db)
    except Exception:  # noqa: BLE001
        log.exception("No se pudieron enlazar los vídeos con sus proyectos")
        db.rollback()
    return read


def _store(db: Session, data: dict, now: datetime) -> None:
    """Guarda las cifras de ahora de los vídeos de un canal."""
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


def safe_error(exc: Exception) -> str:
    """El texto del error sin la clave de YouTube (va en la dirección de la consulta)."""
    return re.sub(r"key=[^&\s'\"]+", "key=***", str(exc))


def failure_reason(exc: Exception, has_key: bool) -> str:
    """El motivo de un fallo al leer las cifras, en palabras sencillas."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (400, 401, 403) and has_key:
            return (
                "YouTube no acepta tu clave (puede que esté mal copiada, la hayan "
                "desactivado o se acabara el cupo gratis de hoy)"
            )
        if code in (403, 429) and not has_key:
            return (
                "YouTube no deja leer el canal sin clave (pon la clave gratuita de YouTube "
                "en JARVIS → Lo que JARVIS sabe de ti)"
            )
        if code == 404:
            return f"YouTube no encuentra tu canal ({CHECK_NAME})"
        if code == 429 or code >= 500:
            return "YouTube está saturado o caído en este momento"
        return f"YouTube respondió con un error ({code})"
    if isinstance(exc, httpx.TransportError):
        return "el ordenador no tiene internet o YouTube no responde"
    if isinstance(exc, ValueError) and "canal" in str(exc):
        return f"no encuentro tu canal ({CHECK_NAME})"
    if isinstance(exc, (KeyError, IndexError)) and has_key:
        return f"YouTube no devuelve datos de tu canal ({CHECK_NAME})"
    if isinstance(exc, (SQLAlchemyError, OSError)):
        return "falló algo dentro del programa, no en YouTube (mira la ventana negra)"
    return f"YouTube devolvió algo que no entiendo ({type(exc).__name__})"


def record_failure(db: Session, exc: Exception, now: datetime | None = None) -> str:
    """Apunta por qué no se pudieron leer las cifras (y desde cuándo falla)."""
    now = now or datetime.now()
    reason = failure_reason(exc, bool(get_api_key(db, "youtube")))
    set_setting(db, "analytics_error", reason)
    try:
        count = int(get_setting(db, "analytics_error_count") or 0)
    except ValueError:
        count = 0
    set_setting(db, "analytics_error_count", str(count + 1))
    if not get_setting(db, "analytics_error_since"):
        set_setting(db, "analytics_error_since", now.isoformat(timespec="seconds"))
    return reason


def _when(raw: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        log.warning("Fecha guardada que no se entiende: %r", raw)
        return None


def stale_status(db: Session, now: datetime | None = None) -> dict | None:
    """Si lleva más de 2 días fallando cada intento de leer las cifras: desde cuándo y
    por qué. None si el último intento fue bien. Un PC apagado no cuenta como fallo: hacen
    falta varios intentos fallidos y que las últimas cifras buenas tengan más de 2 días."""
    now = now or datetime.now()
    reason = get_setting(db, "analytics_error")
    since = _when(get_setting(db, "analytics_error_since"))
    if not reason or since is None:
        return None
    try:
        failures = int(get_setting(db, "analytics_error_count") or 0)
    except ValueError:
        failures = 0
    last = _when(get_setting(db, "analytics_last"))
    if failures < STALE_MIN_FAILURES or now - since < STALE_AFTER:
        return None
    if last and now - last < STALE_AFTER:
        return None
    return {"reason": reason, "since": since, "last": last, "days": (now - since).days}


def maybe_refresh(db: Session, now: datetime | None = None) -> bool:
    """Cada pocas horas (lo llama el trabajador cuando no tiene tareas). Cualquier fallo
    queda apuntado con su motivo, para que JARVIS avise si las cifras se quedan paradas."""
    now = now or datetime.now()
    due = _when(get_setting(db, "analytics_next"))
    if due and due > now:
        return False
    wait = timedelta(minutes=RETRY_MINUTES)
    try:
        refresh(db, now)
        wait = timedelta(hours=REFRESH_HOURS)
    except Exception as exc:  # noqa: BLE001 — se apunta el motivo y se reintenta luego
        log.warning("No se pudieron leer las cifras del canal: %s", safe_error(exc))
        db.rollback()
        try:
            record_failure(db, exc, now)
        except Exception:  # noqa: BLE001 — si la base de datos falla, al menos el registro
            log.exception("No se pudo apuntar el fallo de las cifras")
            db.rollback()
    finally:
        try:
            set_setting(db, "analytics_next", (now + wait).isoformat(timespec="seconds"))
        except Exception:  # noqa: BLE001 — sin esto se reintentaría en cada vuelta
            log.exception("No se pudo apuntar el próximo intento de las cifras")
            db.rollback()
    return True


# ---------------------------------------------------------------- resumen


def _views_at(stats: list[VideoStat], moment: datetime) -> int | None:
    """Visitas en un momento dado (la foto más cercana anterior), si se tomó."""
    before = [s for s in stats if s.taken_at <= moment]
    if not before or (moment - before[-1].taken_at) > timedelta(hours=12):
        return None
    return before[-1].views


SAME_AGE_MIN = 3  # hacen falta al menos 3 vídeos más viejos para saber qué es «lo normal»
SAME_AGE_FLOOR = 10  # con menos visitas «normales», cualquier cifra parece enorme


def _views_between(stats: list[VideoStat], moment: datetime) -> float | None:
    """Visitas en un momento, repartidas entre la foto de antes y la de después (si el
    vídeo aún no llegó a ese momento, None)."""
    before = [s for s in stats if s.taken_at <= moment]
    after = [s for s in stats if s.taken_at >= moment]
    if not before or not after:
        return None
    a, b = before[-1], after[0]
    if b.taken_at == a.taken_at:
        return float(a.views)
    if b.taken_at - a.taken_at > MAX_GAP:
        return None  # fotos muy separadas (PC apagado): repartir inventaría la cifra
    share = (moment - a.taken_at) / (b.taken_at - a.taken_at)
    return a.views + (b.views - a.views) * share


def same_age(db: Session, rows: list[dict], row: dict) -> dict | None:
    """Cuántas visitas solían tener tus otros vídeos a la misma edad que `row` (al tomar
    su última cifra). {"normal", "ratio", "count", "hours"} o None si no hay con qué
    comparar."""
    from statistics import median

    if not row.get("exact_time") or not row.get("updated"):
        return None  # sin la hora de publicación, la edad puede fallar un día
    age = row["updated"] - row["published_at"]
    if age < timedelta(hours=12):
        return None  # las primeras horas bailan demasiado
    others = [
        o
        for o in rows
        if o["video_id"] != row["video_id"]
        and o.get("exact_time")
        and bool(o.get("is_short")) == bool(row.get("is_short"))  # Shorts con Shorts
        and o.get("updated")
        and o["published_at"] + age <= o["updated"]  # ya llegó a esa edad
    ]
    if len(others) < SAME_AGE_MIN:
        return None
    by_video: dict[str, list[VideoStat]] = {}
    for stat in db.scalars(
        select(VideoStat)
        .where(VideoStat.video_id.in_([o["video_id"] for o in others]))
        .order_by(VideoStat.taken_at)
    ):
        by_video.setdefault(stat.video_id, []).append(stat)
    found = []
    for other in others:
        views = _views_between(by_video.get(other["video_id"], []), other["published_at"] + age)
        if views is not None:
            found.append(views)
    if len(found) < SAME_AGE_MIN:
        return None
    normal = median(found)
    if normal < SAME_AGE_FLOOR:
        return None
    return {
        "normal": round(normal),
        "ratio": row["views"] / normal,
        "count": len(found),
        "hours": round(age.total_seconds() / 3600),
    }


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
            if "T" in video.published:  # a la hora local de ese día (con su horario de verano)
                published = published.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
            weekday = published.weekday()  # 0 = lunes
        except ValueError:
            published, weekday = stats[0].taken_at, None  # sin fecha: no se sabe el día
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
                "retention_30s": video.retention_30s,
                "retention_mid": video.retention_mid,
                "channel_id": project.channel_id if project else None,
                "project_id": project.id if project else None,
                "project": project.title if project else None,
                "topic": project.topic if project else None,
                "thumb_text": thumb["variants"][chosen]["text"]
                if chosen is not None and thumb.get("variants")
                else None,
                "history": list(daily.items())[-30:],
                "updated": last.taken_at,  # cuándo se tomó la última cifra
                "exact_time": weekday is not None and "T" in video.published,  # hora exacta
                "published_at": published,  # hora local (o la primera cifra, si no hay fecha)
                "weekday": weekday,
                "hour": published.hour if weekday is not None and "T" in video.published else None,
                "is_short": bool(project and project.duration == "Short"),
            }
        )
    if rows:
        average = sum(r["views_per_day"] for r in rows) / len(rows)
        for r in rows:
            r["vs_average"] = round(r["views_per_day"] / average * 100) if average else None
            r["diagnosis"] = retention_diagnosis(r)
    return rows


# ---------------------------------------------------------------- retención

# Referencias para documentales largos (aproximadas: cada nicho es distinto).
HOOK_OK = 60  # % que sigue a los 30 s; por debajo, el gancho pierde a mucha gente
MIDDLE_KEEP = 0.6  # de los que pasan los 30 s, al menos el 60 % debería llegar a la mitad
AVERAGE_OK = 35  # % medio visto; por debajo, el vídeo en conjunto se hace largo


def retention_diagnosis(row: dict) -> list[dict]:
    """Qué parte del vídeo pierde gente, con los datos de retención que haya."""
    found = []
    hook, mid, average = row.get("retention_30s"), row.get("retention_mid"), row.get("retention")
    if hook is not None and hook < HOOK_OK:
        found.append(
            {
                "part": "hook",
                "text": f"Solo el {hook:g} % sigue a los 30 s: el gancho pierde gente.",
            }
        )
    if hook and mid is not None and mid / hook < MIDDLE_KEEP:
        found.append(
            {
                "part": "middle",
                "text": f"De {hook:g} % a los 30 s baja a {mid:g} % a la mitad: el desarrollo "
                "se hace largo.",
            }
        )
    if average is not None and average < AVERAGE_OK and not found:
        found.append(
            {"part": "overall", "text": f"Se ve de media el {average:g} %: falta ritmo en general."}
        )
    return found


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def retention_summary(rows: list[dict], channel_id: int | None = None, limit: int = 5) -> dict:
    """Lo que dicen los datos de retención de los últimos vídeos (del canal, si se da)."""
    rows = [
        r
        for r in rows
        if (channel_id is None or r.get("channel_id") in (channel_id, None))
        and any(r.get(k) is not None for k in ("retention_30s", "retention_mid", "retention"))
    ][:limit]
    hooks = [r["retention_30s"] for r in rows if r.get("retention_30s") is not None]
    keeps = [
        r["retention_mid"] / r["retention_30s"]
        for r in rows
        if r.get("retention_30s") and r.get("retention_mid") is not None
    ]
    averages = [r["retention"] for r in rows if r.get("retention") is not None]
    hook, keep, average = _mean(hooks), _mean(keeps), _mean(averages)
    weak = []
    if hook is not None and hook < HOOK_OK:
        weak.append("hook")
    if keep is not None and keep < MIDDLE_KEEP:
        weak.append("middle")
    if average is not None and average < AVERAGE_OK and not weak:
        weak.append("overall")
    return {"videos": len(rows), "hook": hook, "keep": keep, "average": average, "weak": weak}


RETENTION_FIXES = {
    "hook": "En los últimos vídeos, mucha gente se va en los primeros 30 segundos "
    "({hook:g} % sigue). Refuerza el GANCHO: empieza en el momento de más tensión con una "
    "frase corta, di en los primeros 10 s qué está en juego y promete algo que solo se "
    "descubre al final. Nada de contexto ni presentaciones antes de los 30 s.",
    "middle": "En los últimos vídeos, la gente se va a mitad del vídeo (de cada 100 que pasan "
    "los 30 s, unos {keep_pct:g} llegan a la mitad). Refuerza el DESARROLLO: un giro o dato "
    "sorprendente cada 60–90 s, cada sección cierra con una pregunta abierta y recuerda a "
    "mitad de vídeo la promesa del gancho.",
    "overall": "En los últimos vídeos se ve de media solo el {average:g} %. Más RITMO: frases "
    "más cortas, quita lo que no haga avanzar la historia y adelanta lo más interesante.",
}


def retention_notes(summary: dict) -> str:
    """Instrucciones para el próximo guion según los datos (vacío si no hay problema)."""
    values = {
        "hook": summary.get("hook") or 0,
        "keep_pct": round((summary.get("keep") or 0) * 100),
        "average": summary.get("average") or 0,
    }
    return "\n".join(RETENTION_FIXES[part].format(**values) for part in summary.get("weak", []))


def channel_retention_notes(db: Session, channel_id: int | None) -> str:
    try:
        return retention_notes(retention_summary(video_rows(db), channel_id))
    except Exception:  # noqa: BLE001 — un dato raro no puede parar un guion
        log.exception("No se pudieron leer los datos de retención")
        return ""


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
        if r.get("retention_30s") is not None:
            extra.append(f"sigue a los 30 s el {r['retention_30s']} %")
        if r.get("retention_mid") is not None:
            extra.append(f"sigue a la mitad el {r['retention_mid']} %")
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
