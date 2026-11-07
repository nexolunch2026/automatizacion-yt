"""THUMBNAIL ENGINE: tres miniaturas con el estilo del canal para elegir la mejor.

- Fondo: las imágenes más llamativas del vídeo (más color y contraste) y, si se puede,
  una imagen nueva creada con IA a partir del concepto de miniatura de la estrategia.
- Texto: 2–4 palabras enormes en Bebas Neue, blanco con borde, y la palabra clave en el
  rojo de la marca. Tres composiciones distintas (texto a la izquierda, abajo, centrado).
- Con imágenes de Google Flow (stickman): solo se usan esas, sin fondo de IA aparte, y las
  composiciones son las que mejor funcionan en el canal: texto a un lado, pantalla partida
  «antes / después» con una palabra en cada mitad, y frase abajo (sin tapar caras).
- Salida: JPG de 1280×720 (o 1080×1920 en los Shorts), por debajo de los 2 MB de YouTube.
"""

import random
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat
from pydantic import BaseModel, Field

from app.models import Project
from app.pipeline import accent
from app.pipeline.render import TITLE_FONT, font
from app.providers.ai import AIProvider, ProviderError

LANDSCAPE = (1280, 720)
PORTRAIT = (1080, 1920)
LAYOUTS = ["left", "bottom", "center"]
FLOW_LAYOUTS = ["left", "split", "bottom"]  # con Flow (arriba taparía las cabezas)
ALL_LAYOUTS = [*LAYOUTS, "split", "top"]
MIN_FLOW_IMAGES = 4
SPLIT_SEP = "|"  # «SE RIÓ | QUEBRÓ»: una palabra para cada mitad
WHITE = (255, 255, 255)
YELLOW = (255, 214, 10)
MAX_BYTES = 1_900_000


class ThumbText(BaseModel):
    text: str = Field(description="2 a 4 palabras, impactantes, en mayúsculas")
    highlight: str = Field(description="La palabra (o cifra) que irá en rojo")


class ThumbTexts(BaseModel):
    texts: list[ThumbText]


class ThumbPlan(BaseModel):
    main: int = Field(description="Escena con la imagen más potente para la miniatura principal")
    second: int = Field(description="Otra escena muy llamativa (distinta de la principal)")
    left: int = Field(description="Escena del ANTES (gloria, inicio) para la pantalla partida")
    right: int = Field(description="Escena del DESPUÉS (caída, final) para la pantalla partida")
    left_text: str = Field(description="1 o 2 palabras para la mitad izquierda, en mayúsculas")
    right_text: str = Field(description="1 o 2 palabras para la mitad derecha, en mayúsculas")


# ---------------------------------------------------------------- textos


def _prompt(project: Project, strategy: dict, script: dict, hint: str = "") -> str:
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
- De 2 a 4 palabras, que despierten curiosidad sin repetir el título: se ven juntos, así
  que la miniatura debe añadir algo (una cifra, una emoción, una pregunta) que el título
  no dice.
- Uno con una cifra o un año si el tema lo permite (solo si es real y está en el guion).
- Honestos: nada que el vídeo no cuente.
- Indica en «highlight» la palabra que irá en rojo (la más fuerte).""" + (
        f"\n- {hint}" if hint else ""
    )


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


def make_texts(
    project: Project, strategy: dict, script: dict, ai: AIProvider | None, hint: str = ""
) -> list:
    texts: list[ThumbText] = []
    if ai is not None:
        try:
            texts = ai.generate_json(_prompt(project, strategy, script, hint), ThumbTexts).texts
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


def flow_scenes(visuals: dict, scenes: list[dict], folder: Path) -> list[dict]:
    """Las escenas que tienen imagen de Google Flow: [{"number", "path", "prompt"}]."""
    items = visuals.get("items", {})
    found = []
    for scene in scenes:
        entry = items.get(scene.get("paragraph_id")) or {}
        name = entry.get("file")
        if entry.get("provider") == "flow" and name and (folder / name).exists():
            found.append(
                {
                    "number": scene["number"],
                    "path": folder / name,
                    "prompt": (scene.get("image_prompt") or scene.get("visual") or "")[:220],
                    "narration": " ".join((scene.get("narration") or "").split())[:160],
                }
            )
    return found


def _plan_prompt(project: Project, strategy: dict, script: dict, scenes: list[dict]) -> str:
    concept = {}
    if strategy and strategy.get("selected"):
        concept = strategy["concepts"][strategy["selected"]["concept"]]
    listing = "\n".join(
        f"{s['number']}. Imagen: {s['prompt']} | Narración: {s['narration']}" for s in scenes
    )
    title = script.get("title") or project.title
    return f"""Eres experto en miniaturas de YouTube. Vídeo: «{title}».
Gancho: {concept.get("hook", "")}. Idioma de los textos: {project.language}.
Estas son las escenas del vídeo (ilustraciones stickman):
{listing}

Elige escenas para tres miniaturas:
- «main»: la imagen más potente y fácil de entender en pequeño (un momento clave, con emoción).
- «second»: otra muy llamativa, distinta.
- Pantalla partida «antes / después»: «left» (la gloria o el inicio) y «right» (la caída o el
  final), con una o dos palabras para cada mitad que cuenten el contraste («SE RIÓ» / «QUEBRÓ»,
  «2002» / «2020»). Honestas: nada que el vídeo no cuente."""


def _best(scenes: list[dict]) -> list[dict]:
    scored = []
    for scene in scenes:
        try:
            scored.append((_score(scene["path"]), scene))
        except OSError:
            continue
    scored.sort(key=lambda s: s[0], reverse=True)
    return [s for _, s in scored]


def plan_flow(
    project: Project, strategy: dict, script: dict, scenes: list[dict], ai: AIProvider | None
) -> dict:
    """Qué imágenes de Flow usar: {"main", "second", "left", "right"} (escenas) y el texto de
    la pantalla partida. La IA las elige leyendo las escenas; si no puede, las más llamativas
    (y para el antes/después, una del principio y otra del final)."""
    by_number = {s["number"]: s for s in scenes}
    ranked = _best(scenes)
    third = max(1, len(scenes) // 3)
    early = _best(scenes[:third]) or ranked
    late = _best(scenes[-third:]) or ranked
    plan = {
        "main": ranked[0],
        "second": ranked[1] if len(ranked) > 1 else ranked[0],
        "left": early[0],
        "right": late[0],
        "split_text": f"ANTES {SPLIT_SEP} DESPUÉS",
        "by": "color",
    }
    if ai is None:
        return plan
    try:
        answer = ai.generate_json(_plan_prompt(project, strategy, script, scenes), ThumbPlan)
    except ProviderError:
        return plan
    picks = {k: by_number.get(getattr(answer, k)) for k in ("main", "second", "left", "right")}
    for key, scene in picks.items():
        if scene is not None:
            plan[key] = scene
    if plan["second"] is plan["main"]:
        plan["second"] = next((s for s in ranked if s is not plan["main"]), plan["main"])
    left, right = answer.left_text.strip().upper(), answer.right_text.strip().upper()
    if left and right and len((left + " " + right).split()) <= 5:
        plan["split_text"] = f"{left} {SPLIT_SEP} {right}"
    plan["by"] = "IA"
    return plan


def split_text(text: str) -> tuple[str, str]:
    """«SE RIÓ | QUEBRÓ» → ("SE RIÓ", "QUEBRÓ"). Sin «|», se parte por la mitad."""
    if SPLIT_SEP in text:
        left, right = text.split(SPLIT_SEP, 1)
        return left.strip(), right.strip()
    words = text.split()
    cut = max(1, len(words) // 2)
    return " ".join(words[:cut]), " ".join(words[cut:])


def ai_background(strategy: dict, project: Project, images, portrait: bool, out: Path) -> Path:
    concept = strategy["concepts"][strategy["selected"]["concept"]] if strategy else {}
    thumb = concept.get("thumbnail", {})
    idea = thumb.get("composition") or thumb.get("concept") or project.title
    from app.flow import STICKMAN_STYLE

    prompt = (
        f"YouTube thumbnail background: {idea}. One clear subject, strong contrast, bold "
        f"colors. Style: {STICKMAN_STYLE}"
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
    elif direction == "top":
        span = int(h * 0.5)
        for i in range(span):
            draw.line([(0, i), (w, i)], fill=int(strength * (1 - i / span) ** 1.3))
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
            draw.rectangle(
                [x - pad, y + size * 0.06, x + width + pad, y + size * 0.98], fill=accent.color()
            )
            draw.text((x, y), word, font=fnt, fill=WHITE)
        else:
            draw.text((x + stroke, y + stroke), word, font=fnt, fill=(0, 0, 0))  # sombra
            draw.text(
                (x, y), word, font=fnt, fill=accent.color() if hot else WHITE,
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
    info: dict | None = None,
    second: Path | None = None,
) -> Path:
    """Dibuja la miniatura. Si se pasa `info`, apunta el tamaño de la letra (para saber
    si se lee en pequeño). `second` es la otra imagen de la pantalla partida."""
    w, h = size
    portrait = h > w
    if portrait and layout == "left":
        layout = "bottom"
    if layout == "split":
        return _compose_split(background, second, text, size, out, info)
    image = _cover(background, size, focus_x=0.7 if layout == "left" else 0.5).convert("RGBA")
    if layout == "left":
        image.alpha_composite(_gradient(size, "left"))
    elif layout == "top":
        image.alpha_composite(_gradient(size, "top", 225))
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
        draw.rectangle(
            [margin, y + h * 0.045, margin + w * 0.12, y + h * 0.06], fill=accent.color()
        )
    elif layout == "bottom":
        fnt, fsize = _fit(draw, lines, w - margin * 2, int(h * 0.44), int(h * 0.3))
        block = int(fsize * 0.92) * len(lines)
        y = h - block - int(h * 0.07)
        draw.rectangle(
            [margin, y - h * 0.035, margin + w * 0.14, y - h * 0.018], fill=accent.color()
        )
        for line in lines:
            _draw_words(draw, line, margin, y, fnt, fsize, marked, box=False)
            y += int(fsize * 0.92)
    elif layout == "top":
        fnt, fsize = _fit(draw, lines, w - margin * 2, int(h * 0.36), int(h * 0.2))
        y = int(h * 0.035)
        for line in lines:
            lw = draw.textlength(line, font=fnt)
            _draw_words(draw, line, (w - lw) / 2, y, fnt, fsize, marked, box=False)
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
    if info is not None:
        info.update(font_ratio=fsize / h, lines=len(lines))
    # Marco fino rojo abajo: firma visual del canal en todas las miniaturas.
    draw.rectangle([0, h - max(6, h // 120), w, h], fill=accent.color())
    return _save(image, out)


def _save(image: Image.Image, out: Path) -> Path:
    rgb = image.convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    for quality in (92, 85, 75, 65):
        rgb.save(out, "JPEG", quality=quality, optimize=True)
        if out.stat().st_size <= MAX_BYTES:
            break
    return out


def _compose_split(
    first: Path | None,
    second: Path | None,
    text: str,
    size: tuple[int, int],
    out: Path,
    info: dict | None,
) -> Path:
    """Pantalla partida «antes / después»: dos imágenes separadas por una raya blanca y una
    palabra grande en cada mitad (amarilla la primera, del color del canal la segunda)."""
    w, h = size
    gap = max(6, w // 160)
    if h > w:  # vertical: una arriba y otra abajo
        half = (w, (h - gap) // 2)
        spots = [(0, 0), (0, half[1] + gap)]
    else:
        half = ((w - gap) // 2, h)
        spots = [(0, 0), (half[0] + gap, 0)]
    image = Image.new("RGBA", size, (255, 255, 255, 255))
    for path, spot in zip((first, second or first), spots, strict=True):
        part = _cover(path, half).convert("RGBA")
        part.alpha_composite(_gradient(half, "bottom", 215))
        image.alpha_composite(part, spot)
    draw = ImageDraw.Draw(image)
    fsize = 0
    for label, color, (x0, y0) in zip(
        split_text(text), (YELLOW, accent.color()), spots, strict=True
    ):
        if not label:
            continue
        line = label.upper()
        fnt, fsize = _fit(
            draw, [line], int(half[0] * 0.88), int(half[1] * 0.3), int(half[1] * 0.24)
        )
        x = x0 + (half[0] - draw.textlength(line, font=fnt)) / 2
        y = y0 + half[1] - int(fsize * 0.92) - int(half[1] * 0.06)
        stroke = max(3, fsize // 22)
        draw.text((x + stroke, y + stroke), line, font=fnt, fill=(0, 0, 0))
        draw.text((x, y), line, font=fnt, fill=color, stroke_width=stroke, stroke_fill=(0, 0, 0))
    if info is not None:
        info.update(font_ratio=fsize / h, lines=1)
    draw.rectangle([0, h - max(6, h // 120), w, h], fill=accent.color())
    return _save(image, out)


# ---------------------------------------------------------------- se lee en pequeño

SMALL_HEIGHT = 94  # alto de la miniatura en pequeño (168 px de ancho: búsqueda y laterales)
MIN_LETTER_PX = 12  # por debajo, el texto no se lee de un vistazo
MAX_WORDS = 5


def mobile_check(text: str, font_ratio: float, portrait: bool = False) -> dict:
    """¿Se lee el texto de la miniatura cuando se ve pequeña? Letra y número de palabras."""
    height = 168 if portrait else SMALL_HEIGHT  # los Shorts se ven en vertical
    px = round(font_ratio * height)
    words = len(text.split())
    problems = []
    if font_ratio and px < MIN_LETTER_PX:
        problems.append(f"letra de {px} px en pequeño: acorta el texto")
    if words > MAX_WORDS:
        problems.append(f"{words} palabras: mejor 2–4")
    return {"ok": not problems, "px": px, "problems": problems}


# Palabras cortas o de relleno que no cuentan como «repetir el título».
TITLE_SKIP = {"como", "para", "porque", "cuando", "donde", "esta", "este", "todo", "toda",
              "nadie", "sobre", "entre", "desde", "hasta", "nunca", "historia"}  # fmt: skip


def _content_words(text) -> list[str]:
    plain = unicodedata.normalize("NFD", str(text or "").lower())
    plain = "".join(ch for ch in plain if unicodedata.category(ch) != "Mn")
    words = re.findall(r"[a-zñ0-9]+", plain)
    return [w for w in words if (len(w) >= 4 or w.isdigit()) and w not in TITLE_SKIP]


def title_repeat(text: str, title: str) -> dict:
    """¿El texto de la miniatura repite el título? Título y miniatura se ven juntos: si
    dicen lo mismo, se desperdicia la miniatura. Avisa si repite 2 palabras del título o
    si todo lo que dice ya está en el título. `ok` es None si no hay con qué comparar
    (sin título o con un texto sin palabras largas, como «¡YA!»)."""
    mine = list(dict.fromkeys(_content_words(text)))
    in_title = set(_content_words(title))
    if not mine or not in_title:
        return {"ok": None, "repeated": []}
    repeated = [w for w in mine if w in in_title]
    ok = not repeated or (len(repeated) < 2 and len(repeated) < len(mine))
    return {"ok": ok, "repeated": repeated}


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
    hint: str = "",
    rotate: int = 0,
    scenes: list[dict] | None = None,
    previous: dict | None = None,
) -> dict:
    """`hint`: lo que suele ganar en el canal (para Gemini). `rotate`: cuánto se turnan las
    posiciones del texto (izquierda, abajo, centro) entre proyectos, para que en «Probar y
    comparar» no gane siempre la misma posición solo por ir en la primera miniatura."""
    progress(10, "Eligiendo las imágenes más llamativas del vídeo")
    size = PORTRAIT if portrait else LANDSCAPE
    flow = flow_scenes(visuals, scenes or [], visuals_folder)
    if len(flow) >= MIN_FLOW_IMAGES:
        return _run_flow(
            project, strategy, script, flow, out_folder, ai, progress, texts, size, portrait,
            previous, hint,
        )  # fmt: skip
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
        chosen = make_texts(project, strategy, script, ai, hint)

    variants = []
    shift = rotate % len(LAYOUTS)
    layouts = LAYOUTS[shift:] + LAYOUTS[:shift]
    for i, (layout, text) in enumerate(zip(layouts, chosen, strict=False)):
        progress(65 + i * 10, f"Componiendo la miniatura {i + 1} de 3")
        background = backgrounds[i % len(backgrounds)]
        name = f"miniatura-{i + 1}.jpg"
        drawn: dict = {}
        compose(background, text.text, text.highlight, layout, size, out_folder / name, drawn)
        variants.append(
            {
                "file": name,
                "text": text.text,
                "highlight": text.highlight,
                "layout": "bottom" if portrait and layout == "left" else layout,  # lo dibujado
                "source": sources[i % len(sources)],
                "mobile": mobile_check(text.text, drawn.get("font_ratio", 0), portrait),
            }
        )
    progress(100, "Miniaturas listas")
    return {"variants": variants, "selected": None, "notes": notes, "portrait": portrait}


def _run_flow(
    project,
    strategy,
    script,
    flow,
    out_folder,
    ai,
    progress,
    texts,
    size,
    portrait,
    previous,
    hint="",
) -> dict:
    """Miniaturas con las imágenes de Flow: texto a un lado, pantalla partida y texto abajo.
    Al cambiar solo los textos se reutilizan las mismas imágenes."""
    by_name = {s["path"].name: s for s in flow}
    before = (previous or {}).get("variants", [])
    old = [v.get("images") for v in before]
    reuse = (
        bool(texts) and len(old) == 3 and all(o and all(name in by_name for name in o) for o in old)
    )
    if reuse:
        picks = [[by_name[n] for n in o] for o in old]
        split, by = (
            before[1].get("text") or f"ANTES {SPLIT_SEP} DESPUÉS",
            (previous or {}).get("picked_by", ""),
        )
    else:
        progress(25, "Eligiendo las mejores escenas para la miniatura")
        plan = plan_flow(project, strategy, script, flow, ai)
        picks = [[plan["main"]], [plan["left"], plan["right"]], [plan["second"]]]
        split, by = plan["split_text"], plan["by"]
    progress(55, "Escribiendo los textos de la miniatura")
    if texts:
        chosen = [ThumbText(**t) for t in texts][:3]
        while len(chosen) < 3:
            chosen.append(chosen[-1])
        if len(texts) < 2:  # solo cambió el primero: la partida conserva sus palabras
            chosen[1] = ThumbText(text=split, highlight="")
    else:
        made = make_texts(project, strategy, script, ai, hint)
        chosen = [made[0], ThumbText(text=split, highlight=""), made[1]]
    out_folder.mkdir(parents=True, exist_ok=True)
    for old_file in out_folder.glob("*"):
        if old_file.is_file():
            old_file.unlink(missing_ok=True)
    variants = []
    for i, (layout, text, images) in enumerate(zip(FLOW_LAYOUTS, chosen, picks, strict=True)):
        progress(65 + i * 10, f"Componiendo la miniatura {i + 1} de 3")
        name = f"miniatura-{i + 1}.jpg"
        drawn: dict = {}
        compose(
            images[0]["path"], text.text, text.highlight, layout, size, out_folder / name,
            drawn, second=images[1]["path"] if len(images) > 1 else None,
        )  # fmt: skip
        variants.append(
            {
                "file": name,
                "text": text.text,
                "highlight": text.highlight,
                "layout": layout,
                "source": "escena " + " y ".join(str(s["number"]) for s in images),
                "images": [s["path"].name for s in images],
                "mobile": mobile_check(
                    text.text.replace(SPLIT_SEP, " "), drawn.get("font_ratio", 0), portrait
                ),
            }
        )
    progress(100, "Miniaturas listas")
    notes = ["Hechas con las imágenes de Google Flow del vídeo."]
    if by == "IA":
        notes.append("La IA eligió las escenas leyendo de qué trata cada una.")
    return {
        "variants": variants,
        "selected": None,
        "notes": notes,
        "portrait": portrait,
        "picked_by": by,
    }
