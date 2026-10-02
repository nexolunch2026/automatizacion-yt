"""VOICE ENGINE: graba la narración párrafo a párrafo.

Cada párrafo se guarda en su propio archivo, con el texto y la voz con que se grabó.
Si luego cambias un párrafo, solo se vuelve a grabar ese.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

from app.models import Project
from app.pipeline.storyboard import paragraphs_of
from app.providers.voice import VoiceProvider, join_wavs, wav_seconds


def take_key(text: str, voice: str, speed: str) -> str:
    return hashlib.sha1(f"{voice}|{speed}|{text}".encode()).hexdigest()[:12]


def run_voice(
    project: Project,
    script: dict,
    previous: dict | None,
    tts: VoiceProvider,
    params: dict,
    folder: Path,
    progress: Callable[[int, str], None],
) -> dict:
    voice, speed = params["voice"], params["speed"]
    folder.mkdir(parents=True, exist_ok=True)
    old_takes = {t["paragraph_id"]: t for t in (previous or {}).get("takes", [])}
    paragraphs = paragraphs_of(script)
    if not paragraphs:
        raise ValueError("El guion está vacío")

    takes, audio_parts, reused = [], [], 0
    for i, paragraph in enumerate(paragraphs, 1):
        key = take_key(paragraph["text"], voice, speed)
        filename = f"{paragraph['id']}-{key}.wav"
        path = folder / filename
        old = old_takes.get(paragraph["id"])
        if old and old["key"] == key and path.exists():
            data = path.read_bytes()
            reused += 1
        else:
            progress(
                round(5 + 85 * (i - 1) / len(paragraphs)),
                f"Grabando párrafo {i} de {len(paragraphs)}",
            )
            data = tts.synthesize(paragraph["text"], voice, speed)
            path.write_bytes(data)
        takes.append(
            {
                "paragraph_id": paragraph["id"],
                "key": key,
                "file": f"voz/{filename}",
                "seconds": wav_seconds(data),
            }
        )
        audio_parts.append(data)

    progress(92, "Uniendo la narración completa")
    full = join_wavs(audio_parts)
    (folder / "narracion.wav").write_bytes(full)

    # Borra grabaciones viejas que ya no se usan.
    in_use = {Path(t["file"]).name for t in takes} | {"narracion.wav"}
    for leftover in folder.glob("*.wav"):
        if leftover.name not in in_use:
            leftover.unlink(missing_ok=True)

    progress(100, "Narración lista")
    return {
        "voice": voice,
        "speed": speed,
        "provider": tts.name,
        "takes": takes,
        "full": "voz/narracion.wav",
        "seconds": wav_seconds(full),
        "reused": reused,
    }
