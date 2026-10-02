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

    if failures:
        print("\nFALLOS:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
