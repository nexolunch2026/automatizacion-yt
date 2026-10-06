"""JARVIS como entrenador del canal.

- `next_steps`: qué hay que hacer ahora en cada vídeo a medias (con un botón para hacerlo).
- `monetization_path`: cuánto falta para entrar en el Programa de Socios (suscriptores y
  horas de visualización) y qué conviene hacer para llegar antes.
- `review_project`: la nota del control de calidad de un vídeo.

Nada de esto gasta IA. Solo `monetization_path` lee el canal (con caché de 15 min).
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.models import STAGES, Project, Video
from app.pipeline.monetization import project_review, summary_text, video_seconds
from app.settings_store import get_setting

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
            "text": f"trabajando en {STAGES[job.stage].lower()} ({job.progress} %)",
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
SHORTS_DAYS = (0, 2, 5)  # lunes, miércoles y sábado: 3 Shorts por semana
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


def _shorts_queue(db: Session) -> list[str]:
    """Títulos de los Shorts preparados, empezando por los del vídeo más reciente."""
    titles = []
    for project in db.scalars(select(Project).order_by(Project.id.desc()).limit(10)):
        for short in (jobs.get_result(db, project.id, "shorts") or {}).get("shorts", []):
            titles.append(short.get("title") or project.title)
    return titles


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
    short_days = [d for d in upcoming if d in SHORTS_DAYS]
    schedule = list(zip(short_days, shorts, strict=False))
    return {
        "publish_day": day,
        "publish_hour": hour,
        "long": long_text,
        "shorts": [
            (WEEKDAYS[d] + (" (hoy)" if d == now.weekday() else ""), title) for d, title in schedule
        ],
        "learning": LEARNING[now.weekday()],
        "today_publish": now.weekday() == day and bool(ready),
        "today_short": next((t for d, t in schedule if d == now.weekday()), None),
        "ready": ready[0].title if ready else None,
    }


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
