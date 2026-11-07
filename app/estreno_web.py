"""Página «Preparar el estreno» (la claqueta) y sus botones."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import estreno, jobs
from app.auth import DB, CurrentUser
from app.models import Project
from app.templating import render

router = APIRouter(prefix="/proyectos/{project_id}/estreno")


def _project(db, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")
    return project


def _back(project_id: int, toast: str = "") -> RedirectResponse:
    query = f"?aviso={toast}" if toast else ""
    return RedirectResponse(f"/proyectos/{project_id}/estreno{query}", status_code=303)


TOASTS = {
    "aprobado": "Aprobado: queda apuntado a tu nombre",
    "quitado": "Aprobación quitada",
    "fecha": "Fecha guardada",
    "carpeta": "Carpeta para subir lista",
}


@router.get("")
def launch_page(
    request: Request, db: DB, user: CurrentUser, project_id: int, aviso: str = ""
):  # fmt: skip
    from app.web import _thumb_url

    project = _project(db, project_id)
    data = estreno.get(db, project_id)
    lines = estreno.checklist(db, project)
    people = estreno.approvals_view(db, project_id)
    done = sum(line["ok"] for line in lines) + all(p["ok"] for p in people)
    chosen = data.get("date")
    seo = jobs.get_result(db, project_id, "publish") or {}
    return render(
        request,
        "estreno.html",
        project=project,
        lines=lines,
        people=people,
        me=user,
        done=done,
        total=len(lines) + 1,
        slots=estreno.next_slots(db, project),
        chosen=chosen,
        chosen_text=estreno.nice_date(date.fromisoformat(chosen)) if chosen else "",
        thumb=_thumb_url(db, project_id),
        title=(seo.get("titles") or [project.title])[0],
        folder=data.get("folder"),
        toast=TOASTS.get(aviso, ""),
        stale=jobs.stale_stages(db, project_id),
    )


@router.post("/aprobar")
def approve(db: DB, user: CurrentUser, project_id: int, yes: Annotated[str, Form()] = "1"):
    _project(db, project_id)
    if not estreno._render(db, project_id):
        raise HTTPException(400, "Primero hay que montar el vídeo.")
    estreno.approve(db, project_id, user, yes == "1")
    return _back(project_id, "aprobado" if yes == "1" else "quitado")


@router.post("/fecha")
def choose_date(db: DB, user: CurrentUser, project_id: int, day: Annotated[str, Form()] = ""):
    _project(db, project_id)
    try:
        chosen = date.fromisoformat(day) if day else None
    except ValueError as exc:
        raise HTTPException(400, "Fecha no válida") from exc
    estreno.set_date(db, project_id, chosen)
    return _back(project_id, "fecha")


@router.post("/carpeta")
def make_folder(db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    try:
        estreno.prepare_folder(db, project)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _back(project_id, "carpeta")
