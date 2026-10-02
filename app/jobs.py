"""Tareas en segundo plano.

Las tareas se guardan en la base de datos, así que si el programa se cierra a mitad,
al volver a abrirlo se retoman. Un único trabajador las ejecuta de una en una.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import STATUSES, Job, Project, StageResult
from app.pipeline.research import run_research
from app.pipeline.script import default_params, run_script
from app.pipeline.strategy import run_strategy
from app.providers.ai import AIProvider, GeminiProvider, ProviderError
from app.providers.search import SearchProvider, WikipediaSearch
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
RETRY_DELAYS = [timedelta(seconds=30), timedelta(seconds=90), timedelta(minutes=3)]

# Estado del proyecto cuando termina cada etapa.
STAGE_DONE_STATUS = {"research": "Investigación", "script": "Guion"}
# Qué etapa sigue a cada una (para los modos asistido y automático).
NEXT_STAGE = {"research": "strategy", "strategy": "script"}


def get_result(db: Session, project_id: int, stage: str) -> dict | None:
    result = db.scalar(
        select(StageResult).where(StageResult.project_id == project_id, StageResult.stage == stage)
    )
    return result.data if result else None


def _require(db: Session, project: Project, stage: str, message: str) -> dict:
    data = get_result(db, project.id, stage)
    if data is None:
        raise ProviderError(message)
    return data


def get_ai_provider(db: Session) -> AIProvider:
    key = get_api_key(db, "gemini")
    if not key:
        raise ProviderError("Falta la clave de Gemini. Añádela en Configuración.")
    return GeminiProvider(key, preferred=get_setting(db, "gemini_model"))


def remember_working_model(db: Session, ai: AIProvider) -> None:
    """Guarda el modelo que funcionó para usarlo primero la próxima vez."""
    model = getattr(ai, "last_model", None)
    if model and get_setting(db, "gemini_model") != model:
        set_setting(db, "gemini_model", model)


def get_search_provider() -> SearchProvider:
    return WikipediaSearch()


def _run_research(db: Session, project: Project, progress, params: dict) -> dict:
    ai = get_ai_provider(db)
    data = run_research(project, ai, progress, get_search_provider())
    remember_working_model(db, ai)
    return data


def _run_strategy(db: Session, project: Project, progress, params: dict) -> dict:
    research = _require(db, project, "research", "Primero hay que investigar el tema.")
    ai = get_ai_provider(db)
    data = run_strategy(project, research, ai, progress)
    remember_working_model(db, ai)
    if project.automation_mode == "automatico" and data["concepts"]:
        data["selected"] = {"concept": 0, "title": 0, "auto": True}
    return data


def _run_script(db: Session, project: Project, progress, params: dict) -> dict:
    research = _require(db, project, "research", "Primero hay que investigar el tema.")
    strategy = _require(db, project, "strategy", "Primero hay que crear la estrategia.")
    if not strategy.get("selected"):
        raise ProviderError("Primero elige uno de los enfoques en la página de Estrategia.")
    ai = get_ai_provider(db)
    data = run_script(project, research, strategy, ai, params or default_params(), progress)
    remember_working_model(db, ai)
    return data


Runner = Callable[[Session, Project, Callable[[int, str], None], dict], dict]
RUNNERS: dict[str, Runner] = {
    "research": _run_research,
    "strategy": _run_strategy,
    "script": _run_script,
}


def enqueue(db: Session, project_id: int, stage: str, params: dict | None = None) -> Job:
    """Añade una tarea a la cola. Si ya hay una igual en marcha, devuelve esa."""
    if stage not in RUNNERS:
        raise ValueError(f"Etapa desconocida: {stage}")
    existing = db.scalar(
        select(Job).where(
            Job.project_id == project_id,
            Job.stage == stage,
            Job.status.in_(("queued", "running")),
        )
    )
    if existing:
        return existing
    job = Job(project_id=project_id, stage=stage, params=params)
    db.add(job)
    db.commit()
    return job


def latest_jobs(db: Session, project_id: int) -> dict[str, Job]:
    jobs = db.scalars(select(Job).where(Job.project_id == project_id).order_by(Job.id)).all()
    return {job.stage: job for job in jobs}  # el último de cada etapa gana


def recover_interrupted() -> None:
    """Las tareas que estaban en marcha cuando se cerró el programa vuelven a la cola."""
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status == "running")):
            job.status, job.message = "queued", "Reanudando tras un cierre"
        db.commit()


def process_next_job() -> bool:
    """Ejecuta la siguiente tarea pendiente. Devuelve False si no había ninguna."""
    with SessionLocal() as db:
        now = datetime.now()
        job = db.scalar(
            select(Job)
            .where(Job.status == "queued", or_(Job.run_after.is_(None), Job.run_after <= now))
            .order_by(Job.id)
            .limit(1)
        )
        if job is None:
            return False
        project = db.get(Project, job.project_id)
        job.status, job.attempts, job.error = "running", job.attempts + 1, None
        db.commit()

        def progress(pct: int, message: str) -> None:
            job.progress, job.message = pct, message
            db.commit()

        try:
            data = RUNNERS[job.stage](db, project, progress, job.params or {})
        except Exception as exc:  # noqa: BLE001 — cualquier fallo debe quedar registrado
            _handle_failure(db, job, exc)
            return True

        _save_result(db, project, job.stage, data)
        job.status, job.progress, job.message = "done", 100, "Terminado"
        job.finished_at = datetime.now()
        db.commit()
        _chain_next(db, project, job.stage, data)
        return True


def _chain_next(db: Session, project: Project, stage: str, data: dict) -> None:
    """Asistido: tras investigar, la IA prepara las propuestas y espera tu elección.
    Automático: sigue sola hasta el final de lo que ya está disponible."""
    next_stage = NEXT_STAGE.get(stage)
    if next_stage is None or project.automation_mode == "manual":
        return
    if project.automation_mode == "asistido" and stage != "research":
        return
    if next_stage == "script" and not data.get("selected"):
        return
    enqueue(db, project.id, next_stage)


def _save_result(db: Session, project: Project, stage: str, data: dict) -> None:
    result = db.scalar(
        select(StageResult).where(StageResult.project_id == project.id, StageResult.stage == stage)
    )
    if result is None:
        db.add(StageResult(project_id=project.id, stage=stage, data=data))
    else:
        result.data = data
    target = STAGE_DONE_STATUS.get(stage)
    if target and STATUSES.index(project.status) < STATUSES.index(target):
        project.status = target


def _handle_failure(db: Session, job: Job, exc: Exception) -> None:
    transient = isinstance(exc, ProviderError) and exc.transient
    message = str(exc) if isinstance(exc, ProviderError) else "Error inesperado"
    if not isinstance(exc, ProviderError):
        log.exception("Fallo inesperado en la tarea %s", job.id)

    if transient and job.attempts < MAX_ATTEMPTS:
        delay = RETRY_DELAYS[min(job.attempts - 1, len(RETRY_DELAYS) - 1)]
        job.status = "queued"
        job.run_after = datetime.now() + delay
        job.message = f"{message} Reintento {job.attempts + 1} de {MAX_ATTEMPTS}…"
    else:
        detail = exc.detail if isinstance(exc, ProviderError) else repr(exc)
        job.status, job.message = "failed", "Falló"
        # El detalle técnico va tras una línea en blanco; la página lo muestra plegado.
        job.error = f"{message}\n\n{detail}"[:900] if detail else message
        job.finished_at = datetime.now()
    db.commit()


class Worker(threading.Thread):
    def __init__(self, poll_seconds: float = 1.0):
        super().__init__(name="faceless-worker", daemon=True)
        self._stop_event = threading.Event()
        self._poll = poll_seconds

    def run(self) -> None:
        recover_interrupted()
        while not self._stop_event.is_set():
            try:
                worked = process_next_job()
            except Exception:  # noqa: BLE001 — el trabajador nunca debe morir
                log.exception("Error en el trabajador")
                worked = False
            if not worked:
                self._stop_event.wait(self._poll)

    def stop(self) -> None:
        self._stop_event.set()
