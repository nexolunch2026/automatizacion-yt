"""THUMBNAIL ENGINE: tres miniaturas con el estilo del canal para elegir la mejor.

- Fondo: las imágenes más llamativas del vídeo (más color y contraste) y, si se puede,
  una imagen nueva creada con IA a partir del concepto de miniatura de la estrategia.
- Texto: 2–4 palabras enormes en Bebas Neue, blanco con borde, y la palabra clave en el
  rojo de la marca. Tres composiciones distintas (texto a la izquierda, abajo, centrado).
- Salida: JPG de 1280×720 (o 1080×1920 en los Shorts), por debajo de los 2 MB de YouTube.
"""

import random
import re
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat
from pydantic import BaseModel, Field

from app.models import Project
from app.pipeline.render import RED, TITLE_FONT, font
from app.providers.ai import AIProvider, ProviderError

LANDSCAPE = (1280, 720)
PORTRAIT = (1080, 1920)
LAYOUTS = ["left", "bottom", "center"]
WHITE = (255, 255, 255)
MAX_BYTES = 1_900_000


class ThumbText(BaseModel):
    text: str = Field(description="2 a 4 palabras, impactantes, en mayúsculas")
    highlight: str = Field(description="La palabra (o cifra) que irá en rojo")


class ThumbTexts(BaseModel):
    texts: list[ThumbText]


# ---------------------------------------------------------------- textos


def _prompt(project: Project, strategy: dict, script: dict) -> str:
    concept = {}
    if strategy and strategy.get("selected"):
        concept = strategy["concepts"][strategy["selected"]["concept"]]
    thumb = concept.get("thumbnail", {})
    niche = getattr(getattr(project, "channel", None), "niche", "") or "documentales"
    return f"""Eres experto en miniaturas de YouTube para canales de {niche}.
Vídeo: «{script.get("title") or project.title}». Idioma: {project.language}.
Idea de miniatura de la estrategia: {thumb.get("concept", "")} — texto sugerido:
«{thumb.get("text", "")}». Gancho del vídeo: {concept.get("hook", "")}

Escribe 3 textos DISTINTOS para la miniatura:
- De 2 a 4 palabras, que despierten curiosidad sin repetir el título.
- Uno con una cifra o un año si el tema lo permite (solo si es real y está en el guion).
- Honestos: nada que el vídeo no cuente.
- Indica en «highlight» la palabra que irá en rojo (la más fuerte)."""


def fallback_texts(project: Project, strategy: dict, script: dict) -> list[ThumbText]:
    texts = []
    if strategy and strategy.get("selected"):
        concept = strategy["concepts"][strategy["selected"]["concept"]]
        suggested = concept.get("thumbnail", {}).get("text", "").strip()
        if suggested:
            texts.append(ThumbText(text=suggested, highlight=suggested.split()[-1]))
    words = re.findall(r"[\wÁÉÍÓÚÑáéíóúñ]+", script.get("title") or project.title)
    if words:
        short = " ".join(words[:4])
        texts.append(ThumbText(text=short, highlight=max(words[:4], key=len)))
    texts.append(ThumbText(text="¿QUÉ PASÓ?", highlight="PASÓ"))
    return texts


def make_texts(project: Project, strategy: dict, script: dict, ai: AIProvider | None) -> list:
    texts: list[ThumbText] = []
    if ai is not None:
        try:
            texts = ai.generate_json(_prompt(project, strategy, script), ThumbTexts).texts
        except ProviderError:
            texts = []
    texts = [t for t in texts if t.text.strip()][:3]
    for extra in fallback_texts(project, strategy, script):
        if len(texts) >= 3:
            break
        if all(extra.text.lower() != t.text.lower() for t in texts):
            texts.append(extra)
    while len(texts) < 3:
        texts.append(texts[-1])
    return texts[:3]


# ---------------------------------------------------------------- fondos


def _score(path: Path) -> float:
    """Cuánto «salta a la vista» una imagen: color y contraste."""
    with Image.open(path) as image:
        small = image.convert("RGB").resize((96, 54))
    saturation = ImageStat.Stat(small.convert("HSV")).mean[1]
    contrast = ImageStat.Stat(small.convert("L")).stddev[0]
    return saturation * 0.6 + contrast * 1.4


def candidate_images(visuals: dict, folder: Path, limit: int = 3) -> list[Path]:
    paths = []
    for entry in visuals.get("items", {}).values():
        name = entry.get("poster") if entry.get("kind") == "video" else entry.get("file")
        if entry.get("kind") in ("image", "video") and name and (folder / name).exists():
            paths.append(folder / name)
    scored = []
    for path in paths:
        try:
            scored.append((_score(path), path))
        except OSError:
            continue
    scored.sort(key=lambda s: s[0], reverse=True)
    return [p for _, p in scored[:limit]]


def ai_background(strategy: dict, project: Project, images, portrait: bool, out: Path) -> Path:
    concept = strategy["concepts"][strategy["selected"]["concept"]] if strategy else {}
    thumb = concept.get("thumbnail", {})
    idea = thumb.get("composition") or thumb.get("concept") or project.title
    prompt = (
        f"YouTube thumbnail background: {idea}. Dramatic cinematic lighting, strong "
        "contrast, bold colors, one clear subject, shallow depth of field"
    )
    data, ext, _ = images.generate(prompt, portrait, random.randint(1, 10_000_000))
    path = out.with_suffix(ext)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------- composición


def _cover(path: Path | None, size: tuple[int, int], focus_x: float = 0.5) -> Image.Image:
    if path is None:
        image = Image.new("RGB", size, (16, 18, 26))
    else:
        with Image.open(path) as source:
            image = ImageOps.fit(source.convert("RGB"), size, centering=(focus_x, 0.4))
    image = ImageEnhance.Contrast(image).enhance(1.18)
    image = ImageEnhance.Color(image).enhance(1.22)
    return ImageEnhance.Sharpness(image).enhance(1.4)


def _gradient(size: tuple[int, int], direction: str, strength: int = 235) -> Image.Image:
    """Capa negra que va de opaca a transparente (para que el texto se lea)."""
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if direction == "left":
        span = int(w * 0.68)
        for x in range(span):
            draw.line([(x, 0), (x, h)], fill=int(strength * (1 - x / span) ** 1.3))
    else:  # bottom
        span = int(h * 0.55)
        for i in range(span):
            draw.line([(0, h - i), (w, h - i)], fill=int(strength * (1 - i / span) ** 1.3))
    layer = Image.new("RGBA", size, (5, 6, 10, 255))
    layer.putalpha(mask)
    return layer


def _vignette(size: tuple[int, int]) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w // 8, h // 8), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([-w // 40, -h // 40, w // 8 + w // 40, h // 8 + h // 40], fill=255)
    mask = ImageOps.invert(mask.filter(ImageFilter.GaussianBlur(w // 60))).resize(size)
    layer = Image.new("RGBA", size, (0, 0, 0, 255))
    layer.putalpha(mask.point(lambda v: int(v * 0.8)))
    return layer


def split_lines(text: str) -> list[str]:
    """2 líneas equilibradas (o 1 si es muy corto)."""
    words = text.upper().split()
    if len(words) <= 1 or len(" ".join(words)) <= 10:
        return [" ".join(words)]
    best, best_diff = None, None
    for cut in range(1, len(words)):
        a, b = " ".join(words[:cut]), " ".join(words[cut:])
        diff = abs(len(a) - len(b))
        if best_diff is None or diff < best_diff:
            best, best_diff = [a, b], diff
    return best


def _fit(draw, lines: list[str], max_w: int, max_h: int, start: int):
    size = start
    while size > 24:
        fnt = font(size, TITLE_FONT)
        widths = [draw.textlength(line, font=fnt) for line in lines]
        height = int(size * 0.92) * len(lines)
        if max(widths) <= max_w and height <= max_h:
            return fnt, size
        size -= 4
    return font(size, TITLE_FONT), size


def _draw_words(draw, line: str, x: float, y: float, fnt, size: int, highlight: set, box: bool):
    """Escribe una línea palabra a palabra; la destacada va en rojo (o sobre caja roja)."""
    space = draw.textlength(" ", font=fnt)
    stroke = max(3, size // 22)
    for word in line.split():
        width = draw.textlength(word, font=fnt)
        hot = re.sub(r"[^\wáéíóúñ%]", "", word.lower()) in highlight
        if hot and box:
            pad = size * 0.08
            draw.rectangle([x - pad, y + size * 0.06, x + width + pad, y + size * 0.98], fill=RED)
            draw.text((x, y), word, font=fnt, fill=WHITE)
        else:
            draw.text((x + stroke, y + stroke), word, font=fnt, fill=(0, 0, 0))  # sombra
            draw.text(
                (x, y), word, font=fnt, fill=RED if hot else WHITE,
                stroke_width=stroke, stroke_fill=(0, 0, 0),
            )  # fmt: skip
        x += width + space


def compose(
    background: Path | None,
    text: str,
    highlight: str,
    layout: str,
    size: tuple[int, int],
    out: Path,
) -> Path:
    w, h = size
    portrait = h > w
    if portrait and layout == "left":
        layout = "bottom"
    image = _cover(background, size, focus_x=0.7 if layout == "left" else 0.5).convert("RGBA")
    if layout == "left":
        image.alpha_composite(_gradient(size, "left"))
    elif layout == "bottom":
        image.alpha_composite(_gradient(size, "bottom"))
    else:
        image = Image.blend(image, Image.new("RGBA", size, (0, 0, 0, 255)), 0.3)
    image.alpha_composite(_vignette(size))

    draw = ImageDraw.Draw(image)
    lines = split_lines(text)
    marked = {re.sub(r"[^\wáéíóúñ%]", "", w_.lower()) for w_ in highlight.split()}
    margin = int(w * 0.05)
    if layout == "left":
        fnt, fsize = _fit(draw, lines, int(w * 0.55), int(h * 0.62), int(h * 0.3))
        block = int(fsize * 0.92) * len(lines)
        y = (h - block) // 2
        for line in lines:
            _draw_words(draw, line, margin, y, fnt, fsize, marked, box=False)
            y += int(fsize * 0.92)
        draw.rectangle([margin, y + h * 0.045, margin + w * 0.12, y + h * 0.06], fill=RED)
    elif layout == "bottom":
        fnt, fsize = _fit(draw, lines, w - margin * 2, int(h * 0.44), int(h * 0.3))
        block = int(fsize * 0.92) * len(lines)
        y = h - block - int(h * 0.07)
        draw.rectangle([margin, y - h * 0.035, margin + w * 0.14, y - h * 0.018], fill=RED)
        for line in lines:
            _draw_words(draw, line, margin, y, fnt, fsize, marked, box=False)
            y += int(fsize * 0.92)
    else:  # center
        fnt, fsize = _fit(
            draw, lines, int(w * 0.8), int(h * 0.6), int(h * 0.32)
        )  # sitio para la caja roja
        block = int(fsize * 0.92) * len(lines)
        y = (h - block) // 2
        for line in lines:
            lw = draw.textlength(line, font=fnt)
            _draw_words(draw, line, (w - lw) / 2, y, fnt, fsize, marked, box=True)
            y += int(fsize * 0.92)
    # Marco fino rojo abajo: firma visual del canal en todas las miniaturas.
    draw.rectangle([0, h - max(6, h // 120), w, h], fill=RED)
    rgb = image.convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    for quality in (92, 85, 75, 65):
        rgb.save(out, "JPEG", quality=quality, optimize=True)
        if out.stat().st_size <= MAX_BYTES:
            break
    return out


# ---------------------------------------------------------------- etapa completa


def run_thumbnail(
    project: Project,
    strategy: dict,
    script: dict,
    visuals: dict,
    visuals_folder: Path,
    out_folder: Path,
    ai: AIProvider | None,
    progress: Callable[[int, str], None],
    images=None,
    texts: list[dict] | None = None,
    portrait: bool = False,
) -> dict:
    progress(10, "Eligiendo las imágenes más llamativas del vídeo")
    size = PORTRAIT if portrait else LANDSCAPE
    backgrounds: list[Path | None] = list(candidate_images(visuals, visuals_folder))
    sources = ["vídeo"] * len(backgrounds)
    out_folder.mkdir(parents=True, exist_ok=True)
    for old in out_folder.glob("*"):
        if old.is_file():
            old.unlink(missing_ok=True)
    notes = []
    if images is not None and strategy and strategy.get("selected"):
        progress(30, "Creando un fondo nuevo con IA a partir de la idea de miniatura")
        try:
            path = ai_background(strategy, project, images, portrait, out_folder / "fondo-ia")
            backgrounds.insert(0, path)
            sources.insert(0, "IA")
        except ProviderError as exc:
            notes.append(f"No se pudo crear el fondo con IA: {exc}")
    if not backgrounds:
        backgrounds, sources = [None], ["fondo de la marca"]
        notes.append("El vídeo aún no tiene imágenes: se usó un fondo liso.")

    progress(55, "Escribiendo los textos de la miniatura")
    if texts:
        chosen = [ThumbText(**t) for t in texts][:3]
        while len(chosen) < 3:
            chosen.append(chosen[-1])
    else:
        chosen = make_texts(project, strategy, script, ai)

    variants = []
    for i, (layout, text) in enumerate(zip(LAYOUTS, chosen, strict=False)):
        progress(65 + i * 10, f"Componiendo la miniatura {i + 1} de 3")
        background = backgrounds[i % len(backgrounds)]
        name = f"miniatura-{i + 1}.jpg"
        compose(background, text.text, text.highlight, layout, size, out_folder / name)
        variants.append(
            {
                "file": name,
                "text": text.text,
                "highlight": text.highlight,
                "layout": layout,
                "source": sources[i % len(sources)],
            }
        )
    progress(100, "Miniaturas listas")
    return {"variants": variants, "selected": None, "notes": notes, "portrait": portrait}
