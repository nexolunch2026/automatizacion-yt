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
