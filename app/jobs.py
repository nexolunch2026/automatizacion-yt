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
from app.providers.ai import AIProvider, GeminiProvider, ProviderError
from app.settings_store import get_api_key

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAYS = [timedelta(seconds=20), timedelta(seconds=60)]

# Estado del proyecto cuando termina cada etapa.
STAGE_DONE_STATUS = {"research": "Investigación"}


def get_ai_provider(db: Session) -> AIProvider:
    key = get_api_key(db, "gemini")
    if not key:
        raise ProviderError("Falta la clave de Gemini. Añádela en Configuración.")
    return GeminiProvider(key)


def _run_research(db: Session, project: Project, progress) -> dict:
    return run_research(project, get_ai_provider(db), progress)


RUNNERS: dict[str, Callable[[Session, Project, Callable[[int, str], None]], dict]] = {
    "research": _run_research,
}


def enqueue(db: Session, project_id: int, stage: str) -> Job:
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
    job = Job(project_id=project_id, stage=stage)
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
            data = RUNNERS[job.stage](db, project, progress)
        except Exception as exc:  # noqa: BLE001 — cualquier fallo debe quedar registrado
            _handle_failure(db, job, exc)
            return True

        _save_result(db, project, job.stage, data)
        job.status, job.progress, job.message = "done", 100, "Terminado"
        job.finished_at = datetime.now()
        db.commit()
        return True


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
        job.status, job.message = "failed", "Falló"
        job.error = message if isinstance(exc, ProviderError) else f"{message}: {exc}"[:500]
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
