from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import jobs, profile, usage
from app.auth import DB, CurrentUser
from app.media import delete_project_files
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
from app.pipeline.monetization import project_review
from app.pipeline.script import FORMATS
from app.settings_store import api_key_hint, get_setting
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
        request,
        "dashboard.html",
        channels=channels,
        projects=projects,
        selected_channel=canal,
        needs_profile=not profile.is_set(db),
        thumbs={p.id: url for p in projects if (url := _thumb_url(db, p.id))},
        summary=_studio_summary(db, projects) if projects else None,
    )


def _thumb_url(db, project_id: int) -> str | None:
    """La miniatura elegida (o la primera) para la tarjeta del proyecto."""
    thumb = jobs.get_result(db, project_id, "thumbnail") or {}
    variants = thumb.get("variants") or []
    if not variants:
        return None
    chosen = thumb.get("selected")
    index = chosen if isinstance(chosen, int) and 0 <= chosen < len(variants) else 0
    return f"/proyectos/{project_id}/archivos/miniaturas/{variants[index]['file']}"


def _studio_summary(db, projects) -> dict:
    """Cifras de la portada y los siguientes pasos (sin ir a internet: carga al momento)."""
    from app import coach

    published = coach._published_ids(db)
    shown = {p.id for p in projects}
    working = sum(1 for p in projects if any(j.active for j in jobs.latest_jobs(db, p.id).values()))
    scores = []
    for p in projects[:6]:  # los más recientes (la revisión compara guiones: no muchos)
        if jobs.get_result(db, p.id, "script"):
            scores.append(project_review(db, p)["score"])
    return {
        "working": working,
        "ready": len(coach.ready_to_upload(db)),
        "published": len(published),
        "score": round(sum(scores) / len(scores)) if scores else None,
        # solo los vídeos que se están viendo (si se filtra por canal, los de ese canal)
        "steps": [(p, st) for p, st in coach.next_steps(db) if p.id in shown][:3],
    }


# ---------- Perfil (la primera vez: bienvenida) ----------


@router.get("/bienvenida")
def welcome_page(request: Request, db: DB, user: CurrentUser, guardado: int = 0):
    return render(
        request,
        "welcome.html",
        p=profile.get(db),
        first_time=not profile.is_set(db),
        handle=get_setting(db, "youtube_channel") or "",
        countries=list(profile.COUNTRIES),
        has_gemini=api_key_hint(db, "gemini") is not None,
        has_channels=bool(db.scalar(select(Channel.id).limit(1))),
        saved=bool(guardado),
    )


@router.post("/bienvenida")
def save_profile(
    db: DB,
    user: CurrentUser,
    owner: Annotated[str, Form()] = "",
    channel: Annotated[str, Form()] = "",
    handle: Annotated[str, Form()] = "",
    niche: Annotated[str, Form()] = "",
    country: Annotated[str, Form()] = "",
):
    profile.save(db, owner, channel, niche, country, handle)
    return _redirect("/bienvenida?guardado=1")


# ---------- Canales ----------


@router.get("/canales")
def channels_page(request: Request, db: DB, user: CurrentUser):
    channels = db.scalars(
        select(Channel).options(selectinload(Channel.projects)).order_by(Channel.name)
    ).all()
    return _channels_page(request, db, channels)


def _channels_page(request: Request, db, channels, status_code: int = 200, **ctx):
    from app import niche
    from app.pipeline import accent

    kits = {c.id: niche.kit_for(db, c) for c in channels}
    own = {
        c.id: niche.has_own_kit(db, c) or niche.is_brands(niche.niche_of(db, c)) for c in channels
    }
    return render(
        request,
        "channels.html",
        status_code=status_code,
        channels=channels,
        languages=LANGUAGES,
        kits=kits,
        own=own,
        has_gemini=api_key_hint(db, "gemini") is not None,
        palette={name: accent.css(name) for name in accent.PALETTE},
        **ctx,
    )


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
        return _channels_page(request, db, channels, 400, error="Escribe un nombre para el canal.")
    db.add(
        Channel(name=name[:100], niche=niche.strip()[:200], language=language, created_by=user.id)
    )
    db.commit()
    return _redirect("/canales")


def _channel(db, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(404, "Ese canal no existe")
    return channel


@router.post("/canales/{channel_id}/nicho")
def change_niche(db: DB, user: CurrentUser, channel_id: int, niche: Annotated[str, Form()] = ""):
    _channel(db, channel_id).niche = " ".join(niche.split())[:200]
    db.commit()
    return _redirect(f"/canales#c-{channel_id}")


@router.post("/canales/{channel_id}/color")
def change_color(db: DB, user: CurrentUser, channel_id: int, color: Annotated[str, Form()] = ""):
    from app.pipeline.accent import PALETTE

    _channel(db, channel_id).color = color if color in PALETTE else None
    db.commit()
    return _redirect(f"/canales#c-{channel_id}")


@router.post("/canales/{channel_id}/ficha")
def make_niche_kit(request: Request, db: DB, user: CurrentUser, channel_id: int):
    """La IA crea (o rehace) la ficha del nicho del canal."""
    from app import niche
    from app.providers.ai import ProviderError

    channel = _channel(db, channel_id)
    try:
        ai = jobs.get_ai_provider(db)
        niche.generate(db, channel, ai)
        jobs.remember_working_model(db, ai)
    except ProviderError as exc:
        channels = db.scalars(select(Channel).order_by(Channel.name)).all()
        return _channels_page(request, db, channels, 400, error=f"No se pudo crear la ficha: {exc}")
    return _redirect(f"/canales#c-{channel_id}")


# ---------- Proyectos ----------


def _project_form_context(db: DB) -> dict:
    return {
        "channels": db.scalars(select(Channel).order_by(Channel.name)).all(),
        "durations": DURATIONS,
        "languages": LANGUAGES,
        "video_types": VIDEO_TYPES,
        "modes": AUTOMATION_MODES,
        "formats": {k: v[0] for k, v in FORMATS.items()},
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
    video_format: Annotated[str, Form()] = "auto",
):
    form = {
        "channel_id": channel_id,
        "topic": topic.strip(),
        "title": title.strip(),
        "duration": duration,
        "language": language,
        "video_type": video_type,
        "automation_mode": automation_mode,
        "video_format": video_format if video_format in FORMATS else "auto",
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
        video_format=form["video_format"],
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
        qc=project_review(db, project) if "script" in results else None,
        usage=usage.project_usage(db, project_id),
        month_usage=usage.month_usage(db),
        stage_names=STAGES,
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
    delete_project_files(project_id)
    return _redirect("/")


# ---------- Semana ----------


@router.get("/semana")
def week_page(request: Request, db: DB, user: CurrentUser):
    from app import coach
    from app.agenda import WEEKDAYS

    day, hour = coach.publish_slot(db)
    return render(
        request,
        "week.html",
        days=coach.week_days(db),
        plan=coach.weekly_plan(db),
        weekdays=WEEKDAYS,
        publish_day=day,
        publish_hour=hour,
    )


@router.post("/semana")
def save_week(
    db: DB,
    user: CurrentUser,
    day: Annotated[int, Form()],
    hour: Annotated[int, Form()],
):
    from app import coach

    coach.set_publish_slot(db, day, hour)
    return _redirect("/semana")
