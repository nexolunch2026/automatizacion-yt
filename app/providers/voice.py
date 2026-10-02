"""Voces (texto a voz). Hoy: Piper, que funciona en el propio ordenador, gratis y sin internet
(solo descarga la voz la primera vez)."""

import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import DATA_DIR
from app.providers.ai import ProviderError

VOICES_DIR = DATA_DIR / "voces"


@dataclass(frozen=True)
class VoiceOption:
    id: str
    label: str
    language: str


# Voces de Piper (https://github.com/rhasspy/piper). Cada una tiene su propia licencia,
# indicada en su ficha (MODEL_CARD) en HuggingFace.
VOICES = [
    VoiceOption("es_ES-davefx-medium", "España · davefx", "Español"),
    VoiceOption("es_ES-sharvard-medium", "España · sharvard", "Español"),
    VoiceOption("es_MX-ald-medium", "México · ald", "Español"),
    VoiceOption("es_MX-claude-high", "México · claude (alta calidad)", "Español"),
    VoiceOption("en_US-lessac-medium", "EE. UU. · lessac", "Inglés"),
    VoiceOption("en_US-ryan-high", "EE. UU. · ryan (alta calidad)", "Inglés"),
    VoiceOption("en_GB-alan-medium", "Reino Unido · alan", "Inglés"),
]
VOICE_IDS = {v.id for v in VOICES}
SPEEDS = {"Lenta": 1.15, "Normal": 1.0, "Rápida": 0.88}


def default_voice(language: str) -> str:
    return next(v.id for v in VOICES if v.language == language) if language else VOICES[0].id


class VoiceProvider(Protocol):
    name: str

    def synthesize(self, text: str, voice: str, speed: str) -> bytes:
        """Devuelve un WAV (mono, 16 bits)."""


class PiperVoices:
    name = "piper"

    def __init__(self, voices_dir: Path = VOICES_DIR):
        self.voices_dir = voices_dir
        self._loaded: dict[str, object] = {}

    def _model_path(self, voice: str) -> Path:
        return self.voices_dir / f"{voice}.onnx"

    def is_downloaded(self, voice: str) -> bool:
        model = self._model_path(voice)
        return model.exists() and Path(f"{model}.json").exists()

    def ensure_downloaded(self, voice: str, transport=None) -> None:
        """Descarga el modelo y su configuración. Cada archivo se guarda primero como
        «.part» y solo se renombra al terminar, para no dejar voces a medias."""
        if self.is_downloaded(voice):
            return
        import httpx
        from piper.download_voices import URL_FORMAT, VOICE_PATTERN

        match = VOICE_PATTERN.match(voice)
        if not match:
            raise ProviderError(f"Voz desconocida: {voice}")
        family = match.group("lang_family")
        args = {
            "lang_family": family,
            "lang_code": f"{family}_{match.group('lang_region')}",
            "voice_name": match.group("voice_name"),
            "voice_quality": match.group("voice_quality"),
        }
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(transport=transport, timeout=120, follow_redirects=True) as client:
                for extension in (".onnx.json", ".onnx"):
                    target = self.voices_dir / f"{voice}{extension}"
                    partial = Path(f"{target}.part")
                    with client.stream("GET", URL_FORMAT.format(extension=extension, **args)) as r:
                        r.raise_for_status()
                        with open(partial, "wb") as f:
                            for chunk in r.iter_bytes():
                                f.write(chunk)
                    partial.replace(target)
        except (httpx.HTTPError, OSError) as exc:
            for leftover in self.voices_dir.glob(f"{voice}.onnx*.part"):
                leftover.unlink(missing_ok=True)
            raise ProviderError(
                "No se pudo descargar la voz. Revisa tu internet o prueba con otra voz.",
                transient=True,
                detail=repr(exc)[:300],
            ) from exc

    def _voice(self, voice: str):
        if voice not in self._loaded:
            from piper import PiperVoice

            self.ensure_downloaded(voice)
            self._loaded[voice] = PiperVoice.load(self._model_path(voice))
        return self._loaded[voice]

    def synthesize(self, text: str, voice: str, speed: str) -> bytes:
        from piper import SynthesisConfig

        piper_voice = self._voice(voice)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            piper_voice.synthesize_wav(
                text, wav, syn_config=SynthesisConfig(length_scale=SPEEDS.get(speed, 1.0))
            )
        return buffer.getvalue()


# ---------------------------------------------------------------- utilidades WAV


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as wav:
        return round(wav.getnframes() / wav.getframerate(), 2)


def join_wavs(parts: list[bytes], pause_seconds: float = 0.35) -> bytes:
    """Une varios WAV con el mismo formato, con una pausa breve entre ellos."""
    if not parts:
        raise ValueError("No hay audio que unir")
    out = io.BytesIO()
    with wave.open(io.BytesIO(parts[0])) as first:
        params = first.getparams()
    silence = b"\x00" * int(params.framerate * pause_seconds) * params.sampwidth * params.nchannels
    with wave.open(out, "wb") as writer:
        writer.setparams(params)
        for i, part in enumerate(parts):
            with wave.open(io.BytesIO(part)) as reader:
                if (reader.getframerate(), reader.getsampwidth(), reader.getnchannels()) != (
                    params.framerate,
                    params.sampwidth,
                    params.nchannels,
                ):
                    raise ValueError("Los audios tienen formatos distintos")
                writer.writeframes(reader.readframes(reader.getnframes()))
            if i < len(parts) - 1:
                writer.writeframes(silence)
    return out.getvalue()
