"""Páginas de cada etapa del proyecto: investigación, estrategia y guion."""

import copy
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select

from app import jobs
from app.auth import DB, CurrentUser
from app.media import project_dir, safe_path
from app.models import LEVELS, SCRIPT_TONES, STAGES, Project, StageResult
from app.pipeline.script import SECTION_LABELS, default_params, rewrite_paragraph, with_stats
from app.pipeline.storyboard import paragraphs_of, stale_scenes
from app.pipeline.voice import take_key
from app.providers.ai import ProviderError
from app.providers.voice import SPEEDS, VOICE_IDS, VOICES
from app.settings_store import api_key_hint
from app.templating import render

router = APIRouter(prefix="/proyectos/{project_id}")

# Dirección de cada etapa en la web.
SLUGS = {
    "research": "investigacion",
    "strategy": "estrategia",
    "script": "guion",
    "storyboard": "escenas",
    "voice": "voz",
    "visuals": "visuales",
    "edit": "video",
}
STAGE_BY_SLUG = {slug: stage for stage, slug in SLUGS.items()}


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _project(db: DB, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")
    return project


def _result_row(db: DB, project_id: int, stage: str) -> StageResult | None:
    return db.scalar(
        select(StageResult).where(StageResult.project_id == project_id, StageResult.stage == stage)
    )


def _stage_page(request: Request, db: DB, project: Project, stage: str, **ctx):
    all_jobs = jobs.latest_jobs(db, project.id)
    results = {
        r.stage: r.data
        for r in db.scalars(select(StageResult).where(StageResult.project_id == project.id))
    }
    return render(
        request,
        f"stage_{stage}.html",
        status_code=ctx.pop("status_code", 200),
        project=project,
        stage=stage,
        stages=STAGES,
        slugs=SLUGS,
        jobs=all_jobs,
        job=all_jobs.get(stage),
        results=results,
        result=results.get(stage),
        has_gemini=api_key_hint(db, "gemini") is not None,
        **ctx,
    )


@router.get("/investigacion")
def research_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    return _stage_page(request, db, _project(db, project_id), "research")


@router.get("/estrategia")
def strategy_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    return _stage_page(request, db, _project(db, project_id), "strategy")


@router.get("/guion")
def script_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    script = jobs.get_result(db, project_id, "script")
    return _stage_page(
        request,
        db,
        project,
        "script",
        tones=SCRIPT_TONES,
        levels=LEVELS,
        labels=SECTION_LABELS,
        params=(script or {}).get("params") or default_params(),
    )


@router.get("/escenas")
def storyboard_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard")
    script = jobs.get_result(db, project_id, "script")
    stale = stale_scenes(board, script) if board and script else {"changed": [], "new": []}
    return _stage_page(request, db, project, "storyboard", stale=stale, labels=SECTION_LABELS)


def _voice_context(db: DB, project: Project) -> dict:
    script = jobs.get_result(db, project.id, "script") or {}
    voice = jobs.get_result(db, project.id, "voice")
    params = jobs.voice_params(db, project, voice)
    takes = {t["paragraph_id"]: t for t in (voice or {}).get("takes", [])}
    paragraphs = []
    for p in paragraphs_of(script):
        take = takes.get(p["id"])
        current = take and take["key"] == take_key(p["text"], params["voice"], params["speed"])
        paragraphs.append({**p, "take": take, "outdated": bool(take) and not current})
    sample = project_dir(project.id) / "voz" / "muestra.wav"
    return {
        "voices": VOICES,
        "speeds": list(SPEEDS),
        "params": params,
        "paragraphs": paragraphs,
        "pending": sum(1 for p in paragraphs if not p["take"] or p["outdated"]),
        "has_sample": sample.exists(),
    }


@router.get("/voz")
def voice_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    return _stage_page(request, db, project, "voice", **_voice_context(db, project))


def make_sample(text: str, voice: str, speed: str) -> bytes:
    """Graba una muestra corta. Se reemplaza en los tests."""
    return jobs.get_voice_provider().synthesize(text, voice, speed)


@router.post("/voz/muestra")
def voice_sample(
    request: Request,
    db: DB,
    user: CurrentUser,
    project_id: int,
    voice: Annotated[str, Form()],
    speed: Annotated[str, Form()] = "Normal",
):
    project = _project(db, project_id)
    if voice not in VOICE_IDS or speed not in SPEEDS:
        raise HTTPException(400, "Voz no válida")
    script = jobs.get_result(db, project_id, "script") or {}
    first = next(iter(paragraphs_of(script)), None)
    text = (first or {}).get("text") or "Hola, esta es una muestra de la voz que narrará tu vídeo."
    try:
        audio = make_sample(text[:300], voice, speed)
    except ProviderError as exc:
        ctx = _voice_context(db, project)
        return _stage_page(request, db, project, "voice", status_code=400, error=str(exc), **ctx)
    folder = project_dir(project_id) / "voz"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "muestra.wav").write_bytes(audio)
    from app.settings_store import set_setting

    set_setting(db, "voice_default", voice)
    return _redirect(f"/proyectos/{project_id}/voz?muestra={voice}-{speed}#muestra")


@router.get("/archivos/{path:path}")
def project_file(db: DB, user: CurrentUser, project_id: int, path: str):
    _project(db, project_id)
    target = safe_path(project_id, path)
    if target is None:
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(target)


@router.get("/visuales")
def visuals_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard") or {}
    visuals = jobs.get_result(db, project_id, "visuals") or {}
    rows = [
        {"scene": scene, "visual": visuals.get("items", {}).get(scene["paragraph_id"])}
        for scene in board.get("scenes", [])
    ]
    return _stage_page(
        request,
        db,
        project,
        "visuals",
        rows=rows,
        has_stock=bool(jobs.get_stock_providers(db)),
    )


@router.post("/visuales/cambiar/{paragraph_id}")
def change_visual(db: DB, user: CurrentUser, project_id: int, paragraph_id: str):
    """Busca otro visual solo para esta escena (salta los resultados ya vistos)."""
    _project(db, project_id)
    visuals = jobs.get_result(db, project_id, "visuals") or {}
    entry = visuals.get("items", {}).get(paragraph_id) or {}
    skip = entry.get("skip", 0) + 1 if entry.get("provider") else 0
    jobs.enqueue(db, project_id, "visuals", {"only": [paragraph_id], "skip": {paragraph_id: skip}})
    return _redirect(f"/proyectos/{project_id}/visuales#escena-{paragraph_id}")


@router.get("/video")
def video_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    folder = project_dir(project_id) / "video"
    return _stage_page(
        request,
        db,
        project,
        "edit",
        has_srt=(folder / "subtitulos.srt").exists(),
        has_credits=(folder / "creditos.txt").exists()
        and (folder / "creditos.txt").read_text(encoding="utf-8").strip() != "",
    )


@router.post("/etapas/{stage}")
def run_stage(
    db: DB,
    user: CurrentUser,
    project_id: int,
    stage: str,
    tone: Annotated[str | None, Form()] = None,
    drama: Annotated[str | None, Form()] = None,
    technical: Annotated[str | None, Form()] = None,
    voice: Annotated[str | None, Form()] = None,
    speed: Annotated[str | None, Form()] = None,
    quality: Annotated[str | None, Form()] = None,
):
    _project(db, project_id)
    if stage not in jobs.RUNNERS:
        raise HTTPException(404, "Esta etapa todavía no está disponible")
    params = None
    if stage == "script":
        defaults = default_params()
        params = {
            "tone": tone if tone in SCRIPT_TONES else defaults["tone"],
            "drama": drama if drama in LEVELS else defaults["drama"],
            "technical": technical if technical in LEVELS else defaults["technical"],
        }
    elif stage == "edit":
        params = {"quality": quality if quality in ("preview", "final") else "preview"}
    elif stage == "voice":
        params = {
            "voice": voice if voice in VOICE_IDS else None,
            "speed": speed if speed in SPEEDS else None,
        }
    jobs.enqueue(db, project_id, stage, params)
    return _redirect(f"/proyectos/{project_id}/{SLUGS[stage]}")


@router.post("/estrategia/elegir")
def choose_concept(
    db: DB,
    user: CurrentUser,
    project_id: int,
    concept: Annotated[int, Form()],
    title: Annotated[int, Form()] = 0,
):
    _project(db, project_id)
    row = _result_row(db, project_id, "strategy")
    if row is None:
        raise HTTPException(404, "Todavía no hay propuestas")
    data = copy.deepcopy(row.data)
    if not (0 <= concept < len(data["concepts"])):
        raise HTTPException(400, "Enfoque no válido")
    if not (0 <= title < len(data["concepts"][concept]["titles"])):
        title = 0
    data["selected"] = {"concept": concept, "title": title}
    row.data = data
    db.commit()
    return _redirect(f"/proyectos/{project_id}/guion")


PARAGRAPH_ACTIONS = {"save", "delete", "regenerate", "expand", "summarize", "tone"}


def rewrite_with_ai(db, project, research, script, paragraph_id, action, tone):
    """Llama a la IA para un párrafo. Se reemplaza en los tests."""
    ai = jobs.get_ai_provider(db)
    updated = rewrite_paragraph(project, research, script, paragraph_id, action, ai, tone)
    jobs.remember_working_model(db, ai)
    return updated


@router.post("/guion/parrafos/{paragraph_id}")
def edit_paragraph(
    request: Request,
    db: DB,
    user: CurrentUser,
    project_id: int,
    paragraph_id: str,
    action: Annotated[str, Form()],
    text: Annotated[str, Form()] = "",
    tone: Annotated[str | None, Form()] = None,
):
    project = _project(db, project_id)
    row = _result_row(db, project_id, "script")
    if row is None or action not in PARAGRAPH_ACTIONS:
        raise HTTPException(404, "No encontrado")
    script = copy.deepcopy(row.data)
    found = next(
        (
            (section, paragraph)
            for section in script["sections"]
            for paragraph in section["paragraphs"]
            if paragraph["id"] == paragraph_id
        ),
        None,
    )
    if found is None:
        raise HTTPException(404, "Párrafo no encontrado")
    section, paragraph = found

    if action == "save":
        if text.strip():
            paragraph["text"] = text.strip()
        script = with_stats(script)
    elif action == "delete":
        section["paragraphs"].remove(paragraph)
        script = with_stats(script)
    else:
        research = jobs.get_result(db, project_id, "research") or {}
        try:
            script = rewrite_with_ai(db, project, research, script, paragraph_id, action, tone)
        except ProviderError as exc:
            return _stage_page(
                request,
                db,
                project,
                "script",
                status_code=400,
                tones=SCRIPT_TONES,
                levels=LEVELS,
                labels=SECTION_LABELS,
                params=script.get("params") or default_params(),
                error=f"No se pudo cambiar el párrafo: {exc}",
            )
    row.data = script
    db.commit()
    return _redirect(f"/proyectos/{project_id}/guion#p-{paragraph_id}")
