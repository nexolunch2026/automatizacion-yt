"""Página «Rendimiento»: cómo le va a cada vídeo publicado y qué aprende JARVIS."""

import json
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app import analytics, info, jobs
from app.auth import DB, CurrentUser
from app.models import Project, Video
from app.providers.ai import ProviderError
from app.settings_store import api_key_hint, get_setting
from app.templating import render

router = APIRouter()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def sparkline(points: list, width: int = 120, height: int = 32) -> str:
    """Mini gráfica SVG (solo puntos de la línea) de una serie de valores."""
    values = [p[1] for p in points if p[1] is not None]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    return " ".join(
        f"{i * step:.1f},{height - 2 - (v - low) / span * (height - 4):.1f}"
        for i, v in enumerate(values)
    )


@router.get("/rendimiento")
def performance_page(request: Request, db: DB, user: CurrentUser):
    rows = analytics.video_rows(db)
    for row in rows:
        row["spark"] = sparkline(row["history"])
    subs = json.loads(get_setting(db, "subs_history") or "[]")
    projects = db.scalars(select(Project).order_by(Project.id.desc())).all()
    return render(
        request,
        "performance.html",
        rows=rows,
        channel=info.youtube(db),
        subs=subs,
        subs_spark=sparkline(subs, 260, 48),
        insight=analytics.last_insight(db),
        last=get_setting(db, "analytics_last"),
        has_key=api_key_hint(db, "youtube") is not None,
        has_gemini=api_key_hint(db, "gemini") is not None,
        projects=projects,
        error=request.query_params.get("error"),
    )


@router.post("/rendimiento/actualizar")
def refresh_now(db: DB, user: CurrentUser):
    try:
        count = analytics.refresh(db)
    except Exception as exc:  # noqa: BLE001 — se muestra al usuario
        return _redirect(f"/rendimiento?error=No se pudieron leer las cifras ({exc})")
    if not count:
        return _redirect("/rendimiento?error=No encontré vídeos publicados en tu canal.")
    return _redirect("/rendimiento")


@router.post("/rendimiento/analizar")
def analyze_now(db: DB, user: CurrentUser):
    try:
        ai = jobs.get_ai_provider(db)
        analytics.analyze(db, ai)
        jobs.remember_working_model(db, ai)
    except (ProviderError, ValueError) as exc:
        return _redirect(f"/rendimiento?error={exc}")
    return _redirect("/rendimiento#analisis")


@router.post("/rendimiento/{video_id}")
def save_video_data(
    db: DB,
    user: CurrentUser,
    video_id: str,
    ctr: Annotated[str, Form()] = "",
    retention: Annotated[str, Form()] = "",
    project_id: Annotated[str, Form()] = "",
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Vídeo no encontrado")

    def number(text: str) -> float | None:
        text = text.replace(",", ".").replace("%", "").strip()
        try:
            value = float(text)
        except ValueError:
            return None
        return value if 0 <= value <= 100 else None

    video.ctr = number(ctr)
    video.retention = number(retention)
    video.project_id = (
        int(project_id) if project_id.isdigit() and db.get(Project, int(project_id)) else None
    )
    db.commit()
    return _redirect("/rendimiento")


@router.post("/proyectos/{project_id}/enlace-youtube")
def link_youtube(db: DB, user: CurrentUser, project_id: int, url: Annotated[str, Form()]):
    """Pegas el enlace del vídeo publicado y queda enlazado con este proyecto."""
    project = db.get(Project, project_id)
    video_id = analytics.parse_video_id(url)
    if project is None or video_id is None:
        raise HTTPException(400, "Ese enlace no parece de un vídeo de YouTube")
    video = db.get(Video, video_id) or Video(video_id=video_id, title=project.title)
    video.project_id = project.id
    db.merge(video)
    project.status = "Publicado"
    db.commit()
    return _redirect(f"/proyectos/{project_id}/publicacion")
