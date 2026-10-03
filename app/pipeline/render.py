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

import math
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
CROSSFADE = 0.4  # fundido entre escenas (segundos)

QUALITIES = {
    # nombre: (ancho, alto, fps, preset de x264, crf, factor de zoom suave) en horizontal
    "preview": (1280, 720, 30, "veryfast", 24, 2),
    "final": (1920, 1080, 30, "veryfast", 20, 3),
    "test": (192, 108, 12, "ultrafast", 35, 1),
}

FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
TITLE_FONT = FONTS_DIR / "BebasNeue-Regular.ttf"
CAPTION_FONT = FONTS_DIR / "Montserrat-ExtraBold.ttf"
CAPTION_FONT_NAME = "Montserrat ExtraBold"

# Colores de la marca
WHITE = (238, 238, 242)
RED = (230, 57, 70)
DARK = (13, 14, 18)

DEFAULT_STYLE = {
    "subtitles": True,
    "film_look": True,
    "look": "auto",
    "music": "",
    "music_volume": "media",
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

# Movimientos de cámara que se van alternando dentro de una escena.
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


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
        [w / 2 - bar, y + h * 0.02, w / 2 + bar, y + h * 0.02 + max(h // 160, 2)], fill=RED
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
        [x0, y0 + box_h, x0 + tw + pad * 2, y0 + box_h + max(h // 120, 2)], fill=RED + (255,)
    )
    draw.text((x0 + pad, y0 + pad * 0.7), label, font=fnt, fill=WHITE + (255,))
    image.save(path)
    return path


# ---------------------------------------------------------------- planos y clips


def split_shots(seconds: float) -> list[float]:
    """Divide una escena en planos de 3–6 s (máximo 4) para que la imagen cambie a menudo."""
    if seconds <= 6:
        return [seconds]
    count = min(max(math.ceil(seconds / 5), 2), 4)
    return [seconds / count] * count


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
    return f"1+0.15*{ease}", center_x, center_y  # zoom_in


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
    factor: int = 1,
    first_motion: int = 0,
) -> None:
    """Clip de una escena. Las fotos se dividen en planos con movimientos distintos."""
    w, h = size
    inputs: list[str] = []
    if kind == "video":
        inputs += ["-stream_loop", "-1", "-i", str(visual_path)]
        chain = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1,trim=duration={seconds:.3f}[v0]"
        )
    else:
        inputs += ["-i", str(visual_path)]
        shots = split_shots(seconds)
        bw, bh = w * factor // 2 * 2, h * factor // 2 * 2
        parts = [
            f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"setsar=1,split={len(shots)}" + "".join(f"[i{k}]" for k in range(len(shots)))
        ]
        for k, shot in enumerate(shots):
            frames = max(int(round(shot * fps)), 1)
            z, x, y = _motion_filter(MOTIONS[(first_motion + k) % len(MOTIONS)], frames)
            parts.append(
                f"[i{k}]zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}[s{k}]"
            )
        parts.append(
            "".join(f"[s{k}]" for k in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[v0]"
        )
        chain = ";".join(parts)
    last = "[v0]"
    if scene.get("on_screen_text"):
        overlay = text_overlay(
            scene["on_screen_text"], size, workdir / f"texto-{scene['number']}.png"
        )
        inputs += ["-loop", "1", "-i", str(overlay)]
        # En los Shorts el gancho sale desde el primer fotograma (sirve de portada).
        fade = "st=0:d=0.04" if scene.get("text_from_start") else "st=0.3:d=0.4"
        chain += f";[1:v]format=rgba,fade=t=in:{fade}:alpha=1[o];[v0][o]overlay=0:0:shortest=1[v1]"
        last = "[v1]"
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
    red = "&H004639E6&"  # RGB(230,57,70) en formato BGR de ASS
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
        parts.append(
            f"{previous}[{k}:v]xfade=transition=fade:duration={CROSSFADE}:offset={offset:.3f}{label}"
        )
        previous = label
    return ";".join(parts), previous


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
    motion = 0
    for i, scene in enumerate(scenes):
        pid = scene["paragraph_id"]
        seconds = takes[pid] + (PAUSE if i < len(scenes) - 1 else 0)
        length = seconds + (CROSSFADE if i < len(scenes) - 1 else 0)
        progress(round(3 + 70 * i / len(scenes)), f"Montando escena {i + 1} de {len(scenes)}")
        visual = visuals.get(pid)
        if visual is None or visual["kind"] == "card":
            text = scene.get("on_screen_text") or scene.get("visual") or ""
            path = text_card(
                text, (w * factor, h * factor), workdir / f"tarjeta-{scene['number']}.png"
            )
            kind = "image"
            scene = {**scene, "on_screen_text": ""}  # el texto ya va en la tarjeta
        else:
            path, kind = Path(visual["path"]), visual["kind"]
        if scene.get("chart"):  # gráfico animado con las cifras de esta escena
            from app.pipeline.charts import chart_clip

            background = path if kind == "image" and visual and visual["kind"] != "card" else None
            path = chart_clip(
                scene["chart"], workdir / f"grafico-{i:03}.mp4", (w, h), fps, length, background
            )
            kind = "video"
            scene = {**scene, "on_screen_text": ""}  # el gráfico ya lleva su título
        clip = workdir / f"escena-{i:03}.mp4"
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
        )
        motion += len(split_shots(length))
        clips.append(clip)
        lengths.append(length)
        seconds_list.append(seconds)
        segments.append((scene["narration"], t, t + takes[pid]))
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
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            audio_map,
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{t:.3f}",
            "-movflags",
            "+faststart",
            tmp_out.name,
        ],
        cwd=workdir,
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
        "style": style,
        "music": music.name if music and music.exists() else "",
    }
