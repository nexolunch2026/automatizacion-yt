"""JARVIS como entrenador del canal.

- `next_steps`: qué hay que hacer ahora en cada vídeo a medias (con un botón para hacerlo).
- `monetization_path`: cuánto falta para entrar en el Programa de Socios (suscriptores y
  horas de visualización) y qué conviene hacer para llegar antes.
- `review_project`: la nota del control de calidad de un vídeo.

Nada de esto gasta IA. Solo `monetization_path` lee el canal (con caché de 15 min).
"""

import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.models import JOB_LABELS, Channel, Project, Video
from app.pipeline.monetization import project_review, summary_text, video_seconds
from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

GOAL_SUBS = 1000
GOAL_HOURS = 4000
ELEVEN_WARN_PCT = 70  # % de suscriptores a partir del que avisa de pagar ElevenLabs
DEFAULT_RETENTION = 35  # % medio visto si no lo has copiado de YouTube Studio
RECENT_PROJECTS = 12
MAX_STEPS = 3

# Qué etapa toca y cómo se dice, en el orden del programa.
STEP_LABELS = {
    "research": "Investigar el tema",
    "strategy": "Proponer enfoques",
    "script": "Escribir el guion",
    "storyboard": "Preparar las escenas",
    "voice": "Grabar la voz",
    "visuals": "Buscar las imágenes",
    "edit": "Montar el vídeo",
    "publish": "Preparar los textos para YouTube",
    "thumbnail": "Hacer las miniaturas",
    "shorts": "Sacar los Shorts",
}


def _published_ids(db: Session) -> set[int]:
    return {v.project_id for v in db.scalars(select(Video)) if v.project_id}


def project_step(db: Session, project: Project) -> dict | None:
    """El siguiente paso de un proyecto: {stage, text, button}. `stage` es la etapa que
    lanza el botón, «choose» (elegir enfoque), «pick_thumb» (elegir miniatura),
    «review» (revisar antes de subir) o None (trabajando, no hace falta nada)."""
    latest = jobs.latest_jobs(db, project.id)
    active = [j for j in latest.values() if j.active]
    if active:
        job = active[0]
        return {
            "stage": None,
            "text": f"trabajando en {JOB_LABELS[job.stage].lower()} ({job.progress} %)",
        }
    results = {s: jobs.get_result(db, project.id, s) for s in STEP_LABELS}
    strategy = results["strategy"]
    for stage in STEP_LABELS:
        if stage == "shorts" and project.duration == "Short":
            continue
        if stage == "script" and strategy and not strategy.get("selected"):
            return {"stage": "choose", "text": "elegir uno de los 3 enfoques"}
        if results[stage] is None:
            failed = latest.get(stage)
            if failed is not None and failed.status == "failed":
                return {"stage": stage, "text": f"{STEP_LABELS[stage].lower()} (falló, reintentar)"}
            return {"stage": stage, "text": STEP_LABELS[stage].lower()}
        if stage == "thumbnail" and results[stage].get("selected") is None:
            return {"stage": "pick_thumb", "text": "elegir la miniatura"}
    qc = project_review(db, project)
    if qc["counts"]["fail"] or qc["score"] < 85:
        return {"stage": "review", "text": f"revisar antes de subir (nota {qc['score']}/100)"}
    return {"stage": "upload", "text": f"subirlo a YouTube (nota {qc['score']}/100) 🚀"}


def next_steps(db: Session) -> list[tuple[Project, dict]]:
    """Los vídeos a medias (aún no publicados) con lo que toca hacer en cada uno."""
    published = _published_ids(db)
    steps = []
    for project in db.scalars(select(Project).order_by(Project.id.desc()).limit(RECENT_PROJECTS)):
        if project.id in published or project.status == "Publicado":
            continue
        step = project_step(db, project)
        if step:
            steps.append((project, step))
        if len(steps) >= MAX_STEPS:
            break
    return steps


def first_step_text(db: Session) -> str:
    """Una línea para el resumen del día."""
    steps = [(p, s) for p, s in next_steps(db) if s["stage"]]
    if not steps:
        return ""
    project, step = steps[0]
    return f"👉 Lo siguiente: «{project.title}» — {step['text']}."


# ---------------------------------------------------------------- camino a monetizar


def _video_seconds(db: Session, project_id: int | None) -> float | None:
    if not project_id:
        return None
    results = {s: jobs.get_result(db, project_id, s) for s in ("edit", "voice")}
    return video_seconds(results)


def watch_hours(db: Session, now: datetime | None = None) -> dict:
    """Horas vistas estimadas en los últimos 12 meses: visitas × duración × % visto.

    YouTube solo cuenta los vídeos largos públicos (no los Shorts). Si no copiaste el %
    visto de YouTube Studio, se supone un 35 %."""
    from app import analytics

    now = now or datetime.now()
    hours, counted, unknown, assumed = 0.0, 0, 0, 0
    for row in analytics.video_rows(db, now):
        if row["days"] > 365:
            continue
        seconds = _video_seconds(db, row["project_id"])
        if not seconds or seconds < 60:
            unknown += 0 if seconds else 1
            continue
        retention = row["retention"]
        if retention is None:
            retention, assumed = DEFAULT_RETENTION, assumed + 1
        hours += row["views"] * seconds * retention / 100 / 3600
        counted += 1
    return {
        "hours": round(hours, 1),
        "pct": min(100, round(hours / GOAL_HOURS * 100)),
        "videos": counted,
        "unknown": unknown,
        "assumed": assumed,
    }


def subs_growth(db: Session, now: datetime | None = None) -> float | None:
    """Suscriptores nuevos por día en el último mes (según las fotos de Rendimiento)."""
    now = now or datetime.now()
    try:
        history = json.loads(get_setting(db, "subs_history") or "[]")
    except ValueError:
        return None
    since = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [(d, n) for d, n in history if d >= since]
    if len(recent) < 2:
        return None
    first, last = recent[0], recent[-1]
    days = (datetime.fromisoformat(last[0]) - datetime.fromisoformat(first[0])).days
    return (last[1] - first[1]) / days if days else None


def _subscribers(db: Session) -> int | None:
    from app import info

    try:
        data = info.youtube(db)
    except Exception:  # noqa: BLE001 — sin internet seguimos con lo guardado
        log.info("No se pudo leer el canal", exc_info=True)
        data = None
    if data and data.get("subscribers") is not None:
        return int(data["subscribers"])
    history = json.loads(get_setting(db, "subs_history") or "[]")
    return int(history[-1][1]) if history else None


def monetization_path(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    subs = _subscribers(db)
    growth = subs_growth(db, now)
    hours = watch_hours(db, now)
    eta = None
    if subs is not None and subs < GOAL_SUBS and growth and growth > 0:
        eta = now + timedelta(days=(GOAL_SUBS - subs) / growth)
    tips = []
    subs_pct = min(100, round(subs / GOAL_SUBS * 100)) if subs is not None else None
    if hours["pct"] < (subs_pct or 0):
        tips.append(
            "Las horas van por detrás: haz vídeos de 10–15 minutos y cuida el gancho "
            "(cada minuto visto cuenta)."
        )
    if subs_pct is not None and subs_pct < 100 and subs_pct <= hours["pct"]:
        tips.append(
            "Los suscriptores van por detrás: sube Shorts de cada vídeo y pide la "
            "suscripción justo después de un momento fuerte, no al final."
        )
    if hours["assumed"]:
        tips.append(
            "Copia el «% visto» de YouTube Studio en Rendimiento para que el cálculo de horas "
            "sea exacto."
        )
    if subs_pct is not None and subs_pct >= ELEVEN_WARN_PCT and _uses_free_eleven(db):
        tips.insert(
            0,
            "Ya estás cerca: antes de solicitar la monetización pasa ElevenLabs al plan de "
            "pago (el gratis no lo permite).",
        )
    tips.append("Publica con regularidad (mismo día y hora cada semana): el algoritmo lo premia.")
    return {
        "subs": subs,
        "subs_pct": subs_pct,
        "growth": round(growth, 1) if growth is not None else None,
        "eta": eta,
        "hours": hours,
        "done": subs is not None and subs >= GOAL_SUBS and hours["hours"] >= GOAL_HOURS,
        "tips": tips[:3],
    }


def _uses_free_eleven(db: Session) -> bool:
    """¿El último vídeo con voz se grabó con ElevenLabs en el plan gratis?"""
    for project in db.scalars(select(Project).order_by(Project.id.desc()).limit(10)):
        voice = jobs.get_result(db, project.id, "voice")
        if voice:
            return voice.get("provider") == "elevenlabs" and voice.get("eleven_tier") == "free"
    return False


# ---------------------------------------------------------------- revisión


def find_project(db: Session, words: str) -> Project | None:
    """El proyecto que encaja con lo dicho («el de Nokia»), o el último con guion."""
    from app.assistant import normalize

    wanted = [w for w in normalize(words).split() if len(w) > 3]
    candidates = db.scalars(select(Project).order_by(Project.id.desc()).limit(40)).all()
    if wanted:
        for project in candidates:
            title = normalize(f"{project.title} {project.topic}")
            if all(w in title for w in wanted):
                return project
        return None
    for project in candidates:
        if jobs.get_result(db, project.id, "script"):
            return project
    return None


def review_project(db: Session, project: Project) -> str:
    return f"«{project.title}»\n" + summary_text(project_review(db, project))


# ---------------------------------------------------------------- plan de la semana

DEFAULT_PUBLISH_DAY = 3  # jueves
DEFAULT_PUBLISH_HOUR = 18
SHORTS_DAYS = (0, 2, 4, 5)  # lunes, miércoles, viernes y sábado (como estreno.SHORT_DAYS)
# 30 minutos al día para aprender (ver docs/aprender-de-los-mejores.md).
LEARNING = {
    0: "una lección del curso gratis de storytelling de Edutin",
    1: "estudiar un canal de referencia (MagnatesMedia o Company Man): su primer minuto",
    2: "leer el boletín de Paddy Galloway o de Creator Hooks",
    3: "revisar en Rendimiento tu último vídeo y pulsar «Analizar ahora»",
    4: "retocar a mano 2–3 párrafos del guion de la semana",
    5: "mirar las miniaturas de los vídeos más vistos de un canal de referencia",
    6: "descansar: el canal también necesita que tú estés bien",
}


def publish_slot(db: Session) -> tuple[int, int]:
    """Día de la semana (0 = lunes) y hora a la que se publica el vídeo largo."""
    try:
        day = int(get_setting(db, "publish_day") or DEFAULT_PUBLISH_DAY)
        hour = int(get_setting(db, "publish_hour") or DEFAULT_PUBLISH_HOUR)
    except ValueError:
        return DEFAULT_PUBLISH_DAY, DEFAULT_PUBLISH_HOUR
    return day % 7, min(max(hour, 0), 23)


def set_publish_slot(db: Session, day: int, hour: int | None = None) -> None:
    from app.settings_store import set_setting

    set_setting(db, "publish_day", str(day % 7))
    if hour is not None:
        set_setting(db, "publish_hour", str(min(max(hour, 0), 23)))


def ready_to_upload(db: Session) -> list[Project]:
    """Vídeos con la versión final montada que aún no están publicados."""
    published = _published_ids(db)
    ready = []
    for project in db.scalars(select(Project).order_by(Project.id).limit(200)):
        if project.id in published or project.status == "Publicado":
            continue
        edit = jobs.get_result(db, project.id, "edit") or {}
        if "final" in edit.get("renders", {}):
            ready.append(project)
    return ready


UPLOADED_KEY = "shorts_uploaded"  # Shorts que ya subiste («proyecto:número»)


def uploaded_shorts(db: Session) -> set[str]:
    try:
        data = json.loads(get_setting(db, UPLOADED_KEY) or "[]")
    except ValueError:
        log.warning("Lista de Shorts subidos dañada: se empieza de cero")
        return set()
    return (
        {k for k in data if isinstance(k, str) and k.count(":") == 1}
        if isinstance(data, list)
        else set()
    )


def forget_uploaded_shorts(db: Session, project_id: int) -> None:
    """Al hacer los Shorts de nuevo son otros: se borran sus marcas de «ya subido»."""
    keys = {k for k in uploaded_shorts(db) if not k.startswith(f"{project_id}:")}
    set_setting(db, UPLOADED_KEY, json.dumps(sorted(keys)))


UPLOADED_DAY_KEY = "shorts_uploaded_day"  # día en que apuntaste el último Short subido


def mark_short_uploaded(
    db: Session, project_id: int, number: int, done: bool = True, now: datetime | None = None
) -> None:
    """Apunta (o desapunta) que ya subiste ese Short: el calendario pasa al siguiente, y
    ese día ya no pide otro."""
    keys = uploaded_shorts(db)
    key = f"{project_id}:{number}"
    keys = keys | {key} if done else keys - {key}
    set_setting(db, UPLOADED_KEY, json.dumps(sorted(keys)))
    day = (now or datetime.now()).strftime("%Y-%m-%d") if done else ""
    set_setting(db, UPLOADED_DAY_KEY, day)


FORGOTTEN_AFTER = timedelta(days=7)  # el vídeo largo lleva una semana publicado
FORGOTTEN_UNTIL = timedelta(days=45)  # después ya no se insiste (el vídeo es viejo)
FORGOTTEN_REPEAT = timedelta(days=7)  # como mucho un recordatorio por semana y vídeo
FORGOTTEN_KEY = "forgotten_shorts_alerted"  # proyecto → cuándo se recordó


def forgotten_shorts(db: Session, now: datetime | None = None) -> list[dict]:
    """Vídeos largos publicados hace más de una semana cuyos Shorts preparados no están
    en YouTube (ni apuntados como subidos): son visitas gratis que se quedan sin usar."""
    from app.analytics import _published
    from app.pipeline.end_screen import _is_short_title, _plain
    from app.pipeline.monetization import _without_hashtags

    now = now or datetime.now()
    done = uploaded_shorts(db)
    videos = db.scalars(select(Video)).all()
    by_project: dict[int, list[Video]] = {}
    for video in videos:
        if video.project_id:
            by_project.setdefault(video.project_id, []).append(video)
    found = []
    for project_id, own in by_project.items():
        project = db.get(Project, project_id)
        result = jobs.get_result(db, project_id, "shorts")
        prepared = result.get("shorts") if isinstance(result, dict) else None
        prepared = prepared if isinstance(prepared, list) else []
        titles = {
            n: _plain(_without_hashtags(str(short["title"])))
            for n, short in enumerate(prepared, 1)
            if isinstance(short, dict) and short.get("title")
        }
        if project is None or not titles:
            continue
        # El largo: el primero publicado de los suyos que no se llama como un Short.
        dated = sorted(
            (d, v)
            for v in own
            if not _is_short_title(_without_hashtags(v.title), set(titles.values()))
            and (d := _published(v)) is not None
        )
        if not dated or not FORGOTTEN_AFTER <= now - dated[0][0] <= FORGOTTEN_UNTIL:
            continue
        long_video = dated[0][1]
        on_youtube = [  # solo los sueltos o los de este vídeo (no los de otro proyecto)
            _without_hashtags(v.title)
            for v in videos
            if v.video_id != long_video.video_id and v.project_id in (None, project_id)
        ]
        pending = [
            n
            for n, title in titles.items()
            if f"{project_id}:{n}" not in done
            and not any(_is_short_title(t, {title}) for t in on_youtube)
        ]
        # Otros vídeos ya enlazados a este proyecto que no se llaman como ningún Short son
        # Shorts subidos con otro título: cuentan como subidos (no se sabe cuál es cuál).
        renamed = sum(
            1
            for v in own
            if v.video_id != long_video.video_id
            and not _is_short_title(_without_hashtags(v.title), set(titles.values()))
        )
        pending = pending[renamed:]
        if pending:
            days = (now - dated[0][0]).days
            found.append({"project": project, "pending": pending, "days": days})
    return found


def check_forgotten_shorts(db: Session, now: datetime | None = None) -> int:
    """Recuerda (Telegram y pantalla de JARVIS) los Shorts preparados que no se subieron,
    como mucho una vez por semana y vídeo. Devuelve cuántos recordatorios dejó."""
    from app import agenda

    now = now or datetime.now()
    try:
        alerted = json.loads(get_setting(db, FORGOTTEN_KEY) or "{}")
    except ValueError:
        log.warning("Lista de Shorts ya recordados dañada: se empieza de cero")
        alerted = {}
    if not isinstance(alerted, dict):
        log.warning("Lista de Shorts ya recordados con otro formato: se empieza de cero")
        alerted = {}
    alerted = {
        key: when
        for key, when in alerted.items()
        if isinstance(when, str) and _recent(when, now, FORGOTTEN_REPEAT)
    }
    made = 0
    for item in forgotten_shorts(db, now):
        project, n = item["project"], len(item["pending"])
        key = str(project.id)
        if key in alerted:
            continue
        tail = (
            f" lleva {item['days']} días publicado y tiene {n} Short{'' if n == 1 else 's'} "
            "sin subir (visitas gratis). Si ya lo subiste, márcalo en la pestaña Shorts"
        )
        title = (
            project.title
            if len(project.title) <= 190 - len(tail)
            else project.title[: 185 - len(tail)] + "…"
        )
        # Primero se apunta: si algo falla después, se pierde un aviso en vez de repetirlo.
        alerted[key] = now.isoformat(timespec="seconds")
        set_setting(db, FORGOTTEN_KEY, json.dumps(alerted))
        agenda.add_reminder(db, f"«{title}»{tail}", now)
        made += 1
    return made


MISSED_AFTER_HOURS = 3  # horas después de la hora de publicar para dar el aviso
MISSED_KEY = "missed_publish_day"  # el día en que ya se avisó


def check_missed_publish(db: Session, now: datetime | None = None) -> bool:
    """El día de publicar, unas horas después de la hora elegida, si hay un vídeo listo y
    YouTube aún no lo tiene (no está enlazado a ningún vídeo), JARVIS lo recuerda una vez.
    Se llama justo después de leer las cifras de YouTube: así se sabe que están al día."""
    from app import agenda
    from app.agenda import WEEKDAYS

    now = now or datetime.now()
    day, hour = publish_slot(db)
    today = now.strftime("%Y-%m-%d")
    # Con una hora tardía (21:00 o más) el aviso llega a las 23, no al día siguiente.
    if now.weekday() != day or now.hour < min(hour + MISSED_AFTER_HOURS, 23):
        return False
    if get_setting(db, MISSED_KEY) == today:
        return False
    ready = ready_to_upload(db)
    if not ready:
        return False
    from app.analytics import _published
    from app.pipeline.end_screen import _is_short_title, _short_titles

    # Si hoy ya se subió un vídeo largo de este canal (o uno aún sin enlazar porque en
    # YouTube lleva otro título), no se molesta. Los Shorts y el otro canal no cuentan.
    short_titles = _short_titles(db)
    channel_of = {p.id: p.channel_id for p in db.scalars(select(Project))}
    short_projects = {p.id for p in db.scalars(select(Project).where(Project.duration == "Short"))}
    for video in db.scalars(select(Video)):
        if video.project_id is not None and (
            video.project_id in short_projects
            or channel_of.get(video.project_id) != ready[-1].channel_id
        ):
            continue  # un Short, o un vídeo del otro canal
        title = video.title or ""
        if "#short" in title.lower() or _is_short_title(title, short_titles):
            continue
        if (d := _published(video)) and d.date() == now.date():
            return False
    # Primero se apunta: si algo falla después, se pierde un aviso en vez de repetirlo.
    set_setting(db, MISSED_KEY, today)
    latest = ready[-1]  # el último terminado: el que suele tocar hoy
    title = latest.title if len(latest.title) <= 60 else latest.title[:59] + "…"
    more = f" (y {len(ready) - 1} más listos)" if len(ready) > 1 else ""
    agenda.add_reminder(
        db,
        f"Hoy {WEEKDAYS[day]} tocaba publicar «{title}»{more} a las {hour:02d}:00 y aún no "
        "lo veo en YouTube. Si ya lo subiste, enlázalo en Rendimiento",
        now,
    )
    return True


def _recent(raw: str, now: datetime, span: timedelta) -> bool:
    """¿`raw` (fecha guardada) es de hace menos de `span`? Una fecha del futuro (reloj
    cambiado) o rara no cuenta, para no callar el aviso para siempre."""
    try:
        return timedelta(0) <= now - datetime.fromisoformat(raw) < span
    except (ValueError, TypeError):
        return False


def _shorts_queue(db: Session, channel_id: int | None = None) -> list[dict]:
    """Shorts preparados que aún no has subido, empezando por los del vídeo más reciente
    (de todos los canales, o solo de `channel_id`)."""
    done = uploaded_shorts(db)
    queue = []
    query = select(Project).order_by(Project.id.desc())
    if channel_id is not None:
        query = query.where(Project.channel_id == channel_id)
    for project in db.scalars(query.limit(10)):
        for n, short in enumerate(
            (jobs.get_result(db, project.id, "shorts") or {}).get("shorts", []), 1
        ):
            key = f"{project.id}:{n}"
            if key not in done:
                queue.append(
                    {
                        "key": key,
                        "title": short.get("title") or project.title,
                        "channel_id": project.channel_id,
                    }
                )
    return queue


def weekly_plan(db: Session, now: datetime | None = None) -> dict:
    from app.agenda import WEEKDAYS

    now = now or datetime.now()
    day, hour = publish_slot(db)
    when = f"el {WEEKDAYS[day]} a las {hour}:00"
    ready = ready_to_upload(db)
    if ready:
        qc = project_review(db, ready[0])
        long_text = f"Sube «{ready[0].title}» {when} (nota {qc['score']}/100)."
        if qc["counts"]["fail"] or qc["score"] < 85:
            long_text += " Antes, mejora lo que marca el Control de calidad."
    else:
        steps = [(p, s) for p, s in next_steps(db) if s["stage"]]
        if steps:
            project, step = steps[0]
            long_text = f"Termina «{project.title}» antes del {WEEKDAYS[day]}: {step['text']}."
        else:
            long_text = "No hay ningún vídeo en marcha: empieza uno hoy («banco de ideas»)."
    shorts = _shorts_queue(db)
    upcoming = [(now.weekday() + i) % 7 for i in range(7)]
    if get_setting(db, UPLOADED_DAY_KEY) == now.strftime("%Y-%m-%d"):
        upcoming = upcoming[1:]  # el Short de hoy ya está subido: el siguiente, otro día
    short_days = [d for d in upcoming if d in SHORTS_DAYS]
    schedule = [(d, s["title"], s["key"]) for d, s in zip(short_days, shorts, strict=False)]
    return {
        "publish_day": day,
        "publish_hour": hour,
        "long": long_text,
        "shorts": [
            (WEEKDAYS[d] + (" (hoy)" if d == now.weekday() else ""), title)
            for d, title, _ in schedule
        ],
        "learning": LEARNING[now.weekday()],
        "today_publish": now.weekday() == day and bool(ready),
        "today_short": next((t for d, t, _ in schedule if d == now.weekday()), None),
        "today_short_key": next((k for d, _, k in schedule if d == now.weekday()), None),
        "ready": ready[0].title if ready else None,
    }


def _week(day: datetime) -> tuple[int, int]:
    year, week, _ = day.isocalendar()
    return year, week


def publishing_streak(db: Session, now: datetime | None = None) -> dict | None:
    """Cuántas semanas seguidas (lunes a domingo) se ha publicado al menos un vídeo largo.
    Si esta semana aún no hay, la racha sigue viva hasta el domingo. None si no hay
    ningún vídeo largo publicado todavía. {"weeks", "this_week", "weeks_without"}."""
    from app.analytics import _published
    from app.pipeline.end_screen import _is_short_title, _short_titles

    now = now or datetime.now()
    short_titles = _short_titles(db)
    short_projects = {p.id for p in db.scalars(select(Project).where(Project.duration == "Short"))}
    weeks = set()
    for video in db.scalars(select(Video)):
        if "#short" in (video.title or "").lower() or video.project_id in short_projects:
            continue
        if _is_short_title(video.title or "", short_titles):
            continue
        published = _published(video)
        if published is not None and published <= now:
            weeks.add(_week(published))
    if not weeks:
        return None
    this_week = _week(now) in weeks
    day = now if this_week else now - timedelta(days=7)
    streak = 0
    while _week(day) in weeks:
        streak += 1
        day -= timedelta(days=7)
    last = max(weeks)
    weeks_without = 0  # semanas enteras sin vídeo (la de ahora aún no ha acabado)
    day = now - timedelta(days=7)
    while _week(day) > last:
        weeks_without += 1
        day -= timedelta(days=7)
    return {"weeks": streak, "this_week": this_week, "weeks_without": weeks_without}


def streak_text(streak: dict | None, fresh: bool = True) -> str:
    """Una línea para JARVIS sobre la constancia (lo que más premia YouTube al empezar).
    Con `fresh` falso (las cifras de YouTube llevan días sin actualizarse) no se dice que
    falte un vídeo: puede estar subido y el programa aún no saberlo."""
    if not streak:
        return ""
    n = streak["weeks"]
    if not fresh:
        if not n:
            return ""
        plural = "" if n == 1 else "s"
        return f"🔥 Racha: al menos {n} semana{plural} seguida{plural} con vídeo largo."
    if n:
        plural = "" if n == 1 else "s"
        text = f"🔥 Racha: {n} semana{plural} seguida{plural} con vídeo largo."
        if not streak["this_week"]:
            text += " Esta semana aún no has publicado: ¡que no se corte!"
        return text
    gap = streak["weeks_without"]
    return (
        f"⚠️ Llevas {gap} semana{'' if gap == 1 else 's'} sin publicar vídeo largo. Publicar "
        "cada semana es lo que más ayuda a crecer al principio."
    )


STREAK_FRESH = timedelta(days=2)  # cifras de YouTube de hace menos de esto: al día


def stats_are_fresh(db: Session, now: datetime | None = None) -> bool:
    """¿Las cifras de YouTube se leyeron hace poco? (Si no, falta información reciente.)"""
    from app.analytics import _when

    last = _when(get_setting(db, "analytics_last"))
    return last is not None and (now or datetime.now()) - last < STREAK_FRESH


def channel_plans(db: Session) -> list[dict]:
    """Con dos canales o más: qué vídeo largo toca en cada uno y cuántos Shorts suyos
    quedan por subir. Con uno solo, nada (el plan de siempre ya lo dice)."""
    channels = db.scalars(select(Channel).order_by(Channel.id)).all()
    if len(channels) < 2:
        return []
    ready = ready_to_upload(db)
    published = _published_ids(db)
    plans = []
    for channel in channels:
        mine = [p for p in ready if p.channel_id == channel.id]
        if mine:
            long_text = f"Sube «{mine[0].title}»"
        else:
            long_text = "No hay ningún vídeo en marcha: empieza uno"
            for project in db.scalars(
                select(Project)
                .where(Project.channel_id == channel.id)
                .order_by(Project.id.desc())
                .limit(200)  # todos los de este canal: uno viejo a medias también cuenta
            ):
                if project.id in published or project.status == "Publicado":
                    continue
                step = project_step(db, project)
                if step["stage"] == "upload":
                    long_text = f"Sube «{project.title}»"
                elif step["stage"]:
                    long_text = f"Termina «{project.title}»: {step['text']}"
                else:  # trabajando solo: no hace falta nada ahora
                    long_text = f"«{project.title}» se está haciendo solo"
                break
        own_shorts = _shorts_queue(db, channel.id)
        plans.append(
            {
                "channel": channel.name,
                "long": long_text,
                "shorts": len(own_shorts),
                "next_short": own_shorts[0]["title"] if own_shorts else None,
            }
        )
    return plans


def today_text(db: Session, now: datetime | None = None) -> str:
    """Lo que toca publicar hoy (para el resumen de la mañana)."""
    now = now or datetime.now()
    plan = weekly_plan(db, now)
    lines = []
    if plan["today_publish"]:
        lines.append(f"🚀 Hoy toca publicar «{plan['ready']}» a las {plan['publish_hour']}:00.")
    if plan["today_short"]:
        lines.append(f"📱 Hoy toca un Short: «{plan['today_short']}».")
    return "\n".join(lines)


def week_days(db: Session, now: datetime | None = None) -> list[dict]:
    """Los próximos 7 días, cada uno con lo que toca: vídeo largo, Short y aprendizaje."""
    from app.agenda import WEEKDAYS

    now = now or datetime.now()
    plan = weekly_plan(db, now)
    shorts = dict(plan["shorts"])  # «miércoles (hoy)» → título
    days = []
    for offset in range(7):
        date = now + timedelta(days=offset)
        weekday = date.weekday()
        name = WEEKDAYS[weekday] + (" (hoy)" if offset == 0 else "")
        items = []
        if weekday == plan["publish_day"]:
            if plan["ready"]:
                items.append(
                    {
                        "kind": "long",
                        "text": f"Subir «{plan['ready']}» a las {plan['publish_hour']}:00",
                    }
                )
            else:
                items.append({"kind": "long", "text": plan["long"]})
        if name in shorts:
            items.append({"kind": "short", "text": f"Short: «{shorts[name]}»"})
        elif weekday in SHORTS_DAYS:
            items.append({"kind": "short", "text": "Short (aún no hay ninguno preparado)"})
        items.append({"kind": "learn", "text": LEARNING[weekday]})
        days.append(
            {"name": name, "date": date.strftime("%d/%m"), "today": offset == 0, "items": items}
        )
    return days


# Palabras con mayúscula que no son un protagonista (salen en muchos nombres o al principio
# de una frase): no cuentan para decir que dos vídeos tratan de lo mismo.
GENERIC_NAMES = {
    "real", "banco", "grupo", "club", "casa", "compania", "empresa", "imperio", "marca",
    "quiero", "habla", "video", "historia", "caida", "auge", "como", "por",
}  # fmt: skip


def subject_words(text: str) -> set[str]:
    """Los nombres propios del protagonista: los de antes de «:» (si hay) o los de todo el
    texto. «La historia de Gareth Bale: del Southampton al Madrid» → {gareth, bale}.
    «Coca-Cola» cuenta como un solo nombre y las siglas cortas (LG, HP) también cuentan."""
    from app.pipeline.monetization import _plain, title_brands

    head = (text or "").split(":", 1)[0]
    head = re.sub(r"(?<=\w)-(?=[A-ZÁÉÍÓÚÑ])", "", head)  # Coca-Cola → CocaCola
    words = set(title_brands(head))
    words |= {_plain(a) for a in re.findall(r"\b[A-Z]{2}\b", head)}  # LG, HP, VW…
    return words - GENERIC_NAMES


def similar_projects(db: Session, project: Project, limit: int = 3) -> list[Project]:
    """Otros vídeos del mismo canal sobre el mismo protagonista (para no repetir sin
    querer). Coinciden si los nombres de uno están todos en los del otro."""

    def words(p: Project) -> set[str]:  # el título manda; el tema, solo si no hay nombres
        return subject_words(p.title) or subject_words(p.topic)

    mine = words(project)
    if not mine:
        return []
    found = []
    others = select(Project).where(
        Project.channel_id == project.channel_id, Project.id != project.id
    )
    for other in db.scalars(others.order_by(Project.id.desc())):
        theirs = words(other)
        # El mismo protagonista: uno dentro del otro y, como mucho, un nombre de diferencia
        # («Pepsi» y «Coca-Cola contra Pepsi» sí; «Nike» y «Nike, Adidas y Puma» no).
        if theirs and (theirs <= mine or mine <= theirs) and len(theirs ^ mine) <= 1:
            found.append(other)
            if len(found) >= limit:
                break
    return found
