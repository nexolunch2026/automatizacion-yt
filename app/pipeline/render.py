"""VIDEO EDITING ENGINE: monta el vídeo con FFmpeg a partir de escenas, visuales y voz.

Cada escena dura exactamente lo que dura su narración (más la pausa entre párrafos), así
la imagen y la voz siempre van sincronizadas.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PAUSE = 0.35  # la misma pausa que se deja entre párrafos al grabar la voz

QUALITIES = {
    # nombre: (ancho, alto, fps, preset de x264, crf) en horizontal
    "preview": (854, 480, 24, "ultrafast", 30),
    "final": (1920, 1080, 30, "veryfast", 21),
    "test": (192, 108, 12, "ultrafast", 35),
}

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        creationflags=flags,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg falló: {result.stderr.strip()[-500:]}")


def font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def dimensions(quality: str, portrait: bool) -> tuple[int, int, int, str, int]:
    w, h, fps, preset, crf = QUALITIES[quality]
    return (h, w, fps, preset, crf) if portrait else (w, h, fps, preset, crf)


# ---------------------------------------------------------------- imágenes con texto


def text_card(text: str, size: tuple[int, int], path: Path) -> Path:
    """Tarjeta de fondo oscuro con un texto grande (para gráficos o cuando no hay imagen)."""
    w, h = size
    image = Image.new("RGB", size, (12, 14, 20))
    draw = ImageDraw.Draw(image)
    for y in range(h):  # degradado suave
        shade = int(12 + 18 * y / h)
        draw.line([(0, y), (w, y)], fill=(shade, shade + 2, shade + 10))
    fnt = font(max(int(h * 0.075), 10))
    lines = textwrap.wrap(text, width=max(int(w / (h * 0.045)), 10))[:5]
    line_h = int(h * 0.1)
    y = (h - line_h * len(lines)) // 2
    for line in lines:
        tw = draw.textlength(line, font=fnt)
        draw.text(((w - tw) / 2, y), line, font=fnt, fill=(240, 240, 245))
        y += line_h
    image.save(path)
    return path


def text_overlay(text: str, size: tuple[int, int], path: Path) -> Path:
    """PNG transparente con el texto en pantalla en el tercio inferior."""
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fnt = font(max(int(h * 0.07), 10))
    tw = draw.textlength(text, font=fnt)
    pad = int(h * 0.025)
    box_h = int(h * 0.07) + pad * 2
    x0 = (w - tw) / 2 - pad
    y0 = h * 0.78
    draw.rounded_rectangle(
        [x0, y0, x0 + tw + pad * 2, y0 + box_h], radius=pad, fill=(10, 10, 14, 200)
    )
    draw.text((x0 + pad, y0 + pad * 0.6), text, font=fnt, fill=(255, 255, 255, 255))
    image.save(path)
    return path


# ---------------------------------------------------------------- clips por escena


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
) -> None:
    w, h = size
    frames = max(int(round(seconds * fps)), 1)
    fade = "fund" in (scene.get("transition") or "").lower()
    inputs = []
    if kind == "video":
        inputs += ["-stream_loop", "-1", "-i", str(visual_path)]
        base = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1"
        )
    else:
        inputs += ["-loop", "1", "-i", str(visual_path)]
        bw, bh = int(w * 1.15) // 2 * 2, int(h * 1.15) // 2 * 2
        pan = "paneo" in (scene.get("motion") or "").lower()
        x = f"(iw-iw/zoom)*on/{frames}" if pan else "iw/2-(iw/zoom/2)"
        zoom = "1.1" if pan else f"min(1+0.12*on/{frames},1.12)"
        base = (
            f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps},setsar=1"
        )
    chain = base
    if fade:
        chain += f",fade=t=in:st=0:d={min(0.3, seconds / 3):.2f}"
    filters = chain + "[v0]"
    last = "[v0]"
    if scene.get("on_screen_text"):
        overlay = text_overlay(
            scene["on_screen_text"], size, workdir / f"texto-{scene['number']}.png"
        )
        inputs += ["-loop", "1", "-i", str(overlay)]
        filters += ";[v0][1:v]overlay=0:0:shortest=1[v1]"
        last = "[v1]"
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            filters,
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


def build_srt(segments: list[tuple[str, float, float]], max_words: int = 10) -> str:
    """Subtítulos a partir de (texto, inicio, fin) de cada párrafo, en trozos cortos
    repartidos según el número de palabras."""
    entries, n = [], 1
    for text, start, end in segments:
        words = text.split()
        if not words:
            continue
        chunks = [words[i : i + max_words] for i in range(0, len(words), max_words)]
        per_word = (end - start) / len(words)
        t = start
        for chunk in chunks:
            t_end = t + per_word * len(chunk)
            entries.append(f"{n}\n{_timestamp(t)} --> {_timestamp(t_end)}\n{' '.join(chunk)}\n")
            n += 1
            t = t_end
    return "\n".join(entries)


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


def render_video(
    scenes: list[dict],
    visuals: dict,
    takes: dict,
    narration: Path,
    folder: Path,
    quality: str,
    portrait: bool,
    progress: Callable[[int, str], None],
) -> dict:
    """`visuals`: paragraph_id → {"path": Path, "kind": "video"|"image"|"card"}.
    `takes`: paragraph_id → segundos de la narración de ese párrafo."""
    w, h, fps, preset, crf = dimensions(quality, portrait)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("tmp-*"):  # restos de montajes anteriores interrumpidos
        _cleanup(old)
    # Carpeta temporal nueva en cada montaje: nunca choca con archivos de otro intento.
    workdir = Path(tempfile.mkdtemp(prefix=f"tmp-{quality}-", dir=folder))

    clips, segments, t = [], [], 0.0
    for i, scene in enumerate(scenes):
        pid = scene["paragraph_id"]
        seconds = takes[pid] + (PAUSE if i < len(scenes) - 1 else 0)
        progress(round(5 + 80 * i / len(scenes)), f"Montando escena {i + 1} de {len(scenes)}")
        visual = visuals.get(pid)
        if visual is None or visual["kind"] == "card":
            text = scene.get("on_screen_text") or scene.get("visual") or ""
            path = text_card(text, (w, h), workdir / f"tarjeta-{scene['number']}.png")
            kind = "image"
            scene = {**scene, "on_screen_text": ""}  # el texto ya va en la tarjeta
        else:
            path, kind = Path(visual["path"]), visual["kind"]
        clip = workdir / f"escena-{i:03}.mp4"
        scene_clip(scene, path, kind, seconds, clip, (w, h), fps, preset, crf, workdir)
        clips.append(clip)
        segments.append((scene["narration"], t, t + takes[pid]))
        t += seconds

    progress(88, "Uniendo escenas y voz")
    concat = workdir / "lista.txt"
    concat.write_text("".join(f"file '{_concat_escape(c)}'\n" for c in clips), encoding="utf-8")
    name = "video" if quality == "final" else f"video-{quality}"
    tmp_out = workdir / f"{name}.mp4"
    run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(narration),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(tmp_out),
        ]
    )
    out = replace_file(tmp_out, folder / f"{name}.mp4")
    tmp_srt = workdir / "subtitulos.srt"
    tmp_srt.write_text(build_srt(segments), encoding="utf-8")
    srt = replace_file(tmp_srt, folder / "subtitulos.srt")

    _cleanup(workdir)
    progress(100, "Vídeo listo")
    return {
        "file": f"video/{out.name}",
        "srt": f"video/{srt.name}",
        "seconds": round(t, 2),
        "width": w,
        "height": h,
    }
