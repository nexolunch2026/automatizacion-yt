from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import jobs
from app.auth import DB, CurrentUser
from app.models import (
    AUTOMATION_MODES,
    DURATIONS,
    LANGUAGES,
    STAGES,
    VIDEO_TYPES,
    Channel,
    Project,
    StageResult,
)
from app.settings_store import api_key_hint
from app.stages_web import SLUGS
from app.templating import render

router = APIRouter()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------- Dashboard ----------


@router.get("/")
def dashboard(request: Request, db: DB, user: CurrentUser, canal: int | None = None):
    channels = db.scalars(select(Channel).order_by(Channel.name)).all()
    query = (
        select(Project)
        .options(selectinload(Project.channel), selectinload(Project.author))
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    if canal:
        query = query.where(Project.channel_id == canal)
    projects = db.scalars(query).all()
    return render(
        request, "dashboard.html", channels=channels, projects=projects, selected_channel=canal
    )


# ---------- Canales ----------


@router.get("/canales")
def channels_page(request: Request, db: DB, user: CurrentUser):
    channels = db.scalars(
        select(Channel).options(selectinload(Channel.projects)).order_by(Channel.name)
    ).all()
    return render(request, "channels.html", channels=channels, languages=LANGUAGES)


@router.post("/canales")
def create_channel(
    request: Request,
    db: DB,
    user: CurrentUser,
    name: Annotated[str, Form()],
    niche: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "Español",
):
    name = name.strip()
    if not name or language not in LANGUAGES:
        channels = db.scalars(select(Channel).order_by(Channel.name)).all()
        return render(
            request,
            "channels.html",
            status_code=400,
            channels=channels,
            languages=LANGUAGES,
            error="Escribe un nombre para el canal.",
        )
    db.add(
        Channel(name=name[:100], niche=niche.strip()[:200], language=language, created_by=user.id)
    )
    db.commit()
    return _redirect("/canales")


# ---------- Proyectos ----------


def _project_form_context(db: DB) -> dict:
    return {
        "channels": db.scalars(select(Channel).order_by(Channel.name)).all(),
        "durations": DURATIONS,
        "languages": LANGUAGES,
        "video_types": VIDEO_TYPES,
        "modes": AUTOMATION_MODES,
    }


@router.get("/proyectos/nuevo")
def new_project_page(request: Request, db: DB, user: CurrentUser):
    ctx = _project_form_context(db)
    if not ctx["channels"]:
        return _redirect("/canales?primero=1")
    return render(request, "project_new.html", form={}, **ctx)


@router.post("/proyectos/nuevo")
def create_project(
    request: Request,
    db: DB,
    user: CurrentUser,
    channel_id: Annotated[int, Form()],
    topic: Annotated[str, Form()],
    duration: Annotated[str, Form()],
    language: Annotated[str, Form()],
    video_type: Annotated[str, Form()],
    automation_mode: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
):
    form = {
        "channel_id": channel_id,
        "topic": topic.strip(),
        "title": title.strip(),
        "duration": duration,
        "language": language,
        "video_type": video_type,
        "automation_mode": automation_mode,
    }
    error = None
    if not form["topic"]:
        error = "Escribe la idea o el tema del vídeo."
    elif db.get(Channel, channel_id) is None:
        error = "Elige un canal."
    elif (
        duration not in DURATIONS
        or language not in LANGUAGES
        or video_type not in VIDEO_TYPES
        or automation_mode not in AUTOMATION_MODES
    ):
        error = "Alguna opción no es válida."
    if error:
        return render(
            request,
            "project_new.html",
            status_code=400,
            error=error,
            form=form,
            **_project_form_context(db),
        )

    project = Project(
        channel_id=channel_id,
        title=(form["title"] or form["topic"])[:200],
        topic=form["topic"],
        duration=duration,
        language=language,
        video_type=video_type,
        automation_mode=automation_mode,
        created_by=user.id,
    )
    db.add(project)
    db.commit()
    return _redirect(f"/proyectos/{project.id}")


def _get_project(db: DB, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")
    return project


@router.get("/proyectos/{project_id}")
def project_detail(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _get_project(db, project_id)
    results = {
        r.stage: r.data
        for r in db.scalars(select(StageResult).where(StageResult.project_id == project_id))
    }
    return render(
        request,
        "project_detail.html",
        project=project,
        stages=STAGES,
        modes=AUTOMATION_MODES,
        jobs=jobs.latest_jobs(db, project_id),
        results=results,
        runnable=set(jobs.RUNNERS),
        slugs=SLUGS,
        has_gemini=api_key_hint(db, "gemini") is not None,
    )


@router.get("/proyectos/{project_id}/estado")
def project_status(db: DB, user: CurrentUser, project_id: int) -> dict:
    """Estado de las tareas; la página lo consulta cada pocos segundos."""
    _get_project(db, project_id)
    return {
        stage: {
            "status": j.status,
            "progress": j.progress,
            "message": j.message,
            "error": j.error,
        }
        for stage, j in jobs.latest_jobs(db, project_id).items()
    }


@router.post("/proyectos/{project_id}/borrar")
def delete_project(db: DB, user: CurrentUser, project_id: int):
    db.delete(_get_project(db, project_id))
    db.commit()
    return _redirect("/")
