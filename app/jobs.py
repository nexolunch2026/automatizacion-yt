"""Tareas en segundo plano.

Las tareas se guardan en la base de datos, así que si el programa se cierra a mitad,
al volver a abrirlo se retoman. Un único trabajador las ejecuta de una en una.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.media import music_library, music_path, project_dir
from app.models import STATUSES, Job, Project, StageResult
from app.pipeline.render import DEFAULT_STYLE, MUSIC_VOLUMES, QUALITIES, render_video
from app.pipeline.research import run_research
from app.pipeline.script import default_params, run_script
from app.pipeline.seo import run_seo
from app.pipeline.storyboard import run_storyboard
from app.pipeline.strategy import run_strategy
from app.pipeline.visuals import credits_text, run_visuals
from app.pipeline.voice import pending_characters, run_voice
from app.providers.ai import AIProvider, GeminiProvider, ProviderError
from app.providers.images import GeminiImages, ImageChain, PollinationsImages
from app.providers.search import SearchProvider, WikipediaSearch
from app.providers.stock import PexelsStock, PixabayStock, StockProvider
from app.providers.voice import (
    ElevenLabsVoices,
    PiperVoices,
    VoiceProvider,
    default_voice,
    is_eleven,
)
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
RETRY_DELAYS = [timedelta(seconds=30), timedelta(seconds=90), timedelta(minutes=3)]

# Estado del proyecto cuando termina cada etapa.
STAGE_DONE_STATUS = {
    "research": "Investigación",
    "script": "Guion",
    "storyboard": "Storyboard",
    "voice": "Producción",
    "edit": "Edición",
}
# Qué etapa sigue a cada una (para los modos asistido y automático).
NEXT_STAGE = {
    "research": "strategy",
    "strategy": "script",
    "script": "storyboard",
    "storyboard": "voice",
    "voice": "visuals",
    "visuals": "edit",
    "edit": "publish",
}


def get_result(db: Session, project_id: int, stage: str) -> dict | None:
    result = db.scalar(
        select(StageResult).where(StageResult.project_id == project_id, StageResult.stage == stage)
    )
    return result.data if result else None


def select_concept(db: Session, project_id: int, concept: int, title: int = 0) -> dict:
    """Guarda el enfoque (y el título) elegidos en la estrategia."""
    import copy

    row = db.scalar(
        select(StageResult).where(
            StageResult.project_id == project_id, StageResult.stage == "strategy"
        )
    )
    if row is None:
        raise ProviderError("Todavía no hay propuestas.")
    data = copy.deepcopy(row.data)
    if not 0 <= concept < len(data["concepts"]):
        raise ProviderError("Ese enfoque no existe.")
    if not 0 <= title < len(data["concepts"][concept]["titles"]):
        title = 0
    data["selected"] = {"concept": concept, "title": title}
    row.data = data
    db.commit()
    return data


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


_voices: VoiceProvider | None = None


def get_voice_provider(db: Session, voice: str, model: str | None = None) -> VoiceProvider:
    """ElevenLabs si la voz es de ElevenLabs; si no, Piper (una sola instancia, para no
    cargar la voz en memoria en cada tarea)."""
    if is_eleven(voice):
        key = get_api_key(db, "elevenlabs")
        if not key:
            raise ProviderError("Falta la clave de ElevenLabs. Añádela en Configuración.")
        return ElevenLabsVoices(key, model or "eleven_multilingual_v2")
    global _voices
    if _voices is None:
        _voices = PiperVoices()
    return _voices


_eleven_cache: dict[str, tuple[float, list[dict]]] = {}


def eleven_voices(db: Session) -> tuple[list[dict], str | None]:
    """Voces de la cuenta de ElevenLabs (se guardan 10 minutos en memoria)."""
    import time

    key = get_api_key(db, "elevenlabs")
    if not key:
        return [], None
    cached = _eleven_cache.get(key)
    if cached and time.time() - cached[0] < 600:
        return cached[1], None
    try:
        voices = ElevenLabsVoices(key).list_voices()
    except ProviderError as exc:
        return [], str(exc)
    _eleven_cache[key] = (time.time(), voices)
    return voices, None


def get_stock_providers(db: Session) -> list[StockProvider]:
    providers: list[StockProvider] = []
    if key := get_api_key(db, "pexels"):
        providers.append(PexelsStock(key))
    if key := get_api_key(db, "pixabay"):
        providers.append(PixabayStock(key))
    return providers


def voice_params(db: Session, project: Project, params: dict | None = None) -> dict:
    params = params or {}
    return {
        "voice": params.get("voice")
        or get_setting(db, "voice_default")
        or default_voice(project.language),
        "speed": params.get("speed") or "Normal",
        "model": params.get("model") or get_setting(db, "eleven_model") or "eleven_multilingual_v2",
    }


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


def _run_storyboard(db: Session, project: Project, progress, params: dict) -> dict:
    script = _require(db, project, "script", "Primero hay que escribir el guion.")
    ai = get_ai_provider(db)
    data = run_storyboard(project, script, ai, progress)
    remember_working_model(db, ai)
    return data


def _run_voice(db: Session, project: Project, progress, params: dict) -> dict:
    script = _require(db, project, "script", "Primero hay que escribir el guion.")
    chosen = voice_params(db, project, params)
    tts = get_voice_provider(db, chosen["voice"], chosen["model"])
    previous = get_result(db, project.id, "voice")
    if is_eleven(chosen["voice"]):
        _check_eleven_credits(tts, pending_characters(script, previous, chosen))
    elif hasattr(tts, "is_downloaded") and not tts.is_downloaded(chosen["voice"]):
        progress(3, "Descargando la voz (solo la primera vez, unos 60 MB)")
        tts.ensure_downloaded(chosen["voice"])
    folder = project_dir(project.id) / "voz"
    data = run_voice(project, script, previous, tts, chosen, folder, progress)
    set_setting(db, "voice_default", chosen["voice"])
    if is_eleven(chosen["voice"]):
        set_setting(db, "eleven_model", chosen["model"])
    return data


def _check_eleven_credits(tts, characters: int) -> None:
    """Antes de gastar nada, comprueba que hay créditos suficientes en ElevenLabs."""
    credits = tts.credits() if hasattr(tts, "credits") else None
    needed = tts.cost(characters) if hasattr(tts, "cost") else characters
    if credits is not None and needed > credits["left"]:
        raise ProviderError(
            f"No te alcanzan los créditos de ElevenLabs: hacen falta unos {needed} y te "
            f"quedan {credits['left']} este mes. Usa el modo «Ahorro», una voz de Piper "
            "(gratis) o amplía tu plan."
        )


def _run_publish(db: Session, project: Project, progress, params: dict) -> dict:
    script = _require(db, project, "script", "Primero hay que escribir el guion.")
    research = get_result(db, project.id, "research") or {}
    visuals = get_result(db, project.id, "visuals") or {"items": {}}
    ai = get_ai_provider(db)
    data = run_seo(
        project,
        script,
        research,
        get_result(db, project.id, "voice"),
        credits_text(visuals),
        any(e.get("ai") for e in visuals["items"].values()),
        ai,
        progress,
    )
    remember_working_model(db, ai)
    return data


def is_portrait(project: Project) -> bool:
    return project.duration == "Short"


def get_image_providers(db: Session) -> ImageChain:
    providers = []
    if key := get_api_key(db, "gemini"):
        providers.append(GeminiImages(key))
    providers.append(PollinationsImages(token=get_api_key(db, "pollinations")))
    return ImageChain(providers)


def _run_visuals(db: Session, project: Project, progress, params: dict) -> dict:
    board = _require(db, project, "storyboard", "Primero hay que crear las escenas.")
    folder = project_dir(project.id) / "visuales"
    only = set(params["only"]) if params.get("only") else None
    stock = get_stock_providers(db)
    # Sin clave de bancos de imágenes, se generan con IA.
    mode = params.get("mode") or ("stock" if stock else "ai")
    return run_visuals(
        board["scenes"],
        stock,
        is_portrait(project),
        folder,
        get_result(db, project.id, "visuals"),
        progress,
        only,
        params.get("skip"),
        mode=mode,
        images=get_image_providers(db) if mode == "ai" else None,
        visual_bible=board.get("visual_bible"),
    )


def render_style(db: Session, params: dict | None = None) -> dict:
    """Opciones de acabado: las de esta tarea, o las últimas que se usaron."""
    import json

    saved = get_setting(db, "render_style")
    style = {**DEFAULT_STYLE, **(json.loads(saved) if saved else {})}
    for key in ("subtitles", "film_look", "music", "music_volume"):
        if params and key in params:
            style[key] = params[key]
    if style["music"] == "auto":  # primera canción de la biblioteca
        library = music_library()
        style["music"] = library[0] if library else ""
    if style["music"] and style["music"] not in music_library():
        style["music"] = ""
    if style["music_volume"] not in MUSIC_VOLUMES:
        style["music_volume"] = "media"
    return style


def _run_edit(db: Session, project: Project, progress, params: dict) -> dict:
    board = _require(db, project, "storyboard", "Primero hay que crear las escenas.")
    voice = _require(db, project, "voice", "Primero hay que grabar la voz.")
    visuals = get_result(db, project.id, "visuals") or {"items": {}}
    scene_ids = [s["paragraph_id"] for s in board["scenes"]]
    take_ids = [t["paragraph_id"] for t in voice["takes"]]
    if scene_ids != take_ids:
        raise ProviderError(
            "Las escenas y la voz no coinciden (el guion cambió). Pulsa «Rehacer escenas» "
            "y luego «Grabar lo que falta» en la voz, y vuelve a montar el vídeo."
        )
    folder = project_dir(project.id)
    media = {}
    for pid, entry in visuals["items"].items():
        if entry.get("file") and (folder / "visuales" / entry["file"]).exists():
            media[pid] = {"path": folder / "visuales" / entry["file"], "kind": entry["kind"]}
    quality = params.get("quality") if params.get("quality") in QUALITIES else "preview"
    style = render_style(db, params)
    result = render_video(
        board["scenes"],
        media,
        {t["paragraph_id"]: t["seconds"] for t in voice["takes"]},
        folder / voice["full"],
        folder / "video",
        quality,
        is_portrait(project),
        progress,
        style=style,
        music=music_path(style["music"]),
    )
    try:  # los créditos no deben hacer fallar el montaje
        (folder / "video" / "creditos.txt").write_text(credits_text(visuals), encoding="utf-8")
    except OSError:
        log.warning("No se pudo escribir creditos.txt", exc_info=True)
    import json

    set_setting(db, "render_style", json.dumps(style))
    previous = get_result(db, project.id, "edit") or {}
    renders = {**previous.get("renders", {}), quality: result}
    return {"renders": renders, "last": quality}


Runner = Callable[[Session, Project, Callable[[int, str], None], dict], dict]
RUNNERS: dict[str, Runner] = {
    "research": _run_research,
    "strategy": _run_strategy,
    "script": _run_script,
    "storyboard": _run_storyboard,
    "voice": _run_voice,
    "visuals": _run_visuals,
    "edit": _run_edit,
    "publish": _run_publish,
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
    if stage == "edit" and get_result(db, project.id, "publish"):
        return  # rehacer el vídeo (p. ej. la versión final) no rehace los textos
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


def describe_unexpected(exc: Exception) -> str:
    """Detalle técnico de un error inesperado: tipo, archivo implicado y dónde ocurrió."""
    import traceback

    text = f"{type(exc).__name__}: {exc}"
    for attr in ("filename", "filename2"):
        if getattr(exc, attr, None):
            text += f" | archivo: {getattr(exc, attr)}"
    frames = traceback.extract_tb(exc.__traceback__)[-3:]
    where = " → ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames)
    return f"{text} | en: {where}" if where else text


def _handle_failure(db: Session, job: Job, exc: Exception) -> None:
    if isinstance(exc, PermissionError):
        # Windows bloquea archivos abiertos (un vídeo en el reproductor) o que el
        # antivirus está revisando. Suele resolverse solo: se reintenta.
        exc = ProviderError(
            "Windows no dejó escribir o borrar un archivo (puede que esté abierto en otro "
            "programa o que el antivirus lo esté revisando). Se volverá a intentar solo.",
            transient=True,
            detail=describe_unexpected(exc),
        )
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
        detail = exc.detail if isinstance(exc, ProviderError) else describe_unexpected(exc)
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
