"""CHART ENGINE: gráficos animados con las cifras del guion.

1. Gemini busca en el guion los párrafos con cifras que se entienden mejor con un
   gráfico (cuota de mercado que cae, ventas por año, una pérdida enorme…).
2. Cada cifra se comprueba: tiene que aparecer en el guion o en la investigación. Si no,
   el gráfico se descarta (nunca se inventan datos).
3. Al montar, esa escena muestra el gráfico animado con el estilo del canal: barras que
   crecen, una línea que se dibuja o un contador que sube, sobre la imagen de la escena
   oscurecida y desenfocada.
"""

import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel, Field

from app.models import Project
from app.providers.ai import AIProvider, ProviderError

KINDS = ("bars", "line", "counter")
RED = (230, 57, 70)
WHITE = (242, 238, 238)
MUTED = (150, 156, 170)
DARK = (8, 10, 16)
ANIMATION_SECONDS = 2.4


class Point(BaseModel):
    label: str = Field(description="Etiqueta: un año, una empresa, «antes»…")
    value: float


class ChartSpec(BaseModel):
    paragraph: int = Field(description="Número del párrafo donde se dice la cifra")
    kind: Literal["bars", "line", "counter"]
    title: str = Field(description="Título corto del gráfico (máx. 45 caracteres)")
    unit: str = Field(default="", description="Unidad: %, millones de USD, tiendas…")
    points: list[Point]


class ChartPlan(BaseModel):
    charts: list[ChartSpec]


# ---------------------------------------------------------------- cifras reales


def number_forms(value: float) -> set[str]:
    """Formas en que puede estar escrita una cifra en el texto (63000, 63.000, 63,5…)."""
    forms = set()
    if float(value).is_integer():
        n = int(abs(value))
        forms |= {str(n), f"{n:,}".replace(",", "."), f"{n:,}", f"{n:,}".replace(",", " ")}
    else:
        v = abs(value)
        for digits in (1, 2):
            text = f"{v:.{digits}f}"
            forms |= {text, text.replace(".", ",")}
    return forms


def _clean(text: str) -> str:
    return text.replace("\xa0", " ").replace(" ", " ")


def value_in_text(value: float, text: str) -> bool:
    text = _clean(text)
    for form in number_forms(value):
        if re.search(rf"(?<![\d.,]){re.escape(form)}(?![\d]|[.,]\d)", text):
            return True
    return False


def paragraphs_of(script: dict) -> list[dict]:
    return [p for s in script.get("sections", []) for p in s["paragraphs"]]


def research_text(research: dict) -> str:
    parts = [research.get("context", ""), research.get("summary", "")]
    for key in ("key_facts", "timeline", "figures", "data"):
        for item in research.get(key, []) or []:
            parts.append(item.get("text", "") if isinstance(item, dict) else str(item))
    return " ".join(parts)


def validate(spec: ChartSpec, paragraphs: list[dict], extra_text: str) -> dict | None:
    """El gráfico solo vale si todas sus cifras salen en el guion o la investigación."""
    if not 1 <= spec.paragraph <= len(paragraphs) or spec.kind not in KINDS:
        return None
    points = [p for p in spec.points if math.isfinite(p.value) and p.label.strip()][:8]
    if spec.kind == "counter":
        points = points[:1]
        if len(points) != 1 or points[0].value <= 0:
            return None
    elif spec.kind == "bars" and not 2 <= len(points) <= 6:
        return None
    elif spec.kind == "line" and len(points) < 3:
        return None
    if spec.kind != "counter" and any(p.value < 0 for p in points):
        return None
    text = paragraphs[spec.paragraph - 1]["text"] + " " + extra_text
    if not all(value_in_text(p.value, text) for p in points):
        return None
    return {
        "paragraph_id": paragraphs[spec.paragraph - 1]["id"],
        "kind": spec.kind,
        "title": spec.title.strip()[:45],
        "unit": spec.unit.strip()[:24],
        "points": [{"label": p.label.strip()[:14], "value": p.value} for p in points],
    }


def _prompt(project: Project, paragraphs: list[dict], limit: int) -> str:
    table = "\n".join(f"[{n}] {p['text']}" for n, p in enumerate(paragraphs, 1))
    return f"""Eres editor de documentales para YouTube («{project.title}»).
Busca en el guion como mucho {limit} momentos donde un GRÁFICO ANIMADO ayude a entender
una cifra. Tipos:
- bars: comparar 2–6 valores (años, empresas, antes/después).
- line: evolución en el tiempo (3 o más años).
- counter: una sola cifra impactante que sube (una pérdida, unas ventas, un récord).
REGLAS: usa SOLO cifras que aparezcan escritas en el guion; no inventes ni estimes nada.
Si un párrafo no tiene cifras claras, no lo uses. Indica el número de párrafo.

GUION:
{table}"""


def plan_charts(
    project: Project, script: dict, research: dict, ai: AIProvider, total_seconds: float = 0
) -> dict[str, dict]:
    """paragraph_id → especificación del gráfico (ya validada)."""
    paragraphs = paragraphs_of(script)
    if not paragraphs:
        return {}
    limit = max(1, min(6, round((total_seconds or len(paragraphs) * 15) / 100)))
    try:
        plan = ai.generate_json(_prompt(project, paragraphs, limit), ChartPlan)
    except ProviderError:
        return {}
    extra = research_text(research or {})
    charts: dict[str, dict] = {}
    for spec in plan.charts:
        valid = validate(spec, paragraphs, extra)
        if valid and valid["paragraph_id"] not in charts:
            charts[valid["paragraph_id"]] = valid
        if len(charts) >= limit:
            break
    return charts


# ---------------------------------------------------------------- dibujo


def fmt(value: float) -> str:
    """Cifras en español: 63.000 · 49,5."""
    if abs(value) >= 100 or float(value).is_integer():
        return f"{round(value):,}".replace(",", ".")
    return f"{value:.1f}".replace(".", ",")


def _font(size: int, bold: bool = False):
    from app.pipeline.render import FONTS_DIR, TITLE_FONT, font

    return font(size, TITLE_FONT if not bold else FONTS_DIR / "Montserrat-ExtraBold.ttf")


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def background(path: Path | None, size: tuple[int, int]) -> Image.Image:
    """La imagen de la escena, desenfocada y oscura, para que el gráfico destaque."""
    if path is not None and path.exists():
        try:
            with Image.open(path) as source:
                image = ImageOps.fit(source.convert("RGB"), size)
            image = image.filter(ImageFilter.GaussianBlur(max(size) // 90))
            image = ImageEnhance.Brightness(image).enhance(0.35)
            return image
        except OSError:
            pass
    image = Image.new("RGB", size, DARK)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        shade = int(10 + 14 * y / size[1])
        draw.line([(0, y), (size[0], y)], fill=(shade, shade + 1, shade + 8))
    return image


def draw_frame(spec: dict, size: tuple[int, int], t: float, base: Image.Image) -> Image.Image:
    """Un fotograma del gráfico; `t` va de 0 (empieza) a 1 (animación terminada)."""
    w, h = size
    portrait = h > w
    image = base.copy()
    draw = ImageDraw.Draw(image)
    unit_scale = min(w, h)
    margin = int(w * 0.08)
    # Título con la línea roja de la marca
    title_size = int(unit_scale * (0.075 if portrait else 0.09))
    title_font = _font(title_size)
    title = spec["title"].upper()
    while draw.textlength(title, font=title_font) > w - margin * 2 and title_size > 12:
        title_size -= 2
        title_font = _font(title_size)
    top = int(h * (0.14 if portrait else 0.1))
    draw.text((margin, top), title, font=title_font, fill=WHITE)
    line_y = top + int(title_size * 1.05)
    draw.rectangle(
        [margin, line_y, margin + int(w * 0.12 * _ease(t * 2)), line_y + max(3, h // 180)],
        fill=RED,
    )
    if spec["unit"] and spec["unit"] != "%" and spec["kind"] != "counter":
        unit_font = _font(int(unit_scale * 0.04), bold=True)
        draw.text((margin + int(w * 0.14), line_y - int(unit_scale * 0.018)), spec["unit"],
                  font=unit_font, fill=MUTED)  # fmt: skip
    # Abajo queda sitio para los subtítulos (en vertical, más arriba por los botones).
    area = (margin, line_y + int(h * 0.08), w - margin, int(h * (0.68 if portrait else 0.78)))
    {"bars": _bars, "line": _line, "counter": _counter}[spec["kind"]](
        draw, spec, area, _ease(t), unit_scale
    )
    return image


def _bars(draw, spec, area, p, scale):
    x0, y0, x1, y1 = area
    points = spec["points"]
    top_value = max(pt["value"] for pt in points) or 1
    label_font = _font(int(scale * 0.045), bold=True)
    value_font = _font(int(scale * 0.07))
    gap = (x1 - x0) * 0.04
    bar_w = ((x1 - x0) - gap * (len(points) - 1)) / len(points)
    base_y = y1 - int(scale * 0.07)
    for i, pt in enumerate(points):
        delay = i * 0.12  # cada barra empieza un poco después
        grow = max(0.0, min(1.0, (p - delay) / (1 - delay * 0.5))) if p < 1 else 1.0
        bar_h = (base_y - y0 - scale * 0.1) * pt["value"] / top_value * grow
        bx = x0 + i * (bar_w + gap)
        color = RED if i == len(points) - 1 else WHITE
        draw.rectangle([bx, base_y - bar_h, bx + bar_w, base_y], fill=color)
        value = fmt(pt["value"] * grow) + (" %" if spec["unit"] == "%" else "")
        vw = draw.textlength(value, font=value_font)
        draw.text((bx + (bar_w - vw) / 2, base_y - bar_h - scale * 0.085), value,
                  font=value_font, fill=WHITE)  # fmt: skip
        lw = draw.textlength(pt["label"], font=label_font)
        draw.text((bx + (bar_w - lw) / 2, base_y + scale * 0.015), pt["label"],
                  font=label_font, fill=MUTED)  # fmt: skip


def _line(draw, spec, area, p, scale):
    x0, y0, x1, y1 = area
    points = spec["points"]
    values = [pt["value"] for pt in points]
    low, high = min(values), max(values)
    span = (high - low) or 1
    label_font = _font(int(scale * 0.042), bold=True)
    value_font = _font(int(scale * 0.06))
    base_y = y1 - int(scale * 0.07)
    top_y = y0 + int(scale * 0.08)
    coords = [
        (
            x0 + (x1 - x0) * i / (len(points) - 1),
            base_y - (base_y - top_y) * (pt["value"] - low) / span * 0.9 - (base_y - top_y) * 0.05,
        )
        for i, pt in enumerate(points)
    ]
    draw.line([(x0, base_y), (x1, base_y)], fill=(70, 74, 88), width=max(2, int(scale * 0.004)))
    reach = p * (len(coords) - 1)  # hasta dónde se ha dibujado la línea
    drawn = [coords[0]]
    for i in range(1, len(coords)):
        if reach >= i:
            drawn.append(coords[i])
        elif reach > i - 1:
            f = reach - (i - 1)
            (ax, ay), (bx, by) = coords[i - 1], coords[i]
            drawn.append((ax + (bx - ax) * f, ay + (by - ay) * f))
            break
    if len(drawn) > 1:
        draw.line(drawn, fill=RED, width=max(4, int(scale * 0.012)), joint="curve")
    r = max(5, int(scale * 0.014))
    for i, (cx, cy) in enumerate(coords):
        lw = draw.textlength(points[i]["label"], font=label_font)
        draw.text((cx - lw / 2, base_y + scale * 0.015), points[i]["label"], font=label_font,
                  fill=MUTED)  # fmt: skip
        if reach >= i - 0.001:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
            value = fmt(points[i]["value"]) + (" %" if spec["unit"] == "%" else "")
            vw = draw.textlength(value, font=value_font)
            draw.text((cx - vw / 2, cy - scale * 0.085), value, font=value_font, fill=WHITE)


def _counter(draw, spec, area, p, scale):
    x0, y0, x1, y1 = area
    point = spec["points"][0]
    text = fmt(point["value"] * p) + (" %" if spec["unit"] == "%" else "")
    size = int(scale * 0.32)
    big = _font(size)
    while draw.textlength(text, font=big) > (x1 - x0) and size > 20:
        size -= 6
        big = _font(size)
    tw = draw.textlength(text, font=big)
    cy = (y0 + y1) / 2 - size * 0.55
    draw.text(((x0 + x1 - tw) / 2, cy), text, font=big, fill=RED)
    under = spec["unit"] if spec["unit"] and spec["unit"] != "%" else point["label"]
    small = _font(int(scale * 0.06), bold=True)
    uw = draw.textlength(under.upper(), font=small)
    draw.text(((x0 + x1 - uw) / 2, cy + size * 1.05), under.upper(), font=small, fill=WHITE)


def preview(spec: dict, size: tuple[int, int], path: Path, bg: Path | None = None) -> Path:
    """Imagen fija del gráfico terminado (para verlo en la página de escenas)."""
    draw_frame(spec, size, 1.0, background(bg, size)).save(path)
    return path


# ---------------------------------------------------------------- vídeo


def chart_clip(
    spec: dict,
    out: Path,
    size: tuple[int, int],
    fps: int,
    seconds: float,
    bg: Path | None = None,
) -> Path:
    """Clip del gráfico animado: la animación y luego el gráfico quieto hasta el final."""
    from app.pipeline.render import ffmpeg_exe

    w, h = size
    base = background(bg, size)
    anim = min(ANIMATION_SECONDS, seconds * 0.7)
    frames = max(2, int(round(anim * fps)))
    cmd = [
        ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={max(0.0, seconds - anim) + 0.2:.3f}",
        "-t",
        f"{seconds:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "16",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    try:
        for i in range(frames):
            frame = draw_frame(spec, size, i / (frames - 1), base)
            proc.stdin.write(frame.convert("RGB").tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    error = proc.stderr.read().decode(errors="ignore")
    if proc.wait() != 0:
        raise RuntimeError(f"FFmpeg falló creando el gráfico: {error[-400:]}")
    return out
