"""Comprobaciones con servicios reales (se ejecuta en GitHub Actions, que tiene internet).

- Todas las voces del catálogo existen en HuggingFace.
- Piper descarga una voz y graba audio de verdad.
- El actualizador descarga el repositorio público y lo reconoce.
"""

import sys
import tempfile
from pathlib import Path

import httpx
from piper.download_voices import URL_FORMAT, VOICE_PATTERN

from app import updater
from app.providers.voice import VOICES, PiperVoices, wav_seconds


def voice_url(voice: str, extension: str) -> str:
    m = VOICE_PATTERN.match(voice)
    family = m.group("lang_family")
    return URL_FORMAT.format(
        extension=extension,
        lang_family=family,
        lang_code=f"{family}_{m.group('lang_region')}",
        voice_name=m.group("voice_name"),
        voice_quality=m.group("voice_quality"),
    )


def main() -> None:
    failures = []

    print("1) Voces del catálogo")
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for voice in VOICES:
            status = client.head(voice_url(voice.id, ".onnx.json")).status_code
            print(f"   {voice.id}: {status}")
            if status != 200:
                failures.append(f"La voz {voice.id} no existe ({status})")

    print("2) Grabación real con Piper")
    with tempfile.TemporaryDirectory() as tmp:
        piper = PiperVoices(Path(tmp))
        for voice in ("es_ES-davefx-medium", "es_MX-ald-medium"):
            audio = piper.synthesize(
                "Hola, esta es una prueba de la voz de Faceless Studio.", voice, "Normal"
            )
            seconds = wav_seconds(audio)
            print(f"   {voice}: {seconds} s de audio")
            if seconds < 1:
                failures.append(f"Piper generó un audio demasiado corto con {voice}")

    print("3) Actualizador (repositorio público)")
    with tempfile.TemporaryDirectory() as tmp:
        source = updater.extract(updater.download(), Path(tmp))
        version = updater.read_version((source / "app" / "config.py").read_text("utf-8"))
        print(f"   Versión publicada: {version}")

    print("4) Montaje de vídeo real con FFmpeg")
    with tempfile.TemporaryDirectory(prefix="prueba d'apostrofo ") as tmp:
        folder = Path(tmp)
        from PIL import Image

        from app.pipeline.render import render_video
        from app.providers.voice import join_wavs

        Image.new("RGB", (640, 360), (90, 40, 30)).save(folder / "foto.jpg")
        voice = PiperVoices(folder / "voces")
        clips = [voice.synthesize(t, "es_ES-davefx-medium", "Normal") for t in ("Uno.", "Dos.")]
        (folder / "narracion.wav").write_bytes(join_wavs(clips))
        scenes = [
            {
                "number": 1,
                "paragraph_id": "a",
                "narration": "Uno.",
                "motion": "zoom lento",
                "transition": "fundido",
                "on_screen_text": "2001",
            },
            {
                "number": 2,
                "paragraph_id": "b",
                "narration": "Dos.",
                "motion": "",
                "transition": "corte",
                "on_screen_text": "63.000 MILLONES",
            },
        ]
        takes = {"a": wav_seconds(clips[0]), "b": wav_seconds(clips[1])}
        out = render_video(
            scenes,
            {"a": {"path": folder / "foto.jpg", "kind": "image"}},
            takes,
            folder / "narracion.wav",
            folder / "video",
            "preview",
            False,
            lambda p, m: None,
        )
        size = (folder / "video" / out["file"].removeprefix("video/")).stat().st_size
        print(f"   {out['file']}: {out['seconds']} s, {size} bytes")
        if size < 1000:
            failures.append("El vídeo montado está vacío")

    print("5) Imágenes con IA gratis (Pollinations, 3 seguidas con el ritmo del programa)")
    import time

    from app.providers.ai import ProviderError
    from app.providers.images import PollinationsImages

    pollinations = PollinationsImages()  # mismo ritmo que en el programa (sin clave)
    for n, prompt in enumerate(
        ["a quiet lighthouse at dusk", "an old empty office", "a city skyline at night"], 1
    ):
        start = time.monotonic()
        try:
            data, ext = pollinations.generate(prompt + ", cinematic", portrait=False, seed=n)
            print(f"   {n}: OK {ext} {len(data)} bytes ({time.monotonic() - start:.0f} s)")
        except ProviderError as exc:  # servicio externo gratuito: solo aviso
            print(f"   {n}: AVISO {exc} | {exc.detail}")

    if failures:
        print("\nFALLOS:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
