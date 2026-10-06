"""SHORTS ENGINE: de cada documental, 2–3 Shorts verticales con sus mejores momentos.

1. Gemini elige los fragmentos más llamativos (párrafos seguidos de 20–58 s): un dato
   sorprendente, un giro, una cifra… y les pone un título y un gancho en pantalla.
   Sin Gemini se eligen solos (los que tienen cifras, preguntas o el gancho del vídeo).
2. Cada fragmento se vuelve a montar en vertical (no se recorta el vídeo horizontal):
   mismas imágenes con movimiento, la misma voz, subtítulos grandes y el gancho arriba.
3. Cada Short empuja al documental: gancho desde el primer fotograma, final que deja la
   intriga abierta, cartel «la historia completa, en el canal» los últimos 3 s y, cuando
   el creador pega el enlace del vídeo largo, la descripción y el comentario fijado lo llevan.
   En YouTube Studio además se elige ese vídeo como «Vídeo relacionado» del Short.
"""

import re
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import Project
from app.pipeline.render import PAUSE, render_video
from app.providers.ai import AIProvider, ProviderError
from app.providers.voice import join_wavs

MIN_SECONDS = 18
MAX_SECONDS = 58
TARGET_SECONDS = 40
END_TEXT = "La historia completa, en el canal"


class ShortPick(BaseModel):
    start: int = Field(description="Número del primer párrafo")
    end: int = Field(description="Número del último párrafo (incluido)")
    title: str = Field(description="Título del Short, máximo 60 caracteres, con gancho")
    hook: str = Field(description="Texto en pantalla al empezar: 2 a 5 palabras")


class ShortPicks(BaseModel):
    shorts: list[ShortPick]


def paragraph_table(script: dict, takes: dict[str, float]) -> list[dict]:
    rows = []
    for section in script.get("sections", []):
        for paragraph in section["paragraphs"]:
            if paragraph["id"] in takes:
                rows.append(
                    {
                        "n": len(rows) + 1,
                        "id": paragraph["id"],
                        "text": paragraph["text"],
                        "seconds": takes[paragraph["id"]],
                        "kind": section.get("kind", ""),
                    }
                )
    return rows


def span_seconds(rows: list[dict], start: int, end: int) -> float:
    chosen = rows[start - 1 : end]
    return sum(r["seconds"] for r in chosen) + PAUSE * max(0, len(chosen) - 1)


def _fit(rows: list[dict], start: int, end: int) -> tuple[int, int] | None:
    """Ajusta un fragmento para que dure entre MIN y MAX segundos."""
    start, end = max(1, start), min(len(rows), max(start, end))
    while end > start and span_seconds(rows, start, end) > MAX_SECONDS:
        end -= 1
    while span_seconds(rows, start, end) < MIN_SECONDS and end < len(rows):
        if span_seconds(rows, start, end + 1) > MAX_SECONDS:
            break
        end += 1
    seconds = span_seconds(rows, start, end)
    if seconds > MAX_SECONDS or seconds < MIN_SECONDS * 0.6:
        return None
    return start, end


def _interest(row: dict) -> float:
    text = row["text"]
    score = len(re.findall(r"\d", text)) * 0.4 + text.count("?") * 1.5 + text.count("!")
    if row["kind"] in ("hook", "twist", "climax"):
        score += 4
    return score


def heuristic_picks(rows: list[dict], count: int) -> list[ShortPick]:
    windows = []
    for start in range(1, len(rows) + 1):
        fitted = _fit(rows, start, start)
        if fitted:
            s, e = fitted
            score = sum(_interest(r) for r in rows[s - 1 : e]) / (e - s + 1)
            windows.append((score, s, e))
    windows.sort(reverse=True)
    picks: list[ShortPick] = []
    taken: set[int] = set()
    for _, s, e in windows:
        if taken & set(range(s, e + 1)):
            continue
        taken |= set(range(s, e + 1))
        words = rows[s - 1]["text"].split()
        picks.append(ShortPick(start=s, end=e, title=" ".join(words[:9]), hook=" ".join(words[:4])))
        if len(picks) >= count:
            break
    return sorted(picks, key=lambda p: p.start)


def _prompt(project: Project, script: dict, rows: list[dict], count: int) -> str:
    table = "\n".join(f"[{r['n']}] ({r['seconds']:.0f} s) {r['text']}" for r in rows)
    return f"""Eres editor de YouTube Shorts para el canal de documentales «{project.title}».
Del guion numerado elige {count} fragmentos para Shorts verticales:
- Cada uno son párrafos SEGUIDOS que duren entre {MIN_SECONDS} y {MAX_SECONDS} segundos en total
  (mira los segundos de cada párrafo) y que se entiendan solos, sin ver el vídeo largo.
- Los 2 primeros segundos deciden si la gente se queda: que el primer párrafo empiece
  fuerte (un dato sorprendente, una cifra, un giro, una pregunta), nunca con contexto.
- Que el último párrafo deje la intriga ABIERTA (qué pasó después, por qué cayó…): el
  Short tiene que dar ganas de ver el documental completo, no contar el final.
- Que no se solapen.
- title: título del Short (máximo 60 caracteres), con curiosidad, honesto y sin
  destripar el final.
- hook: 2–5 palabras que se verán grandes desde el primer fotograma: una promesa o una
  cifra («PERDIÓ 74.000 MILLONES», «NADIE LO VIO VENIR»), no el nombre de la marca solo.

Vídeo: «{script.get("title") or project.title}»
GUION:
{table}"""


def choose_segments(
    project: Project, script: dict, rows: list[dict], ai: AIProvider | None, count: int
) -> list[ShortPick]:
    picks: list[ShortPick] = []
    if ai is not None:
        try:
            picks = ai.generate_json(_prompt(project, script, rows, count), ShortPicks).shorts
        except ProviderError:
            picks = []
    valid, taken = [], set()
    for pick in picks:
        fitted = _fit(rows, pick.start, pick.end)
        if not fitted:
            continue
        span = set(range(fitted[0], fitted[1] + 1))
        if span & taken:
            continue
        taken |= span
        valid.append(pick.model_copy(update={"start": fitted[0], "end": fitted[1]}))
    if len(valid) < count:  # completa con los elegidos automáticamente
        for pick in heuristic_picks(rows, count * 2):
            span = set(range(pick.start, pick.end + 1))
            if not span & taken and len(valid) < count:
                taken |= span
                valid.append(pick)
    return sorted(valid[:count], key=lambda p: p.start)


def how_many(total_seconds: float) -> int:
    if total_seconds < 90:
        return 1
    if total_seconds < 240:
        return 2
    return 3


def highlight_word(text: str) -> str:
    """La palabra que irá en rojo: una cifra si la hay; si no, la más larga."""
    words = text.split()
    if not words:
        return ""
    with_digits = [w for w in words if re.search(r"\d", w)]
    return (with_digits or sorted(words, key=len, reverse=True))[0]


def make_cover(media: dict, paragraph_ids: list[str], text: str, out: Path) -> Path:
    """Portada vertical del Short (1080×1920) con la imagen más llamativa de sus escenas."""
    from app.pipeline import thumbnail

    images = [
        media[pid]["path"]
        for pid in paragraph_ids
        if pid in media and media[pid]["kind"] == "image" and Path(media[pid]["path"]).exists()
    ]
    scored = []
    for path in images:
        try:
            scored.append((thumbnail._score(Path(path)), Path(path)))
        except OSError:
            continue
    background = max(scored)[1] if scored else None
    return thumbnail.compose(
        background, text, highlight_word(text), "center", thumbnail.PORTRAIT, out
    )


def run_shorts(
    project: Project,
    script: dict,
    board: dict,
    voice: dict,
    media: dict,
    project_folder: Path,
    ai: AIProvider | None,
    progress: Callable[[int, str], None],
    quality: str = "preview",
    style: dict | None = None,
    music: Path | None = None,
    hashtags: list[str] | None = None,
) -> dict:
    takes = {t["paragraph_id"]: t["seconds"] for t in voice["takes"]}
    files = {t["paragraph_id"]: project_folder / t["file"] for t in voice["takes"]}
    rows = paragraph_table(script, takes)
    if not rows:
        raise ProviderError("No hay narración grabada para hacer Shorts.")
    progress(5, "Buscando los mejores momentos del vídeo")
    count = how_many(voice.get("seconds") or sum(takes.values()))
    picks = choose_segments(project, script, rows, ai, count)
    if not picks:  # no es un error: simplemente no hay material suficiente
        progress(100, "Vídeo demasiado corto para Shorts")
        return {
            "shorts": [],
            "quality": quality,
            "note": "El vídeo es demasiado corto para "
            "sacar Shorts (hace falta al menos un fragmento de unos 20 segundos).",
        }

    scenes_by_id = {s["paragraph_id"]: s for s in board["scenes"]}
    out_root = project_folder / "shorts"
    shorts = []
    for i, pick in enumerate(picks, 1):
        ids = [r["id"] for r in rows[pick.start - 1 : pick.end]]
        scenes = [dict(scenes_by_id[pid]) for pid in ids if pid in scenes_by_id]
        if not scenes:
            continue
        scenes[0]["on_screen_text"] = pick.hook.upper()  # el gancho, arriba, al empezar
        scenes[0]["text_from_start"] = True
        scenes[0].pop("chart", None)  # el primer plano es el gancho, no un gráfico
        if len(scenes) > 1:
            scenes[-1]["on_screen_text"] = ""  # que solo se vea el cartel final
        scenes[-1]["end_text"] = END_TEXT  # los últimos segundos llevan al vídeo largo
        folder = out_root / f"short-{i}"
        folder.mkdir(parents=True, exist_ok=True)
        narration = folder / "narracion.wav"
        narration.write_bytes(join_wavs([files[pid].read_bytes() for pid in ids], PAUSE))

        def step(pct: int, message: str, i=i) -> None:
            progress(10 + round(85 * ((i - 1) + pct / 100) / len(picks)), f"Short {i}: {message}")

        result = render_video(
            scenes,
            media,
            {pid: takes[pid] for pid in ids},
            narration,
            folder,
            quality,
            True,  # vertical
            step,
            style={**(style or {}), "subtitles": True},  # en los Shorts se ven sin sonido
            music=music,
        )
        narration.unlink(missing_ok=True)
        step(99, "creando la portada")
        make_cover(media, ids, pick.hook, folder / "portada.jpg")
        tags = " ".join((hashtags or [])[:2] + ["#shorts"])
        shorts.append(
            {
                "file": f"shorts/short-{i}/{result['file'].removeprefix('video/')}",
                "cover": f"shorts/short-{i}/portada.jpg",
                "title": pick.title[:100],
                "hook": pick.hook,
                "seconds": result["seconds"],
                "paragraphs": [pick.start, pick.end],
                "paragraph_ids": ids,
                "tags": tags,
                "description": description(pick.title, tags),
            }
        )
    progress(100, "Shorts listos")
    return {"shorts": shorts, "quality": quality}


def description(title: str, tags: str, long_url: str = "") -> str:
    where = "El documental completo, en el canal."
    if long_url:
        where = f"▶ El documental completo: {long_url}"
    return f"{title}\n\n{where}\n\n{tags}".strip()


def pinned_comment(long_url: str) -> str:
    return f"🎬 ¿Qué pasó después? La historia completa aquí 👉 {long_url}"


def link_long_video(data: dict, long_url: str) -> dict:
    """Pone (o quita, con "") el enlace del vídeo largo en todos los Shorts."""
    data = {**data, "long_url": long_url}
    shorts = []
    for short in data.get("shorts", []):
        # Shorts de versiones anteriores: los hashtags estaban al final de la descripción.
        tags = short.get("tags") or " ".join(re.findall(r"#\w+", short.get("description", "")))
        shorts.append(
            {**short, "tags": tags, "description": description(short["title"], tags, long_url)}
        )
    data["shorts"] = shorts
    return data
