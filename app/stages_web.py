"""Páginas de cada etapa del proyecto: investigación, estrategia y guion."""

import copy
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app import jobs
from app.auth import DB, CurrentUser
from app.models import LEVELS, SCRIPT_TONES, STAGES, Project, StageResult
from app.pipeline.script import SECTION_LABELS, default_params, rewrite_paragraph, with_stats
from app.providers.ai import ProviderError
from app.settings_store import api_key_hint
from app.templating import render

router = APIRouter(prefix="/proyectos/{project_id}")

# Dirección de cada etapa en la web.
SLUGS = {"research": "investigacion", "strategy": "estrategia", "script": "guion"}
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


@router.post("/etapas/{stage}")
def run_stage(
    db: DB,
    user: CurrentUser,
    project_id: int,
    stage: str,
    tone: Annotated[str | None, Form()] = None,
    drama: Annotated[str | None, Form()] = None,
    technical: Annotated[str | None, Form()] = None,
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
