"""Páginas de cada etapa del proyecto: investigación, estrategia y guion."""

import copy
import re
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import select

from app import jobs
from app.auth import DB, CurrentUser
from app.media import project_dir, safe_path
from app.models import LEVELS, SCRIPT_TONES, STAGES, Project, StageResult
from app.pipeline.script import SECTION_LABELS, default_params, rewrite_paragraph, with_stats
from app.pipeline.storyboard import paragraphs_of, stale_scenes
from app.pipeline.voice import pending_characters, take_key
from app.providers.ai import ProviderError
from app.providers.voice import ELEVEN_MODELS, SPEEDS, VOICE_IDS, VOICES, ElevenLabsVoices
from app.settings_store import api_key_hint, get_api_key
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


ELEVEN_ID = re.compile(r"^eleven:[A-Za-z0-9]{6,40}$")


def _valid_voice(voice: str) -> bool:
    return voice in VOICE_IDS or bool(ELEVEN_ID.match(voice))


def _voice_context(db: DB, project: Project) -> dict:
    script = jobs.get_result(db, project.id, "script") or {}
    voice = jobs.get_result(db, project.id, "voice")
    params = jobs.voice_params(db, project, voice)
    takes = {t["paragraph_id"]: t for t in (voice or {}).get("takes", [])}
    paragraphs = []
    for p in paragraphs_of(script):
        take = takes.get(p["id"])
        key = take_key(p["text"], params["voice"], params["speed"], params["model"])
        current = take and take["key"] == key
        paragraphs.append({**p, "take": take, "outdated": bool(take) and not current})
    eleven, eleven_error = jobs.eleven_voices(db)
    credits = None
    if eleven:
        credits = ElevenLabsVoices(get_api_key(db, "elevenlabs")).credits()
    sample = project_dir(project.id) / "voz" / "muestra.wav"
    return {
        "voices": VOICES,
        "eleven_voices": eleven,
        "eleven_error": eleven_error,
        "eleven_models": ELEVEN_MODELS,
        "credits": credits,
        "script_characters": sum(len(p["text"]) for p in paragraphs),
        "pending_characters": pending_characters(script, voice, params),
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


def make_sample(db: DB, text: str, voice: str, speed: str, model: str) -> bytes:
    """Graba una muestra corta. Se reemplaza en los tests."""
    return jobs.get_voice_provider(db, voice, model).synthesize(text, voice, speed)


@router.post("/voz/muestra")
def voice_sample(
    request: Request,
    db: DB,
    user: CurrentUser,
    project_id: int,
    voice: Annotated[str, Form()],
    speed: Annotated[str, Form()] = "Normal",
    model: Annotated[str, Form()] = "eleven_multilingual_v2",
):
    project = _project(db, project_id)
    if not _valid_voice(voice) or speed not in SPEEDS or model not in ELEVEN_MODELS:
        raise HTTPException(400, "Voz no válida")
    script = jobs.get_result(db, project_id, "script") or {}
    first = next(iter(paragraphs_of(script)), None)
    text = (first or {}).get("text") or "Hola, esta es una muestra de la voz que narrará tu vídeo."
    # Con ElevenLabs la muestra gasta créditos: se usa una frase corta.
    text = text[:160] if voice.startswith("eleven:") else text[:300]
    try:
        audio = make_sample(db, text, voice, speed, model)
    except ProviderError as exc:
        ctx = _voice_context(db, project)
        return _stage_page(request, db, project, "voice", status_code=400, error=str(exc), **ctx)
    folder = project_dir(project_id) / "voz"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "muestra.wav").write_bytes(audio)
    from app.settings_store import set_setting

    set_setting(db, "voice_default", voice)
    set_setting(db, "eleven_model", model)
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


@router.post("/visuales/ia/{paragraph_id}")
def ai_visual(
    db: DB,
    user: CurrentUser,
    project_id: int,
    paragraph_id: str,
    prompt: Annotated[str | None, Form()] = None,
):
    """Genera (o regenera) con IA la imagen de una escena, opcionalmente con otro prompt."""
    _project(db, project_id)
    row = _result_row(db, project_id, "storyboard")
    if row is None:
        raise HTTPException(404, "No hay escenas")
    if prompt is not None and prompt.strip():
        board = copy.deepcopy(row.data)
        for scene in board["scenes"]:
            if scene["paragraph_id"] == paragraph_id:
                scene["image_prompt"] = prompt.strip()[:1000]
        row.data = board
        db.commit()
    jobs.enqueue(db, project_id, "visuals", {"mode": "ai", "only": [paragraph_id]})
    return _redirect(f"/proyectos/{project_id}/visuales#escena-{paragraph_id}")


@router.get("/visuales/prompts.txt")
def prompts_file(db: DB, user: CurrentUser, project_id: int):
    """Todos los prompts numerados, para pegarlos en ChatGPT u otra herramienta."""
    from app.pipeline.visuals import image_prompt

    project = _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard")
    if board is None:
        raise HTTPException(404, "Todavía no hay escenas")
    shape = "vertical 9:16" if jobs.is_portrait(project) else "horizontal 16:9"
    lines = [
        f"PROMPTS DE IMÁGENES — {project.title}",
        f"Formato: {shape}. Pide a la IA que no ponga texto ni marcas de agua.",
        "Truco: en ChatGPT puedes escribir «Genera esta imagen en formato "
        f"{shape}:» y pegar el prompt.",
        "",
    ]
    for scene in board["scenes"]:
        lines += [
            f"=== Escena {scene['number']:02} ({scene['seconds']} s) ===",
            f"Lo que se narra: {scene['narration']}",
            f"Prompt: {image_prompt(scene, board.get('visual_bible') or {})}",
            "",
        ]
    filename = f"prompts-proyecto-{project_id}.txt"
    return PlainTextResponse(
        "\n".join(lines), headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


MAX_UPLOAD = 20 * 1024 * 1024


@router.post("/visuales/subir/{paragraph_id}")
async def upload_visual(
    db: DB,
    user: CurrentUser,
    project_id: int,
    paragraph_id: str,
    image: Annotated[UploadFile, File()],
    is_ai: Annotated[str | None, Form()] = None,
):
    """Usa una imagen propia (por ejemplo, hecha en ChatGPT) para una escena."""
    import io
    import secrets

    from PIL import Image, UnidentifiedImageError

    _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard")
    scene = next(
        (s for s in (board or {}).get("scenes", []) if s["paragraph_id"] == paragraph_id), None
    )
    if scene is None:
        raise HTTPException(404, "Escena no encontrada")
    data = await image.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "La imagen es demasiado grande (máximo 20 MB)")
    try:
        picture = Image.open(io.BytesIO(data))
        picture.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "El archivo no es una imagen válida") from exc
    picture = picture.convert("RGB")
    picture.thumbnail((2560, 2560))
    folder = project_dir(project_id) / "visuales"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{scene['number']:03}-subida-{secrets.token_hex(3)}.jpg"
    picture.save(folder / filename, "JPEG", quality=92)

    row = _result_row(db, project_id, "visuals")
    visuals = copy.deepcopy(row.data) if row else {"items": {}, "providers": []}
    visuals["items"][paragraph_id] = {
        "kind": "image",
        "file": filename,
        "provider": "manual",
        "id": filename,
        "author": "",
        "license": "Imagen subida por ti" + (" (generada con IA)" if is_ai else ""),
        "page_url": "",
        "query": "",
        "ai": bool(is_ai),
        "uploaded": True,
    }
    if row:
        row.data = visuals
    else:
        db.add(StageResult(project_id=project_id, stage="visuals", data=visuals))
    db.commit()
    return _redirect(f"/proyectos/{project_id}/visuales#escena-{paragraph_id}")


@router.get("/video")
def video_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    folder = project_dir(project_id) / "video"
    visuals = jobs.get_result(db, project_id, "visuals") or {}
    return _stage_page(
        request,
        db,
        project,
        "edit",
        has_ai_images=any(e.get("ai") for e in visuals.get("items", {}).values()),
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
    model: Annotated[str | None, Form()] = None,
    mode: Annotated[str | None, Form()] = None,
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
    elif stage == "visuals" and mode in ("stock", "ai"):
        params = {"mode": mode}
    elif stage == "voice":
        params = {
            "voice": voice if voice and _valid_voice(voice) else None,
            "speed": speed if speed in SPEEDS else None,
            "model": model if model in ELEVEN_MODELS else None,
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
