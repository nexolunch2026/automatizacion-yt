"""VIDEO EDITING ENGINE: monta el vídeo con FFmpeg a partir de escenas, visuales y voz.

Cada escena dura exactamente lo que dura su narración (más la pausa entre párrafos), así
la imagen y la voz siempre van sincronizadas.

Acabado («paquete de calidad»):
- Las fotos se dividen en planos de 3–6 s con movimientos distintos (zoom de entrada, de
  salida, paneos), calculados a mayor resolución para que el movimiento sea suave.
- Fundidos encadenados entre escenas.
- Subtítulos animados palabra a palabra con la tipografía de la marca (ASS + libass).
- Música de fondo que baja sola cuando habla la voz.
- Acabado de cine: contraste suave, viñeta y grano de película.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.pipeline import accent
from app.providers.voice import spoken_text

log = logging.getLogger(__name__)

PAUSE = 0.35  # la misma pausa que se deja entre párrafos al grabar la voz
CROSSFADE = 0.4  # fundido entre escenas (segundos)

QUALITIES = {
    # nombre: (ancho, alto, fps, preset de x264, crf, factor de zoom suave) en horizontal
    "preview": (1280, 720, 30, "veryfast", 24, 2),
    # Zoom suave ×2 (antes ×3): casi el doble de rápido y apenas se nota (Simón, 7 nov 2026).
    "final": (1920, 1080, 30, "veryfast", 20, 2),
    "test": (192, 108, 12, "ultrafast", 35, 1),
}

FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
TITLE_FONT = FONTS_DIR / "BebasNeue-Regular.ttf"
CAPTION_FONT = FONTS_DIR / "Montserrat-ExtraBold.ttf"
CAPTION_FONT_NAME = "Montserrat ExtraBold"

# Colores de la marca
WHITE = (238, 238, 242)
RED = accent.RED  # el de siempre; cada canal puede tener otro (accent.color())
DARK = (13, 14, 18)

DEFAULT_STYLE = {
    "subtitles": True,
    "film_look": True,
    "look": "auto",
    "music": "",
    "music_volume": "media",
    "callouts": True,  # cifras clave que aparecen animadas cuando se dicen
    # Balanceo de toda la imagen. Apagado: Simón quiere que se mueva el PERSONAJE, no la cámara
    # (ver agentes/informes/2026-11-07_animar_al_personaje.md).
    "puppet": False,
}
AUTO = "auto"
# Acabados de color. Se turnan entre vídeos («auto») para que el canal no parezca hecho en
# serie, sin perder la identidad: subtítulos y rojo de la marca son siempre los mismos.
LOOKS = {
    "cine": ("Cine", "eq=contrast=1.06:saturation=0.94,vignette=PI/5,noise=alls=6:allf=t"),
    "calido": (
        "Cálido",
        "eq=contrast=1.05:saturation=1.02,colorbalance=rs=0.06:bs=-0.06,vignette=PI/5",
    ),
    "frio": ("Frío", "eq=contrast=1.08:saturation=0.9,colorbalance=rs=-0.05:bs=0.07,vignette=PI/5"),
    "archivo": (
        "Archivo (tono antiguo)",
        "eq=contrast=1.1:saturation=0.45,colorbalance=rs=0.08:gs=0.03:bs=-0.08,"
        "vignette=PI/4,noise=alls=12:allf=t",
    ),
    "nitido": ("Nítido", "eq=contrast=1.04:saturation=1.05,unsharp=5:5:0.4"),
}


def least_recent(options: list[str], recent: list[str]) -> str:
    """La opción que hace más tiempo que no se usa (`recent`: de la más nueva a la más
    vieja). Las que nunca se han usado van primero."""

    def last_used(key: str) -> int:
        return recent.index(key) if key in recent else len(recent) + 1

    return max(options, key=last_used)


MUSIC_VOLUMES = {"baja": 0.10, "media": 0.16, "alta": 0.24}

# Movimientos de cámara que se van alternando de una escena a otra. Desde la v0.85, además
# de los suaves, los «combinados» tipo CapCut: zoom de golpe, rebote, subida y péndulo.
MOTIONS = [
    "zoom_in",
    "pan_right",
    "punch_in",
    "zoom_out",
    "bounce",
    "pan_left",
    "drift_up",
    "pendulum",
]
# Transiciones entre escenas: fundido la mitad de las veces y, entre medias, otras distintas
# para que no todos los cortes sean iguales.
TRANSITIONS = [
    "smoothleft",
    "zoomin",
    "slideup",
    "fadeblack",
    "smoothright",
    "circleopen",
    "wipeleft",
    "slidedown",
]


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        creationflags=flags,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg falló: {result.stderr.strip()[-500:]}")


def font(size: int, path: Path = TITLE_FONT) -> ImageFont.ImageFont:
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def dimensions(quality: str, portrait: bool) -> tuple[int, int, int, str, int]:
    w, h, fps, preset, crf, _ = QUALITIES[quality]
    return (h, w, fps, preset, crf) if portrait else (w, h, fps, preset, crf)


# ---------------------------------------------------------------- imágenes con texto


def text_card(text: str, size: tuple[int, int], path: Path) -> Path:
    """Tarjeta con el estilo de la marca: fondo oscuro, texto grande y línea roja."""
    w, h = size
    image = Image.new("RGB", size, DARK)
    draw = ImageDraw.Draw(image)
    for y in range(h):  # degradado suave
        shade = int(13 + 16 * y / h)
        draw.line([(0, y), (w, y)], fill=(shade, shade + 1, shade + 8))
    fnt = font(max(int(h * 0.13), 10))
    lines = textwrap.wrap(text.upper(), width=max(int(w / (h * 0.06)), 8))[:4]
    line_h = int(h * 0.14)
    y = (h - line_h * len(lines)) // 2 - int(h * 0.02)
    for line in lines:
        tw = draw.textlength(line, font=fnt)
        draw.text(((w - tw) / 2, y), line, font=fnt, fill=WHITE)
        y += line_h
    bar = int(w * 0.12)
    draw.rectangle(
        [w / 2 - bar, y + h * 0.02, w / 2 + bar, y + h * 0.02 + max(h // 160, 2)],
        fill=accent.color(),
    )
    image.save(path)
    return path


def text_overlay(text: str, size: tuple[int, int], path: Path) -> Path:
    """Texto en pantalla (cifras, fechas, nombres) con el estilo de la marca, arriba a la
    izquierda para no chocar con los subtítulos."""
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    label = text.upper()
    size = max(int(min(h, w * 1.1) * 0.11), 10)  # en vertical manda el ancho
    fnt = font(size)
    tw = draw.textlength(label, font=fnt)
    while tw > w * 0.84 and size > 10:  # que nunca se salga de la pantalla
        size -= 2
        fnt = font(size)
        tw = draw.textlength(label, font=fnt)
    pad = int(size * 0.2)
    x0, y0 = int(w * 0.06), int(h * 0.09)
    box_h = size + pad * 2
    draw.rectangle([x0, y0, x0 + tw + pad * 2, y0 + box_h], fill=(10, 10, 14, 215))
    draw.rectangle(
        [x0, y0 + box_h, x0 + tw + pad * 2, y0 + box_h + max(h // 120, 2)],
        fill=accent.color() + (255,),
    )
    draw.text((x0 + pad, y0 + pad * 0.7), label, font=fnt, fill=WHITE + (255,))
    image.save(path)
    return path


# ---------------------------------------------------------------- cifras animadas

UNITS = (
    r"(?:%|por ciento|mil millones|millones|millón|mil|años|dólares|euros|pesos|personas|"
    r"tiendas|empleados|clientes|usuarios|veces|kilómetros|toneladas)"
)
CALLOUT = re.compile(rf"(?<![\w.,])(\d[\d.,]*)(?:\s+de)?\s*({UNITS})?(?![\w])", re.IGNORECASE)
CALLOUT_SECONDS = 2.4


def find_callout(narration: str, seconds: float) -> dict | None:
    """La cifra más llamativa del párrafo y en qué segundo se dice (aprox.)."""
    best = None
    for match in CALLOUT.finditer(narration):
        number, unit = match.group(1).rstrip(".,"), match.group(2)
        digits = sum(ch.isdigit() for ch in number)
        if not unit and digits < 2:  # «3» suelto no dice nada; «1975» o «50 %» sí
            continue
        score = (2 if unit else 0) + min(digits, 4) / 4
        if best is None or score > best[0]:
            best = (score, match, number, unit)
    if best is None or seconds < 2.5:
        return None
    _, match, number, unit = best
    words_before = len(narration[: match.start()].split())
    total = max(len(narration.split()), 1)
    at = words_before / total * seconds - 0.4  # un poco antes: entra justo al decirlo
    at = max(0.3, min(at, seconds - CALLOUT_SECONDS * 0.6))
    text = f"{number} {unit}".strip() if unit else number
    return {"text": text.replace("por ciento", "%").replace(" %", " %"), "at": round(at, 2)}


def callout_overlay(text: str, size: tuple[int, int], path: Path) -> Path:
    """La cifra, grande y con el color del canal, en una placa oscura en el centro."""
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    label = text.upper()
    font_size = max(int(min(h * 0.16, w * 0.14)), 12)
    fnt = font(font_size)
    while draw.textlength(label, font=fnt) > w * 0.8 and font_size > 12:
        font_size -= 2
        fnt = font(font_size)
    tw = draw.textlength(label, font=fnt)
    pad = int(font_size * 0.35)
    box_w, box_h = int(tw) + pad * 2, int(font_size * 1.15) + pad
    x0, y0 = (w - box_w) // 2, int(h * 0.42) - box_h // 2
    draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=(10, 10, 14, 200))
    draw.rectangle(
        [x0, y0 + box_h, x0 + box_w, y0 + box_h + max(h // 90, 3)], fill=accent.color() + (255,)
    )
    draw.text(((w - tw) / 2, y0 + pad * 0.45), label, font=fnt, fill=accent.color() + (255,))
    image.save(path)
    return path


END_TEXT_SECONDS = 3.0  # el cartel final de los Shorts se ve los últimos 3 s


def end_overlay(text: str, size: tuple[int, int], path: Path) -> Path:
    """Cartel final de un Short («la historia completa, en el canal»): centrado y en dos
    líneas como mucho, por encima de los subtítulos."""
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    words = text.upper().split()
    lines = [" ".join(words[: (len(words) + 1) // 2]), " ".join(words[(len(words) + 1) // 2 :])]
    lines = [line for line in lines if line]
    size = max(int(w * 0.085), 10)
    fnt = font(size)
    while max(draw.textlength(line, font=fnt) for line in lines) > w * 0.8 and size > 10:
        size -= 2
        fnt = font(size)
    pad = int(size * 0.45)
    line_h = int(size * 1.15)
    box_w = int(max(draw.textlength(line, font=fnt) for line in lines)) + pad * 2
    box_h = line_h * len(lines) + pad * 2
    x0, y0 = (w - box_w) // 2, int(h * 0.38) - box_h // 2
    draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=accent.color() + (235,))
    for k, line in enumerate(lines):
        tw = draw.textlength(line, font=fnt)
        draw.text(((w - tw) / 2, y0 + pad + k * line_h), line, font=fnt, fill=WHITE + (255,))
    image.save(path)
    return path


# ---------------------------------------------------------------- planos y clips


def split_shots(seconds: float) -> list[float]:
    """Un solo plano por imagen, con un movimiento suave de principio a fin. (Antes se
    partía en 2-4 planos de la misma imagen con movimientos distintos y daba «rebotes»;
    ahora los párrafos son cortos y cada uno trae su propia imagen.)"""
    return [seconds]


def _motion_filter(motion: str, frames: int) -> tuple[str, str, str]:
    """Expresiones de zoompan (z, x, y) con aceleración suave al principio y al final."""
    p = f"(on/{max(frames - 1, 1)})"
    ease = f"({p}*{p}*(3-2*{p}))"
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if motion == "zoom_out":
        return f"1.15-0.15*{ease}", center_x, center_y
    if motion == "pan_right":
        return "1.12", f"(iw-iw/zoom)*{ease}", center_y
    if motion == "pan_left":
        return "1.12", f"(iw-iw/zoom)*(1-{ease})", center_y
    if motion == "punch_in":  # zoom de golpe al empezar y luego sigue acercándose despacio
        hit = f"min(on/{max(round(frames * 0.12), 1)},1)"
        return f"1+0.10*{hit}*(2-{hit})+0.06*{p}", center_x, center_y
    if motion == "bounce":  # late como un corazón y se va calmando
        beat = max(frames / 3, 1)
        return f"1.08+0.035*sin(2*PI*on/{beat:.1f})*(1-{p})", center_x, center_y
    if motion == "drift_up":  # la cámara sube despacio por la imagen
        return "1.14", center_x, f"(ih-ih/zoom)*(1-{ease})"
    if motion == "pendulum":  # zoom suave; el balanceo lo añade pendulum_filter
        return f"1.10+0.04*{ease}", center_x, center_y
    return f"1+0.15*{ease}", center_x, center_y  # zoom_in


def pendulum_filter(w: int, h: int) -> str:
    """Balanceo de péndulo (±1,2 grados, un vaivén cada 3 s) sin que se vean bordes."""
    bw, bh = int(w * 1.06) // 2 * 2, int(h * 1.06) // 2 * 2
    return (
        f"scale={bw}:{bh},rotate='0.021*sin(2*PI*t/3)':ow=iw:oh=ih:c=black,"
        f"crop={w}:{h}:x='(iw-{w})/2':y='(ih-{h})/2'"
    )


PUPPET_OVERSCAN = 1.05  # margen para que al balancear nunca se vean bordes negros


def puppet_filter(w: int, h: int, seed: int = 0) -> str:
    """«Movimiento de muñeco» (gratis, sin IA): sobre el zoom de cámara, la imagen se balancea
    un poco y rebota como si respirara, igual que un dibujo animado sencillo. Cada escena
    lleva su propio ritmo (`seed`) para que no parezcan todas iguales."""
    bw, bh = int(w * PUPPET_OVERSCAN) // 2 * 2, int(h * PUPPET_OVERSCAN) // 2 * 2
    sway = 2.4 + (seed % 5) * 0.3  # segundos por balanceo (2,4-3,6 s)
    breath = 1.5 + (seed % 3) * 0.25  # segundos por rebote (1,5-2,0 s)
    phase = (seed % 7) * 0.9
    angle = f"0.007*sin(2*PI*(t+{phase:.1f})/{sway:.2f})"  # ±0,4 grados
    bob = f"{h * 0.006:.1f}*sin(2*PI*(t+{phase:.1f})/{breath:.2f})"  # ±0,6 % de alto
    drift = f"{w * 0.004:.1f}*sin(2*PI*(t+{phase:.1f})/{sway * 2:.2f})"
    return (
        f"scale={bw}:{bh},rotate='{angle}':ow=iw:oh=ih:c=black,"
        f"crop={w}:{h}:x='(iw-{w})/2+{drift}':y='(ih-{h})/2+{bob}'"
    )


_qsv: bool | None = None


def has_qsv() -> bool:
    """¿Puede codificar la gráfica Intel (Quick Sync)? Se prueba una vez con un vídeo mínimo.
    FACELESS_NO_QSV=1 lo desactiva (las pruebas automáticas lo usan)."""
    global _qsv
    if os.environ.get("FACELESS_NO_QSV"):
        return False
    if _qsv is None:
        try:
            run_ffmpeg(["-f", "lavfi", "-i", "color=black:s=256x144:d=0.2", "-c:v", "h264_qsv",
                        "-pix_fmt", "nv12", "-f", "null", "-"])  # fmt: skip
            _qsv = True
        except (RuntimeError, OSError):
            _qsv = False
    return _qsv


def _encode(preset: str, crf: int, fps: int) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-an",
    ]


SHORTS_FILL = 0.6  # en los Shorts, la imagen ocupa el 60 % del alto de la pantalla


def blur_fill_height(image: Path, w: int, h: int) -> int | None:
    """En un vídeo vertical, el alto de la franja donde va una imagen horizontal (con fondo
    desenfocado detrás). None si no hace falta: vídeo horizontal, imagen vertical o ilegible.
    Desde la v0.83 la franja es grande (SHORTS_FILL): mostrada entera la imagen se quedaba en
    un tercio de la pantalla y en el móvil el Short parecía vacío; ahora la cámara la recorre
    de un lado a otro para que se vean todos los personajes."""
    if h <= w:
        return None
    try:
        from PIL import Image

        with Image.open(image) as picture:
            iw, ih = picture.size
    except OSError:
        return None
    if iw <= ih * 1.1:  # ya es vertical o casi cuadrada: se recorta como siempre
        return None
    whole = int(w * ih / iw)
    return max(max(whole, int(h * SHORTS_FILL)) // 2 * 2, 2)


def pan_band(seconds: float, fps: int, w: int, fh: int, factor: int, reverse: bool) -> str:
    """Filtro que recorre una imagen ancha de lado a lado en una franja de w×fh (Shorts)."""
    total = int(seconds * fps) + 2
    p = f"min(t/{max(seconds, 0.1):.3f},1)"
    ease = f"({p}*{p}*(3-2*{p}))"
    where = f"(1-{ease})" if reverse else ease
    bw, bh = w * factor // 2 * 2, fh * factor // 2 * 2
    return (
        f"scale=-2:{bh},setsar=1,loop=loop={total}:size=1:start=0,setpts=N/{fps}/TB,"
        # Un paseo corto alrededor del centro (del 30 al 70 %): de borde a borde se cortaban
        # caras al principio y al final de cada escena (v0.84).
        f"crop={bw}:{bh}:x='(iw-ow)*(0.3+0.4*{where})':y=0,"
        f"scale={w}:{fh},fps={fps},trim=duration={seconds:.3f}"
    )


def _end_start(seconds: float) -> float:
    return max(seconds - END_TEXT_SECONDS, 0.3)


def scene_clip(
    scene: dict,
    visual_path: Path,
    kind: str,
    seconds: float,
    out: Path,
    size: tuple[int, int],
    fps: int,
    preset: str,
    crf: int,
    workdir: Path,
    factor: int = 1,
    first_motion: int = 0,
    puppet: bool = False,
    hold_last: bool = False,
) -> None:
    """Clip de una escena. Las fotos se dividen en planos con movimientos distintos.
    `hold_last`: los clips animados de Flow no se repiten en bucle (se vería el salto): si son
    más cortos que la escena, se quedan quietos en su último fotograma."""
    w, h = size
    inputs: list[str] = []
    if kind == "video":
        if hold_last:
            inputs += ["-i", str(visual_path)]
            pad = f"tpad=stop_mode=clone:stop_duration={seconds:.3f},"
        else:
            inputs += ["-stream_loop", "-1", "-i", str(visual_path)]
            pad = ""
        chain = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1,{pad}trim=duration={seconds:.3f}[v0]"
        )
    else:
        inputs += ["-i", str(visual_path)]
        shots = split_shots(seconds)
        # Vertical (Shorts) con imagen horizontal: la imagen ENTERA en el centro y, detrás,
        # la misma ampliada y desenfocada. Recortar el centro dejaba fuera a los personajes.
        fh = blur_fill_height(visual_path, w, h)
        ph = fh or h  # alto de la imagen que se mueve
        bw, bh = w * factor // 2 * 2, ph * factor // 2 * 2
        src = "[0:v]"
        parts = []
        if fh:
            total = int(seconds * fps) + 2
            parts.append("[0:v]split=2[fgsrc][bgsrc]")
            parts.append(
                f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                # (el radio del desenfoque no puede pasar del tamaño de la imagen)
                f"boxblur={max(min(24, w // 8), 1)}:2,eq=brightness=-0.18,setsar=1,"
                f"loop=loop={total}:size=1:start=0,"
                f"setpts=N/{fps}/TB,trim=duration={seconds:.3f}[bg]"
            )
            src = "[fgsrc]"
        if fh:  # la cámara recorre la imagen ancha de un lado a otro
            joined = f"{src}" + pan_band(seconds, fps, w, fh, factor, first_motion % 2 == 1)
        else:
            parts.append(
                f"{src}scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
                f"setsar=1,split={len(shots)}" + "".join(f"[i{k}]" for k in range(len(shots)))
            )
            for k, shot in enumerate(shots):
                frames = max(int(round(shot * fps)), 1)
                z, x, y = _motion_filter(MOTIONS[(first_motion + k) % len(MOTIONS)], frames)
                parts.append(
                    f"[i{k}]zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{ph}:fps={fps}[s{k}]"
                )
            joined = "".join(f"[s{k}]" for k in range(len(shots)))
            joined += f"concat=n={len(shots)}:v=1:a=0"
            if MOTIONS[first_motion % len(MOTIONS)] == "pendulum":
                joined += "," + pendulum_filter(w, ph)
        if puppet:
            joined += "," + puppet_filter(w, ph, first_motion + int(scene.get("number") or 0))
        if fh:
            parts.append(joined + "[fg]")
            parts.append(f"[bg][fg]overlay=0:{(h - fh) // 2}:shortest=1,setsar=1[v0]")
        else:
            parts.append(joined + "[v0]")
        chain = ";".join(parts)
    last = "[v0]"
    if scene.get("on_screen_text"):
        overlay = text_overlay(
            scene["on_screen_text"], size, workdir / f"texto-{scene['number']}.png"
        )
        inputs += ["-loop", "1", "-i", str(overlay)]
        # En los Shorts el gancho sale desde el primer fotograma (sirve de portada).
        fade = "st=0:d=0.04" if scene.get("text_from_start") else "st=0.3:d=0.4"
        # Si hay cartel final, el gancho se quita justo antes para que no se pisen.
        until = f":enable='lt(t,{_end_start(seconds):.3f})'" if scene.get("end_text") else ""
        chain += (
            f";[1:v]format=rgba,fade=t=in:{fade}:alpha=1[o];"
            f"[v0][o]overlay=0:0:shortest=1{until}[v1]"
        )
        last = "[v1]"
    if scene.get("callout"):  # la cifra sube y aparece justo cuando se dice
        info = scene["callout"]
        card = callout_overlay(info["text"], size, workdir / f"cifra-{scene['number']}.png")
        index = inputs.count("-i")
        inputs += ["-loop", "1", "-i", str(card)]
        start = max(0.0, float(info["at"]))
        end = min(start + CALLOUT_SECONDS, max(seconds - 0.3, start + 0.6))
        rise = max(h // 30, 8)
        chain += (
            f";[{index}:v]format=rgba,fade=t=in:st={start:.3f}:d=0.25:alpha=1,"
            f"fade=t=out:st={end - 0.3:.3f}:d=0.3:alpha=1[c];"
            f"{last}[c]overlay=x=0:y='max(0,{rise}*(1-(t-{start:.3f})/0.3))':shortest=1[vc]"
        )
        last = "[vc]"
    if scene.get("end_text"):  # cartel final de los Shorts: lleva al vídeo largo
        card = end_overlay(scene["end_text"], size, workdir / f"final-{scene['number']}.png")
        index = inputs.count("-i")
        inputs += ["-loop", "1", "-i", str(card)]
        start = _end_start(seconds)
        chain += (
            f";[{index}:v]format=rgba,fade=t=in:st={start:.3f}:d=0.25:alpha=1[e];"
            f"{last}[e]overlay=0:0:shortest=1[v2]"
        )
        last = "[v2]"
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            chain,
            "-map",
            last,
            "-t",
            f"{seconds:.3f}",
            *_encode(preset, crf, fps),
            str(out),
        ]
    )


# ---------------------------------------------------------------- subtítulos


def _timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


SRT_LINE_CHARS = 42  # más letras por línea no caben bien en el móvil
SRT_MAX_LINES = 2
SRT_MAX_CPS = 20  # letras por segundo: más deprisa no da tiempo a leerlo


SRT_MIN_SECONDS = 1.0  # un trozo más corto casi no se ve: se junta con el siguiente
CLOSERS = "\"'»”’)]"  # comillas o paréntesis de cierre tras el punto: «fin.»


def _two_lines(text: str) -> str:
    """Parte el texto en dos líneas que quepan (42 letras), lo más parecidas posible."""
    if len(text) <= SRT_LINE_CHARS:
        return text
    middle = len(text) // 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    fit = [i for i in spaces if i <= SRT_LINE_CHARS and len(text) - i - 1 <= SRT_LINE_CHARS]
    cut = min(fit or spaces, key=lambda i: abs(i - middle))
    return f"{text[:cut]}\n{text[cut + 1 :]}"


def _fits(words: list[tuple[str, float, float]]) -> bool:
    """¿Caben estas palabras en 2 líneas de 42 letras?"""
    text = " ".join(word for word, _, _ in words)
    return all(len(line) <= SRT_LINE_CHARS for line in _two_lines(text).split("\n"))


def _cues(text: str, start: float, end: float) -> list[list[tuple[str, float, float]]]:
    """Agrupa las palabras de un párrafo en trozos de subtítulo que se leen bien."""
    cues: list[list[tuple[str, float, float]]] = []
    cue: list[tuple[str, float, float]] = []
    for item in word_times(text, start, end):
        if cue and not _fits([*cue, item]):
            cues.append(cue)
            cue = []
        cue.append(item)
        last = item[0].rstrip(CLOSERS)[-1:] or item[0][-1]
        length = len(" ".join(word for word, _, _ in cue))
        if last in ".!?…" or (last in ",;:" and length >= SRT_LINE_CHARS):
            cues.append(cue)  # mejor cortar donde la voz hace una pausa
            cue = []
    if cue:
        cues.append(cue)
    merged: list[list[tuple[str, float, float]]] = []
    for cue in cues:  # «Sí.» suelto pasa en un suspiro: se junta con lo siguiente
        if merged and merged[-1][-1][2] - merged[-1][0][1] < SRT_MIN_SECONDS:
            if _fits(merged[-1] + cue):
                merged[-1] = merged[-1] + cue
                continue
        merged.append(cue)
    return merged


def build_srt(segments: list[tuple[str, float, float]]) -> str:
    """Subtítulos a partir de (texto, inicio, fin) de cada párrafo: trozos de hasta 2 líneas
    de 42 letras (lo que se lee bien en el móvil), cortando mejor donde hay un punto o una
    coma, y con el tiempo de cada palabra según su longitud."""
    entries, previous_end = [], 0.0
    for text, start, end in segments:
        for cue in _cues(text, start, end):
            begin = max(cue[0][1], previous_end)  # nunca hacia atrás ni encima del anterior
            finish = max(cue[-1][2], begin + 0.001)
            previous_end = finish
            line = _two_lines(" ".join(word for word, _, _ in cue))
            stamp = f"{_timestamp(begin)} --> {_timestamp(finish)}"
            entries.append(f"{len(entries) + 1}\n{stamp}\n{line}\n")
    return "\n".join(entries)


def srt_problems(text: str) -> dict:
    """Trozos de los subtítulos difíciles de leer en el móvil: líneas largas, más de 2
    líneas, demasiado rápidos o dañados (sin tiempos o sin texto).
    {"cues": total, "long": n, "fast": n, "broken": n, "hard": n}, donde «hard» son los
    trozos con algún problema (sin contar dos veces)."""
    cues = long = fast = broken = hard = 0
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if not lines:
            continue
        cues += 1
        times = lines[1] if len(lines) > 1 else ""
        body = lines[2:]
        try:
            begin, finish = (_seconds(t.strip()) for t in times.split("-->"))
        except ValueError:
            begin = finish = None
        if begin is None or finish is None or finish <= begin or not body:
            broken += 1
            hard += 1
            continue
        too_long = len(body) > SRT_MAX_LINES or any(len(line) > SRT_LINE_CHARS for line in body)
        chars = sum(len(line) for line in body)
        too_fast = chars / (finish - begin) > SRT_MAX_CPS
        long += too_long
        fast += too_fast
        hard += too_long or too_fast
    return {"cues": cues, "long": long, "fast": fast, "broken": broken, "hard": hard}


def _seconds(stamp: str) -> float:
    h, m, rest = stamp.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def word_times(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    """Reparte el tiempo de un párrafo entre sus palabras según su longitud (las palabras
    con signos de puntuación reciben un poco más, por la pausa al leerlas)."""
    words = text.split()
    if not words:
        return []
    weights = [len(w) + 3 + (4 if w[-1] in ".,;:!?…" else 0) for w in words]
    total = sum(weights)
    result, t = [], start
    for word, weight in zip(words, weights, strict=True):
        span = (end - start) * weight / total
        result.append((word, t, t + span))
        t += span
    return result


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def build_ass(
    segments: list[tuple[str, float, float]],
    width: int,
    height: int,
    words_per_line: int | None = None,
) -> str:
    """Subtítulos animados: frases cortas en las que la palabra que se está diciendo se
    resalta en el rojo de la marca. En vertical (Shorts): letra según el ancho, 3 palabras
    por línea y más arriba, para que no los tapen los botones de YouTube."""
    portrait = height > width
    words_per_line = words_per_line or (3 if portrait else 5)
    size = max(int(width * 0.1 if portrait else height * 0.064), 8)  # Shorts: letra grande
    outline = max(int(size * 0.07), 1)
    margin = int(height * (0.22 if portrait else 0.08))
    side = int(width * 0.05)
    style_fields = (
        "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    style_values = (
        f"Marca,{CAPTION_FONT_NAME},{size},&H00F2EEEE,&H00F2EEEE,&H00121010,&H96000000,"
        f"0,0,0,0,100,100,0,0,1,{outline},{outline},2,{side},{side},{margin},1"
    )
    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            f"Format: {style_fields}",
            f"Style: {style_values}",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            "",
        ]
    )
    red = accent.ass()  # el color del canal, en formato BGR de ASS
    lines = []
    for text, start, end in segments:
        timed = word_times(text, start, end)
        for i in range(0, len(timed), words_per_line):
            group = timed[i : i + words_per_line]
            for k, (_, w_start, w_end) in enumerate(group):
                shown_until = w_end if k < len(group) - 1 else group[-1][2]
                words = [
                    (f"{{\\c{red}}}{_ass_escape(word)}{{\\r}}" if j == k else _ass_escape(word))
                    for j, (word, _, _) in enumerate(group)
                ]
                lines.append(
                    f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(shown_until)},Marca,,0,0,0,,"
                    + " ".join(words)
                )
    return header + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- montaje completo


def _concat_escape(path: Path) -> str:
    """Escapa la ruta para la lista de FFmpeg (por si la carpeta tiene un apóstrofo)."""
    return path.as_posix().replace("'", "'\\''")


def replace_file(tmp: Path, final: Path, attempts: int = 5) -> Path:
    """Mueve `tmp` a `final`. En Windows, si `final` está abierto (por ejemplo, el vídeo
    anterior en el reproductor) no se puede reemplazar: se reintenta unos segundos y, si
    sigue bloqueado, se guarda con otro nombre para no perder el trabajo."""
    for _ in range(attempts):
        try:
            os.replace(tmp, final)
            return final
        except PermissionError:
            time.sleep(1)
    alternative = final.with_name(f"{final.stem}-{time.strftime('%Y%m%d-%H%M%S')}{final.suffix}")
    os.replace(tmp, alternative)
    return alternative


def _cleanup(path: Path) -> None:
    """Borra carpetas temporales sin fallar si Windows o el antivirus las tiene abiertas."""
    shutil.rmtree(path, ignore_errors=True)


def transition_for(k: int) -> str:
    """La transición del corte nº k: fundido en los pares; en los impares, una distinta cada
    vez (deslizar, zoom, círculo…), siempre en el mismo orden para que el montaje se repita
    igual si se rehace."""
    return "fade" if k % 2 == 0 else TRANSITIONS[(k // 2) % len(TRANSITIONS)]


def _xfade_chain(lengths: list[float], seconds: list[float]) -> tuple[str, str]:
    """Filtro que encadena los clips con fundidos. Cada clip (salvo el último) dura su
    escena + CROSSFADE, y el fundido empieza justo donde empieza la escena siguiente, así
    el vídeo final dura lo mismo que la narración."""
    if len(lengths) == 1:
        return "[0:v]null[vx]", "[vx]"
    parts, previous, offset = [], "[0:v]", 0.0
    for k in range(1, len(lengths)):
        offset += seconds[k - 1]
        label = f"[x{k}]"
        kind = transition_for(k)
        parts.append(
            f"{previous}[{k}:v]xfade=transition={kind}:duration={CROSSFADE}:offset={offset:.3f}{label}"
        )
        previous = label
    return ";".join(parts), previous


CACHE_DIR = "escenas"  # dentro de la carpeta del vídeo


def scene_key(scene: dict, visual: dict | None, length: float, size, fps, crf, factor, motion):
    """Huella de todo lo que cambia el clip de una escena: si es igual, se reutiliza."""
    import hashlib
    import json

    from app.pipeline import accent

    source = None
    if visual and visual.get("kind") != "card":
        path = Path(visual["path"])
        stat = path.stat() if path.exists() else None
        source = [
            str(path),
            visual["kind"],
            stat.st_size if stat else 0,
            stat.st_mtime if stat else 0,
        ]
    data = {
        # 2: Shorts con imagen entera y fondo desenfocado; 3: Shorts con la imagen grande que
        # la cámara recorre (v0.83). Los vídeos horizontales siguen en 2: su caché vale.
        # 4: paseo centrado (v0.84); horizontales 3: movimientos tipo CapCut (v0.85)
        "v": 5 if size[1] > size[0] else 3,
        "scene": {k: v for k, v in scene.items() if k != "number"},  # el nº solo nombra archivos
        "visual": source,
        "length": round(length, 3),
        "size": list(size),
        "fps": fps,
        "crf": crf,
        "factor": factor,
        "motion": motion,
        "accent": accent.color(),
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def first_motion(paragraph_id: str, previous_last: int | None) -> int:
    """Primer movimiento de cámara de una escena: depende solo de su párrafo (así no cambia
    si se toca otra escena) y nunca repite el último plano de la escena anterior."""
    import zlib

    motion = zlib.crc32(paragraph_id.encode("utf-8")) % len(MOTIONS)
    if motion == previous_last:
        motion = (motion + 1) % len(MOTIONS)
    return motion


def _link_or_copy(source: Path, target: Path) -> None:
    """Enlace duro si se puede (no ocupa más disco); si no, copia."""
    try:
        target.unlink(missing_ok=True)
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _build_scene(
    scene, visual, i, length, clip, size, fps, crf, factor, motion, workdir, puppet=False
) -> None:
    w, h = size
    hold_last = False
    if visual is None or visual["kind"] == "card":
        text = scene.get("on_screen_text") or scene.get("visual") or ""
        path = text_card(text, (w * factor, h * factor), workdir / f"tarjeta-{scene['number']}.png")
        kind = "image"
        puppet = False  # los carteles de texto, quietos
        scene = {**scene, "on_screen_text": ""}  # el texto ya va en la tarjeta
    else:
        path, kind = Path(visual["path"]), visual["kind"]
        hold_last = bool(visual.get("animated"))  # clip animado de Flow: sin bucle
    if scene.get("chart"):  # gráfico animado con las cifras de esta escena
        from app.pipeline.charts import chart_clip

        background = path if kind == "image" and visual and visual["kind"] != "card" else None
        path = chart_clip(
            scene["chart"], workdir / f"grafico-{i:03}.mp4", (w, h), fps, length, background
        )
        kind, hold_last = "video", False
        scene = {**scene, "on_screen_text": ""}  # el gráfico ya lleva su título
    # Clips intermedios casi sin pérdida: se recodifican una vez más al final.
    scene_clip(
        scene,
        path,
        kind,
        length,
        clip,
        (w, h),
        fps,
        "veryfast",
        max(crf - 6, 12),
        workdir,
        factor,
        motion,
        puppet=puppet,
        hold_last=hold_last,
    )


def render_video(
    scenes: list[dict],
    visuals: dict,
    takes: dict,
    narration: Path,
    folder: Path,
    quality: str,
    portrait: bool,
    progress: Callable[[int, str], None],
    style: dict | None = None,
    music: Path | None = None,
) -> dict:
    """`visuals`: paragraph_id → {"path": Path, "kind": "video"|"image"|"card"}.
    `takes`: paragraph_id → segundos de la narración de ese párrafo."""
    style = {**DEFAULT_STYLE, **(style or {})}
    w, h, fps, preset, crf = dimensions(quality, portrait)
    factor = QUALITIES[quality][5]
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("tmp-*"):  # restos de montajes anteriores interrumpidos
        _cleanup(old)
    # Carpeta temporal nueva en cada montaje: nunca choca con archivos de otro intento.
    workdir = Path(tempfile.mkdtemp(prefix=f"tmp-{quality}-", dir=folder))

    clips, lengths, seconds_list, segments, t = [], [], [], [], 0.0
    previous_last, reused = None, 0
    cache = folder / CACHE_DIR  # escenas ya montadas: solo se rehacen las que cambian
    cache.mkdir(exist_ok=True)
    used: set[str] = set()
    for i, scene in enumerate(scenes):
        pid = scene["paragraph_id"]
        seconds = takes[pid] + (PAUSE if i < len(scenes) - 1 else 0)
        length = seconds + (CROSSFADE if i < len(scenes) - 1 else 0)
        visual = visuals.get(pid)
        if style.get("callouts") and not scene.get("chart") and not scene.get("end_text"):
            found = find_callout(scene.get("narration", ""), takes[pid])
            if found and "callout" not in scene:
                scene = {**scene, "callout": found}
        motion = first_motion(pid, previous_last)
        clip = workdir / f"escena-{i:03}.mp4"
        puppet = bool(style.get("puppet"))
        # Con «muñeco» cambia la huella (se rehace); sin él, las escenas guardadas siguen valiendo.
        print_motion = [motion, "muñeco"] if puppet else motion
        key = scene_key(scene, visual, length, (w, h), fps, crf, factor, print_motion)
        cached = cache / f"{key}.mp4"
        used.add(cached.name)
        if cached.exists() and cached.stat().st_size > 0:
            progress(
                round(3 + 70 * i / len(scenes)), f"Escena {i + 1} de {len(scenes)}: sin cambios"
            )
            _link_or_copy(cached, clip)
            reused += 1
        else:
            progress(round(3 + 70 * i / len(scenes)), f"Montando escena {i + 1} de {len(scenes)}")
            _build_scene(
                scene, visual, i, length, clip, (w, h), fps, crf, factor, motion, workdir, puppet
            )
            _link_or_copy(clip, cached)
        previous_last = (motion + len(split_shots(length)) - 1) % len(MOTIONS)
        clips.append(clip)
        lengths.append(length)
        seconds_list.append(seconds)
        segments.append((spoken_text(scene["narration"]), t, t + takes[pid]))
        t += seconds

    progress(75, "Acabado final: fundidos, subtítulos, música y color (es lo más lento)")
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", clip.name]
    narration_index = len(clips)
    inputs += ["-i", str(narration.resolve())]
    video_chain, video_label = _xfade_chain(lengths, seconds_list)
    finish = []
    if style.get("film_look"):
        finish.append(LOOKS.get(style.get("look"), LOOKS["cine"])[1])
    if style.get("subtitles"):
        (workdir / "subtitulos.ass").write_text(build_ass(segments, w, h), encoding="utf-8")
        fonts = workdir / "fonts"
        fonts.mkdir()
        for f in FONTS_DIR.glob("*.ttf"):
            shutil.copy(f, fonts / f.name)
        finish.append("subtitles=subtitulos.ass:fontsdir=fonts")
    finish.append("format=yuv420p")
    graph = f"{video_chain};{video_label}{','.join(finish)}[vout]"

    if music and music.exists():
        inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
        volume = MUSIC_VOLUMES.get(style.get("music_volume"), MUSIC_VOLUMES["media"])
        m = narration_index + 1
        fade_out = max(t - 3, 0)
        graph += (
            f";[{narration_index}:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[voz][clave]"
            f";[{m}:a]aformat=sample_rates=44100:channel_layouts=stereo,atrim=duration={t:.3f},"
            f"volume={volume},afade=t=in:d=2,afade=t=out:st={fade_out:.3f}:d=3[musica]"
            f";[musica][clave]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[bajo]"
            f";[voz][bajo]amix=inputs=2:normalize=0:duration=first[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = f"{narration_index}:a"

    name = "video" if quality == "final" else f"video-{quality}"
    tmp_out = workdir / f"{name}.mp4"

    def join(codec: list[str]) -> None:
        run_ffmpeg(
            [*inputs, "-filter_complex", graph, "-map", "[vout]", "-map", audio_map, *codec,
             "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-t", f"{t:.3f}",
             "-movflags", "+faststart", tmp_out.name],
            cwd=workdir,
        )  # fmt: skip

    software = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
    if has_qsv():
        try:  # la gráfica Intel codifica más rápido; si falla, se hace como siempre
            join(["-c:v", "h264_qsv", "-global_quality", str(crf + 2), "-pix_fmt", "nv12"])
        except RuntimeError as exc:
            log.warning(
                "La gráfica Intel no pudo codificar el vídeo (%s): se usa el procesador", exc
            )
            join(software)
    else:
        join(software)
    out = replace_file(tmp_out, folder / f"{name}.mp4")
    tmp_srt = workdir / "subtitulos.srt"
    tmp_srt.write_text(build_srt(segments), encoding="utf-8")
    srt = replace_file(tmp_srt, folder / "subtitulos.srt")

    _cleanup(workdir)
    for stale in cache.glob("*.mp4"):  # escenas que ya no se usan (de versiones viejas)
        if stale.name not in used:
            stale.unlink(missing_ok=True)
    progress(100, "Vídeo listo")
    return {
        "reused_scenes": reused,
        "file": f"video/{out.name}",
        "srt": f"video/{srt.name}",
        "seconds": round(t, 2),
        "width": w,
        "height": h,
        "style": style,
        "music": music.name if music and music.exists() else "",
    }
