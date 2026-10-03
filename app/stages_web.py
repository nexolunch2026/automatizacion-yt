"""Páginas de cada etapa del proyecto: investigación, estrategia y guion."""

import copy
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import select

from app import jobs
from app.auth import DB, CurrentUser
from app.media import MUSIC_DIR, MUSIC_EXTENSIONS, music_library, project_dir, safe_path
from app.models import LEVELS, SCRIPT_TONES, STAGES, Project, StageResult
from app.pipeline.monetization import AREAS, project_review
from app.pipeline.render import MUSIC_VOLUMES
from app.pipeline.script import (
    AUTO,
    SECTION_LABELS,
    STRUCTURES,
    default_params,
    rewrite_paragraph,
    with_stats,
)
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
    "publish": "publicacion",
    "thumbnail": "miniatura",
    "shorts": "shorts",
    "qc": "control",
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
        structures=STRUCTURES,
    )


@router.get("/escenas")
def storyboard_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard")
    script = jobs.get_result(db, project_id, "script")
    stale = stale_scenes(board, script) if board and script else {"changed": [], "new": []}
    return _stage_page(request, db, project, "storyboard", stale=stale, labels=SECTION_LABELS)


@router.post("/escenas/graficos")
def find_charts(db: DB, user: CurrentUser, project_id: int):
    _project(db, project_id)
    if _result_row(db, project_id, "storyboard") is None:
        raise HTTPException(404, "Todavía no hay escenas")
    jobs.enqueue(db, project_id, "storyboard", {"charts_only": True})
    return _redirect(f"/proyectos/{project_id}/escenas")


def _scene_with_chart(db: DB, project_id: int, paragraph_id: str) -> tuple:
    row = _result_row(db, project_id, "storyboard")
    scenes = (row.data if row else {}).get("scenes", [])
    scene = next((s for s in scenes if s["paragraph_id"] == paragraph_id and s.get("chart")), None)
    if scene is None:
        raise HTTPException(404, "Esa escena no tiene gráfico")
    return row, scene


@router.get("/escenas/graficos/{paragraph_id}.png")
def chart_preview(db: DB, user: CurrentUser, project_id: int, paragraph_id: str):
    from app.pipeline.charts import preview

    _, scene = _scene_with_chart(db, project_id, paragraph_id)
    visuals = jobs.get_result(db, project_id, "visuals") or {"items": {}}
    entry = visuals["items"].get(paragraph_id) or {}
    folder = project_dir(project_id)
    bg = folder / "visuales" / entry["file"] if entry.get("kind") == "image" else None
    out = folder / "graficos" / f"{paragraph_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    preview(scene["chart"], (640, 360), out, bg)
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@router.post("/escenas/graficos/{paragraph_id}/quitar")
def remove_chart(db: DB, user: CurrentUser, project_id: int, paragraph_id: str):
    row, _ = _scene_with_chart(db, project_id, paragraph_id)
    data = copy.deepcopy(row.data)
    for scene in data["scenes"]:
        if scene["paragraph_id"] == paragraph_id:
            scene.pop("chart", None)
    row.data = data
    db.commit()
    return _redirect(f"/proyectos/{project_id}/escenas")


ELEVEN_ID = re.compile(r"^eleven:[A-Za-z0-9]{6,40}$")


def _valid_voice(voice: str) -> bool:
    return voice in VOICE_IDS or bool(ELEVEN_ID.match(voice))


def eleven_plan(credits: dict | None, characters: int) -> dict | None:
    """Cuántos vídeos como este caben en los créditos que quedan este mes."""
    if not credits or not characters:
        return None
    half = (characters + 1) // 2  # modo Ahorro: la mitad de créditos
    return {
        "free": credits.get("tier") == "free",
        "videos": credits["left"] // characters,
        "videos_saving": credits["left"] // half,
        "month_saving": credits["limit"] // half,
    }


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
    characters = sum(len(p["text"]) for p in paragraphs)
    return {
        "eleven_plan": eleven_plan(credits, characters),
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
        f"Formato: {shape}.",
        "IMPORTANTE: las imágenes NO deben llevar texto, números, gráficos ni rótulos.",
        "La IA se inventa esos datos (y en inglés). Las cifras y fechas las pone el",
        "programa encima, con los datos reales de tu investigación.",
        "",
        "Truco: en ChatGPT escribe «Genera esta imagen en formato "
        f"{shape}, sin ningún texto, número ni gráfico:» y pega el prompt.",
        "",
    ]
    for scene in board["scenes"]:
        lines += [
            f"=== Escena {scene['number']:02} ({scene['seconds']} s) ===",
            f"Lo que se narra: {scene['narration']}",
            f"Prompt: {image_prompt(scene, board.get('visual_bible') or {})}. "
            "No text, no numbers, no charts, no infographics, no signs.",
            "",
        ]
    filename = f"prompts-proyecto-{project_id}.txt"
    return PlainTextResponse(
        "\n".join(lines), headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


MAX_UPLOAD = 20 * 1024 * 1024


def _store_image(project_id: int, scene: dict, data: bytes) -> str:
    """Valida la imagen, la convierte a JPEG (máx. 2560 px) y devuelve el nombre de archivo."""
    import io
    import secrets

    from PIL import Image, UnidentifiedImageError

    if len(data) > MAX_UPLOAD:
        raise ValueError("es demasiado grande (máximo 20 MB)")
    try:
        picture = Image.open(io.BytesIO(data))
        picture.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("no es una imagen válida") from exc
    picture = picture.convert("RGB")
    picture.thumbnail((2560, 2560))
    folder = project_dir(project_id) / "visuales"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{scene['number']:03}-subida-{secrets.token_hex(3)}.jpg"
    picture.save(folder / filename, "JPEG", quality=92)
    return filename


def _uploaded_entry(filename: str, is_ai: bool) -> dict:
    return {
        "kind": "image",
        "file": filename,
        "provider": "manual",
        "id": filename,
        "author": "",
        "license": "Imagen subida por ti" + (" (generada con IA)" if is_ai else ""),
        "page_url": "",
        "query": "",
        "ai": is_ai,
        "uploaded": True,
    }


def _save_visual_items(db: DB, project_id: int, new_items: dict) -> None:
    row = _result_row(db, project_id, "visuals")
    visuals = copy.deepcopy(row.data) if row else {"items": {}, "providers": []}
    visuals["items"].update(new_items)
    if row:
        row.data = visuals
    else:
        db.add(StageResult(project_id=project_id, stage="visuals", data=visuals))
    db.commit()


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
    _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard")
    scene = next(
        (s for s in (board or {}).get("scenes", []) if s["paragraph_id"] == paragraph_id), None
    )
    if scene is None:
        raise HTTPException(404, "Escena no encontrada")
    try:
        filename = _store_image(project_id, scene, await image.read(MAX_UPLOAD + 1))
    except ValueError as exc:
        raise HTTPException(400, f"El archivo {exc}") from exc
    _save_visual_items(db, project_id, {paragraph_id: _uploaded_entry(filename, bool(is_ai))})
    return _redirect(f"/proyectos/{project_id}/visuales#escena-{paragraph_id}")


SCENE_IN_NAME = re.compile(r"^(?:(?:escena|scene|imagen|image|img)[\s_-]*)?0*(\d{1,3})$", re.I)


def scene_number_from_name(filename: str) -> int | None:
    """«5.png», «05.jpg», «escena 5.png», «Escena-05.webp», «scene_5.png» → 5."""
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0].strip()
    match = SCENE_IN_NAME.match(stem)
    return int(match.group(1)) if match else None


def _natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def match_files_to_scenes(names: list[str], scene_count: int, start: int = 1) -> dict[int, int]:
    """Índice de archivo → número de escena. Si todos los nombres indican su escena, se
    respeta; si no, se asignan en orden (por nombre) a partir de la escena `start`."""
    numbers = [scene_number_from_name(n) for n in names]
    if names and all(n is not None for n in numbers):
        return {i: n for i, n in enumerate(numbers) if 1 <= n <= scene_count}
    order = sorted(range(len(names)), key=lambda i: _natural_key(names[i]))
    return {
        index: start + position
        for position, index in enumerate(order)
        if start + position <= scene_count
    }


@router.post("/visuales/subir-varias")
async def upload_many(
    db: DB,
    user: CurrentUser,
    project_id: int,
    images: Annotated[list[UploadFile], File()],
    start: Annotated[int, Form()] = 1,
    is_ai: Annotated[str | None, Form()] = None,
):
    """Sube muchas imágenes de una vez y las reparte entre las escenas."""
    _project(db, project_id)
    board = jobs.get_result(db, project_id, "storyboard")
    if board is None:
        raise HTTPException(404, "Primero crea las escenas")
    scenes = {s["number"]: s for s in board["scenes"]}
    files = [f for f in images if f.filename]
    mapping = match_files_to_scenes([f.filename for f in files], len(scenes), max(start, 1))
    new_items, problems = {}, []
    for index, upload in enumerate(files):
        number = mapping.get(index)
        if number is None or number not in scenes:
            problems.append(f"{upload.filename}: no hay escena para ella")
            continue
        try:
            filename = _store_image(project_id, scenes[number], await upload.read(MAX_UPLOAD + 1))
        except ValueError as exc:
            problems.append(f"{upload.filename}: {exc}")
            continue
        new_items[scenes[number]["paragraph_id"]] = _uploaded_entry(filename, bool(is_ai))
    if new_items:
        _save_visual_items(db, project_id, new_items)
    row = _result_row(db, project_id, "visuals")
    if row:  # el resumen se muestra en la página
        data = copy.deepcopy(row.data)
        data["upload_report"] = {"ok": len(new_items), "problems": problems[:20]}
        row.data = data
        db.commit()
    return _redirect(f"/proyectos/{project_id}/visuales#subida")


MAX_MUSIC = 60 * 1024 * 1024


@router.post("/musica/subir")
async def upload_music(
    db: DB, user: CurrentUser, project_id: int, songs: Annotated[list[UploadFile], File()]
):
    """Añade canciones a la biblioteca de música (sirve para todos los proyectos)."""
    import re as _re

    _project(db, project_id)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    for song in songs:
        name = Path(song.filename or "").name
        if Path(name).suffix.lower() not in MUSIC_EXTENSIONS:
            continue
        safe = _re.sub(r"[^\w .()-]", "_", name).strip() or "cancion.mp3"
        data = await song.read(MAX_MUSIC + 1)
        if len(data) <= MAX_MUSIC:
            (MUSIC_DIR / safe).write_bytes(data)
    return _redirect(f"/proyectos/{project_id}/video#musica")


@router.post("/musica/borrar")
def delete_music(db: DB, user: CurrentUser, project_id: int, name: Annotated[str, Form()]):
    _project(db, project_id)
    if name in music_library():
        (MUSIC_DIR / name).unlink(missing_ok=True)
    return _redirect(f"/proyectos/{project_id}/video#musica")


@router.get("/musica/{name}")
def play_music(db: DB, user: CurrentUser, project_id: int, name: str):
    _project(db, project_id)
    if name not in music_library():
        raise HTTPException(404, "Canción no encontrada")
    return FileResponse(MUSIC_DIR / name)


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
        style=jobs.render_style(db),
        library=music_library(),
        music_volumes=list(MUSIC_VOLUMES),
        has_ai_images=any(e.get("ai") for e in visuals.get("items", {}).values()),
        has_srt=(folder / "subtitulos.srt").exists(),
        has_credits=(folder / "creditos.txt").exists()
        and (folder / "creditos.txt").read_text(encoding="utf-8").strip() != "",
    )


@router.get("/publicacion")
def publish_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    visuals = jobs.get_result(db, project_id, "visuals") or {}
    return _stage_page(
        request,
        db,
        project,
        "publish",
        has_ai_images=any(e.get("ai") for e in visuals.get("items", {}).values()),
    )


@router.get("/miniatura")
def thumbnail_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    return _stage_page(request, db, _project(db, project_id), "thumbnail")


@router.get("/shorts")
def shorts_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    return _stage_page(request, db, _project(db, project_id), "shorts")


@router.get("/control")
def qc_page(request: Request, db: DB, user: CurrentUser, project_id: int):
    project = _project(db, project_id)
    return _stage_page(request, db, project, "qc", qc=project_review(db, project), areas=AREAS)


@router.post("/shorts/{number}/portada")
def short_cover(
    db: DB, user: CurrentUser, project_id: int, number: int, text: Annotated[str, Form()]
):
    """Rehace la portada de un Short con otro texto (al momento, sin volver a montarlo)."""
    from app.pipeline.shorts import make_cover

    _project(db, project_id)
    row = _result_row(db, project_id, "shorts")
    shorts = (row.data if row else {}).get("shorts", [])
    if not 1 <= number <= len(shorts) or not text.strip():
        raise HTTPException(404, "Ese Short no existe")
    data = copy.deepcopy(row.data)
    short = data["shorts"][number - 1]
    folder = project_dir(project_id)
    visuals = jobs.get_result(db, project_id, "visuals") or {"items": {}}
    text = " ".join(text.split())[:40]
    cover = f"shorts/short-{number}/portada.jpg"
    ids = short.get("paragraph_ids")
    if not ids:  # Shorts hechos antes de que existieran las portadas
        from app.pipeline.shorts import paragraph_table

        script = jobs.get_result(db, project_id, "script") or {}
        voice = jobs.get_result(db, project_id, "voice") or {"takes": []}
        rows = paragraph_table(script, {t["paragraph_id"]: t["seconds"] for t in voice["takes"]})
        start, end = short.get("paragraphs", [1, 1])
        ids = [r["id"] for r in rows[start - 1 : end]]
    make_cover(jobs.media_map(folder, visuals), ids, text, folder / cover)
    short.update(cover=cover, hook=text)
    row.data = data
    db.commit()
    return _redirect(f"/proyectos/{project_id}/shorts")


@router.post("/miniatura/elegir")
def choose_thumbnail(db: DB, user: CurrentUser, project_id: int, index: Annotated[int, Form()]):
    _project(db, project_id)
    try:
        jobs.select_thumbnail(db, project_id, index)
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _redirect(f"/proyectos/{project_id}/miniatura")


@router.post("/miniatura/textos")
def thumbnail_texts(
    db: DB,
    user: CurrentUser,
    project_id: int,
    text1: Annotated[str, Form()] = "",
    text2: Annotated[str, Form()] = "",
    text3: Annotated[str, Form()] = "",
    highlight1: Annotated[str, Form()] = "",
    highlight2: Annotated[str, Form()] = "",
    highlight3: Annotated[str, Form()] = "",
):
    """Rehace las 3 miniaturas con los textos que escribiste (mismos fondos)."""
    _project(db, project_id)
    texts = []
    for text, highlight in ((text1, highlight1), (text2, highlight2), (text3, highlight3)):
        text = " ".join(text.split())[:40]
        if text:
            texts.append({"text": text, "highlight": highlight.strip() or text.split()[-1]})
    if not texts:
        return _redirect(f"/proyectos/{project_id}/miniatura")
    jobs.enqueue(db, project_id, "thumbnail", {"texts": texts})
    return _redirect(f"/proyectos/{project_id}/miniatura")


@router.post("/publicado")
def mark_published(db: DB, user: CurrentUser, project_id: int):
    """El vídeo ya está en YouTube: deja de aparecer en las tareas de JARVIS."""
    project = _project(db, project_id)
    project.status = "Publicado"
    db.commit()
    return _redirect(f"/proyectos/{project_id}/publicacion")


@router.post("/etapas/{stage}")
def run_stage(
    db: DB,
    user: CurrentUser,
    project_id: int,
    stage: str,
    tone: Annotated[str | None, Form()] = None,
    drama: Annotated[str | None, Form()] = None,
    technical: Annotated[str | None, Form()] = None,
    structure: Annotated[str | None, Form()] = None,
    voice: Annotated[str | None, Form()] = None,
    speed: Annotated[str | None, Form()] = None,
    quality: Annotated[str | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    mode: Annotated[str | None, Form()] = None,
    subtitles: Annotated[str | None, Form()] = None,
    film_look: Annotated[str | None, Form()] = None,
    music: Annotated[str | None, Form()] = None,
    music_volume: Annotated[str | None, Form()] = None,
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
            "structure": structure if structure in STRUCTURES else AUTO,
        }
    elif stage == "edit":
        params = {
            "quality": quality if quality in ("preview", "final") else "preview",
            "subtitles": subtitles == "1",
            "film_look": film_look == "1",
            "music": music if music in ("", *music_library()) else "",
            "music_volume": music_volume if music_volume in MUSIC_VOLUMES else "media",
        }
    elif stage == "shorts":
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
    if _result_row(db, project_id, "strategy") is None:
        raise HTTPException(404, "Todavía no hay propuestas")
    try:
        jobs.select_concept(db, project_id, concept, title)
    except ProviderError as exc:
        raise HTTPException(400, "Enfoque no válido") from exc
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
        if text.strip() and text.strip() != paragraph["text"]:
            paragraph["text"] = text.strip()
            # Cuántos párrafos ha retocado a mano (lo mira el control de calidad).
            script["edited"] = script.get("edited", 0) + 1
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
                structures=STRUCTURES,
                error=f"No se pudo cambiar el párrafo: {exc}",
            )
    row.data = script
    db.commit()
    return _redirect(f"/proyectos/{project_id}/guion#p-{paragraph_id}")
