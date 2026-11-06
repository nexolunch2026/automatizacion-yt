"""Voces (texto a voz).

- Microsoft: voces neuronales de Microsoft (las de Edge), gratis, sin clave y sin límite.
  Es la voz de todos los vídeos; por defecto, Jorge (México).
- ElevenLabs: voces de la cuenta del usuario (de pago por créditos), opcional.
"""

import asyncio
import io
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.providers.ai import ProviderError


@dataclass(frozen=True)
class VoiceOption:
    id: str
    label: str
    language: str


# Voces de Microsoft (https://github.com/rany2/edge-tts). Jorge es la que eligió el creador.
VOICES = [
    VoiceOption("es-MX-JorgeNeural", "Jorge (México) · documental", "Español"),
    VoiceOption("es-CO-GonzaloNeural", "Gonzalo (Colombia)", "Español"),
    VoiceOption("es-ES-AlvaroNeural", "Álvaro (España)", "Español"),
    VoiceOption("es-AR-TomasNeural", "Tomás (Argentina)", "Español"),
    VoiceOption("es-US-AlonsoNeural", "Alonso (latino neutro)", "Español"),
    VoiceOption("en-US-GuyNeural", "Guy (EE. UU.)", "Inglés"),
    VoiceOption("en-US-ChristopherNeural", "Christopher (EE. UU.)", "Inglés"),
    VoiceOption("en-GB-RyanNeural", "Ryan (Reino Unido)", "Inglés"),
]
VOICE_IDS = {v.id for v in VOICES}
# Ritmo de documental: un poco más pausado y grave que la voz normal.
SPEEDS = {"Lenta": "-14%", "Normal": "-6%", "Rápida": "+4%"}
PITCH = "-4Hz"
RATE = 24000


def default_voice(language: str) -> str:
    return next((v.id for v in VOICES if v.language == language), VOICES[0].id)


def known_voice(voice: str | None, language: str) -> str:
    """La voz si existe; si no (p. ej. una voz Piper de versiones antiguas), la de por defecto."""
    if voice and (voice in VOICE_IDS or is_eleven(voice)):
        return voice
    return default_voice(language)


CITATION = re.compile(r"\s*\[\d+(?:\s*[,–-]\s*\d+)*\]")


def spoken_text(text: str) -> str:
    """El texto tal como se dice y se subtitula: sin las marcas de fuentes «[1]» del guion."""
    return " ".join(CITATION.sub("", text).split())


# «10.000» con punto de miles: la voz lo lee como decimal («diez punto cero cero»).
THOUSANDS = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?![\d]|[.,]\d)")


def _plain_number(match: re.Match) -> str:
    n = int(match.group().replace(".", ""))
    if n % 1000 == 0 and n < 1_000_000:
        return f"{n // 1000} mil"  # «10 mil millones»: se lee siempre bien
    return str(n)


def say_numbers(text: str) -> str:
    """Lo que de verdad se le pasa a la voz: cifras con punto de miles sin el punto."""
    return THOUSANDS.sub(_plain_number, text)


class VoiceProvider(Protocol):
    name: str

    def synthesize(self, text: str, voice: str, speed: str) -> bytes:
        """Devuelve un WAV (mono, 16 bits)."""


def edge_mp3(text: str, voice: str, rate: str, out: Path) -> None:
    """Graba un MP3 con la voz de Microsoft. Se reemplaza en los tests (no usan internet)."""
    import edge_tts

    async def run() -> None:
        await edge_tts.Communicate(text, voice, rate=rate, pitch=PITCH).save(str(out))

    asyncio.run(run())


def mp3_to_wav(mp3: Path, wav: Path) -> None:
    """MP3 -> WAV mono de 16 bits, sin el silencio del principio y del final."""
    from app.pipeline.render import ffmpeg_exe

    trim = "silenceremove=start_periods=1:start_threshold=-50dB"
    result = subprocess.run(
        [
            ffmpeg_exe(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(mp3),
            "-af",
            f"{trim},areverse,{trim},areverse",
            "-ar",
            str(RATE),
            "-ac",
            "1",
            "-sample_fmt",
            "s16",
            str(wav),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode or not wav.exists():
        raise ProviderError("No se pudo preparar el audio de la voz.", detail=result.stderr[-300:])


class MicrosoftVoices:
    """Voces neuronales de Microsoft: gratis, sin clave, necesitan internet."""

    name = "microsoft"

    def synthesize(self, text: str, voice: str, speed: str) -> bytes:
        if voice not in VOICE_IDS:
            voice = VOICES[0].id
        last: Exception | None = None
        with tempfile.TemporaryDirectory() as tmp:
            mp3, wav = Path(tmp) / "voz.mp3", Path(tmp) / "voz.wav"
            for _ in range(3):  # el servicio a veces corta una petición: se reintenta
                try:
                    edge_mp3(text, voice, SPEEDS.get(speed, SPEEDS["Normal"]), mp3)
                    if mp3.exists() and mp3.stat().st_size > 500:
                        break
                except Exception as exc:  # noqa: BLE001 — sin internet, servicio caído…
                    last = exc
            else:
                raise ProviderError(
                    "No se pudo usar la voz de Microsoft. Revisa tu internet; si sigue "
                    "fallando, pulsa Actualizar (puede que Microsoft haya cambiado algo).",
                    transient=True,
                    detail=repr(last)[:300] if last else "audio vacío",
                )
            mp3_to_wav(mp3, wav)
            return wav.read_bytes()


# ---------------------------------------------------------------- utilidades WAV


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as wav:
        return round(wav.getnframes() / wav.getframerate(), 2)


def tighten(
    data: bytes, keep: float = 0.08, max_pause: float = 0.45, threshold: float = 0.02
) -> bytes:
    """Quita el silencio del principio y del final de una toma y acorta las pausas largas
    entre frases (las guías de retención piden quitar las de más de medio segundo).
    Solo audio de 16 bits; con cualquier otro formato devuelve la toma tal cual."""
    import array

    try:
        with wave.open(io.BytesIO(data)) as reader:
            params = reader.getparams()
            frames = reader.readframes(reader.getnframes())
    except (wave.Error, EOFError):
        return data
    if params.sampwidth != 2 or not frames:
        return data
    samples = array.array("h", frames)
    channels, rate = params.nchannels, params.framerate
    window = max(int(rate * 0.01), 1) * channels  # trozos de 10 ms
    limit = max(int(32767 * threshold), 1)
    loud = []
    for i in range(0, len(samples), window):
        chunk = samples[i : i + window]  # max/min de un trozo van a velocidad de C
        loud.append(max(chunk) >= limit or -min(chunk) >= limit)
    if not any(loud):
        return data
    first = loud.index(True)
    last = len(loud) - 1 - loud[::-1].index(True)
    margin, longest = round(keep / 0.01), round(max_pause / 0.01)
    keep_windows: list[int] = list(range(max(first - margin, 0), first))
    quiet: list[int] = []
    for w in range(first, last + 1):
        if loud[w]:
            keep_windows += quiet[:longest] if len(quiet) > longest else quiet
            quiet = []
            keep_windows.append(w)
        else:
            quiet.append(w)
    keep_windows += list(range(last + 1, min(last + 1 + margin, len(loud))))
    out_samples = array.array("h")
    for w in keep_windows:
        out_samples.extend(samples[w * window : (w + 1) * window])
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(out_samples.tobytes())
    return out.getvalue()


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
# Nombre del permiso tal como aparece en la pantalla de claves de ElevenLabs.
PERMISSION_NAMES = {
    "voices_read": "Voices → Read (leer voces)",
    "text_to_speech": "Text to Speech (texto a voz)",
    "user_read": "User → Read (leer usuario)",
}


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
        if "missing_permissions" in detail:
            import re

            match = re.search(r"permission (\w+)", detail)
            permission = PERMISSION_NAMES.get(match.group(1), match.group(1)) if match else ""
            raise ProviderError(
                "A tu clave de ElevenLabs le falta un permiso"
                + (f": «{permission}»" if permission else "")
                + ". Edita la clave en ElevenLabs (Settings → API Keys) y actívalo.",
                detail=detail,
            )
        if response.status_code == 401 and "quota" not in detail:
            raise ProviderError(
                "La clave de ElevenLabs no es válida o no tiene permisos. Revísala en "
                "Configuración.",
                detail=detail,
            )
        if "quota" in detail or response.status_code == 402:
            raise ProviderError(
                "Se acabaron tus créditos de ElevenLabs de este mes. Usa la voz gratis de "
                "Microsoft (Jorge) o amplía tu plan.",
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
