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


# ---------------------------------------------------------------- ElevenLabs

ELEVEN_PREFIX = "eleven:"
ELEVEN_API = "https://api.elevenlabs.io/v1"
ELEVEN_MODELS = {
    "eleven_multilingual_v2": "Máxima calidad (1 crédito por carácter)",
    "eleven_flash_v2_5": "Ahorro: buena calidad, la mitad de créditos",
}
ELEVEN_SPEEDS = {"Lenta": 0.9, "Normal": 1.0, "Rápida": 1.1}
ELEVEN_RATE = 22050  # formato PCM disponible en todos los planes


def is_eleven(voice: str) -> bool:
    return voice.startswith(ELEVEN_PREFIX)


def pcm_to_wav(pcm: bytes, rate: int = ELEVEN_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


class ElevenLabsVoices:
    """Voces de ElevenLabs con la cuenta del usuario (de pago por créditos)."""

    name = "elevenlabs"

    def __init__(self, api_key: str, model: str = "eleven_multilingual_v2", transport=None):
        import httpx

        self.model = model if model in ELEVEN_MODELS else "eleven_multilingual_v2"
        self._client = httpx.Client(
            base_url=ELEVEN_API,
            timeout=120,
            transport=transport,
            headers={"xi-api-key": api_key},
        )

    def _request(self, method: str, url: str, base: str | None = None, **kwargs):
        import httpx

        try:
            if base:  # rutas fuera de /v1 (p. ej. /v2/voices)
                response = self._client.request(method, base + url, **kwargs)
            else:
                response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(
                "No se pudo conectar con ElevenLabs. Revisa tu internet.",
                transient=True,
                detail=str(exc)[:200],
            ) from exc
        if response.status_code < 400:
            return response
        detail = response.text[:300]
        if response.status_code == 401 and "quota" not in detail:
            raise ProviderError(
                "La clave de ElevenLabs no es válida o no tiene permisos. Revísala en "
                "Configuración.",
                detail=detail,
            )
        if "quota" in detail or response.status_code == 402:
            raise ProviderError(
                "Se acabaron tus créditos de ElevenLabs de este mes. Usa una voz de Piper "
                "(gratis) o amplía tu plan.",
                detail=detail,
            )
        if response.status_code == 429:
            raise ProviderError(
                "ElevenLabs está ocupado. Se reintentará.", transient=True, detail=detail
            )
        if response.status_code >= 500:
            raise ProviderError("ElevenLabs falló temporalmente.", transient=True, detail=detail)
        raise ProviderError(
            f"ElevenLabs respondió con un error ({response.status_code}): "
            f"{_eleven_message(detail)}",
            detail=detail,
        )

    def list_voices(self) -> list[dict]:
        """Voces de la cuenta. Prueba primero la API nueva (/v2/voices) y, si no está
        disponible para esta clave, la antigua (/v1/voices)."""
        try:
            data = self._request(
                "GET", "/v2/voices", base="https://api.elevenlabs.io", params={"page_size": 100}
            ).json()
        except ProviderError as first:
            try:
                data = self._request("GET", "/voices").json()
            except ProviderError as second:
                if second.detail and first.detail and first.detail != second.detail:
                    second.detail = f"v2: {first.detail} | v1: {second.detail}"[:600]
                raise second from first
        voices = []
        for v in data.get("voices", []):
            labels = v.get("labels") or {}
            extra = " · ".join(x for x in (labels.get("gender"), labels.get("accent")) if x)
            voices.append(
                {
                    "id": ELEVEN_PREFIX + v["voice_id"],
                    "label": f"{v.get('name', 'Voz')}{f' ({extra})' if extra else ''}",
                }
            )
        return sorted(voices, key=lambda v: v["label"].lower())

    def credits(self) -> dict | None:
        """Caracteres usados y límite del mes. None si la clave no permite consultarlo."""
        try:
            data = self._request("GET", "/user/subscription").json()
        except ProviderError:
            return None
        used, limit = data.get("character_count"), data.get("character_limit")
        if used is None or limit is None:
            return None
        return {
            "used": used,
            "limit": limit,
            "left": max(limit - used, 0),
            "tier": data.get("tier", ""),
        }

    def cost(self, characters: int) -> int:
        """Créditos aproximados que gasta un texto con el modelo elegido."""
        return characters if self.model == "eleven_multilingual_v2" else (characters + 1) // 2

    def synthesize(self, text: str, voice: str, speed: str) -> bytes:
        voice_id = voice.removeprefix(ELEVEN_PREFIX)
        response = self._request(
            "POST",
            f"/text-to-speech/{voice_id}",
            params={"output_format": f"pcm_{ELEVEN_RATE}"},
            json={
                "text": text,
                "model_id": self.model,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "speed": ELEVEN_SPEEDS.get(speed, 1.0),
                },
            },
        )
        return pcm_to_wav(response.content)


def _eleven_message(detail: str) -> str:
    """Extrae el mensaje legible de una respuesta de error de ElevenLabs."""
    import json

    try:
        data = json.loads(detail)
    except ValueError:
        return detail[:160]
    info = data.get("detail", data) if isinstance(data, dict) else data
    if isinstance(info, dict):
        return str(info.get("message") or info.get("status") or info)[:160]
    if isinstance(info, list) and info:
        first = info[0]
        return str(first.get("msg") if isinstance(first, dict) else first)[:160]
    return str(info)[:160]
