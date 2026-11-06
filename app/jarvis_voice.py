"""La voz de JARVIS.

- «microsoft»: voces neuronales de Microsoft (las mismas de Edge), gratis y sin clave.
- «eleven»: una voz de tu cuenta de ElevenLabs (gasta créditos).
Encima se aplica el «efecto JARVIS»: voz un poco más grave, con cuerpo, un brillo
metálico muy suave y un eco corto, como un asistente que suena desde la sala.

Las frases se guardan en `datos/jarvis_voz/` para no volver a generarlas.
"""

import asyncio
import hashlib
import logging
import tempfile
from pathlib import Path

from app.config import DATA_DIR
from app.pipeline.render import run_ffmpeg
from app.providers.ai import ProviderError

log = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "jarvis_voz"
CACHE_LIMIT = 400  # frases guardadas como máximo
MAX_CHARS = 900

# Voces masculinas en español (todas gratis). Álvaro, de España, es la más «mayordomo».
MICROSOFT_VOICES = {
    "es-ES-AlvaroNeural": "Álvaro (España) — elegante, el más JARVIS",
    "es-MX-JorgeNeural": "Jorge (México) — cálido",
    "es-CO-GonzaloNeural": "Gonzalo (Colombia) — cercano",
    "es-US-AlonsoNeural": "Alonso (EE. UU.) — neutro",
    "es-AR-TomasNeural": "Tomás (Argentina)",
    "es-ES-ElviraNeural": "Elvira (España) — voz femenina, estilo FRIDAY",
}
DEFAULT_VOICE = "es-ES-AlvaroNeural"

# Efecto JARVIS (FFmpeg). Sutil a propósito: tiene que entenderse perfectamente.
EFFECTS = {
    "jarvis": ",".join(
        [
            # 5 % más grave sin cambiar el ritmo
            "aresample=24000,asetrate=24000*0.95,aresample=24000,atempo=1.0526",
            "highpass=f=70",
            "equalizer=f=140:t=q:w=1:g=3",  # cuerpo
            "equalizer=f=3200:t=q:w=1.2:g=2",  # claridad
            "chorus=0.85:0.85:18:0.25:0.3:1.8",  # brillo metálico suave
            "aecho=0.85:0.5:28|46:0.18|0.10",  # eco corto, como en una sala
            "acompressor=threshold=-18dB:ratio=3:attack=5:release=120",
            "volume=1.4",
            "alimiter=limit=0.95",
        ]
    ),
    "none": "anull",
}


def _cache_path(engine: str, voice: str, effect: str, text: str) -> Path:
    key = hashlib.sha1(f"{engine}|{voice}|{effect}|{text}".encode()).hexdigest()[:20]
    return CACHE_DIR / f"{key}.mp3"


def microsoft_tts(text: str, voice: str, out: Path) -> None:
    """Graba con las voces neuronales de Microsoft. Se reemplaza en los tests."""
    import edge_tts

    async def run() -> None:
        # Un pelín más pausado y grave: suena más sereno.
        await edge_tts.Communicate(text, voice, rate="-4%", pitch="-2Hz").save(str(out))

    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 — sin internet, servicio caído, voz inexistente…
        raise ProviderError(
            "No se pudo usar la voz de Microsoft (¿hay internet?).", detail=str(exc)[:300]
        ) from exc
    if not out.exists() or out.stat().st_size < 500:
        raise ProviderError("La voz de Microsoft no devolvió audio.")


def _apply_effect(source: Path, out: Path, effect: str) -> None:
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-af",
            EFFECTS.get(effect, EFFECTS["jarvis"]),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-b:a",
            "64k",
            str(out),
        ]
    )


def _trim_cache() -> None:
    files = sorted(CACHE_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for old in files[:-CACHE_LIMIT]:
        old.unlink(missing_ok=True)


def speak(
    text: str,
    engine: str = "microsoft",
    voice: str = DEFAULT_VOICE,
    effect: str = "jarvis",
    eleven=None,
) -> Path:
    """Devuelve un MP3 con la frase dicha por JARVIS (de la caché si ya existe).

    `eleven` es el proveedor de ElevenLabs ya creado (solo para engine="eleven")."""
    text = " ".join(text.split())[:MAX_CHARS]
    if not text:
        raise ProviderError("No hay nada que decir.")
    if effect not in EFFECTS:
        effect = "jarvis"
    if engine == "microsoft" and voice not in MICROSOFT_VOICES:
        voice = DEFAULT_VOICE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = _cache_path(engine, voice, effect, text)
    if target.exists():
        target.touch()
        return target
    with tempfile.TemporaryDirectory(dir=CACHE_DIR) as tmp:
        raw = Path(tmp) / "voz.mp3"
        if engine == "eleven":
            if eleven is None:
                raise ProviderError("Falta la clave de ElevenLabs. Añádela en Configuración.")
            wav = Path(tmp) / "voz.wav"
            wav.write_bytes(eleven.synthesize(text, voice, "Normal"))
            raw = wav
        else:
            microsoft_tts(text, voice, raw)
        try:
            _apply_effect(raw, Path(tmp) / "final.mp3", effect)
        except RuntimeError as exc:
            raise ProviderError("No se pudo aplicar el efecto de voz.", detail=str(exc)) from exc
        (Path(tmp) / "final.mp3").replace(target)
    _trim_cache()
    return target


def to_voice_note(mp3: Path) -> Path:
    """La misma frase en OGG/Opus, el formato de las notas de voz de Telegram."""
    out = mp3.with_suffix(".ogg")
    if not out.exists():
        run_ffmpeg(["-i", str(mp3), "-c:a", "libopus", "-b:a", "32k", str(out)])
    return out


# ---------------------------------------------------------------- preferencias


def preferences(db) -> dict:
    """Motor, voz y efecto elegidos (los usan la pantalla JARVIS y Telegram)."""
    import json

    from app.settings_store import get_setting

    prefs = {"engine": "microsoft", "voice": DEFAULT_VOICE, "effect": "jarvis", "telegram": True}
    raw = get_setting(db, "jarvis_voice")
    if raw:
        try:
            prefs.update(json.loads(raw))
        except ValueError:
            pass
    return prefs


def save_preferences(db, prefs: dict) -> None:
    import json

    from app.settings_store import set_setting

    set_setting(db, "jarvis_voice", json.dumps(prefs))


def spoken_text(html: str) -> str:
    """De un mensaje con formato a texto para decir en voz alta (sin emojis ni etiquetas)."""
    import re
    from html import unescape

    text = unescape(re.sub(r"<[^>]+>", "", html))
    text = re.sub("[\U0001f000-\U0001faff☀-➿⬀-⯿️⃣]", "", text)
    return " ".join(text.replace("«", "").replace("»", "").split())


def voice_for(db, text: str) -> Path:
    """La frase con la voz y el efecto elegidos."""
    prefs = preferences(db)
    eleven = None
    if prefs["engine"] == "eleven" and not prefs["voice"].startswith("eleven:"):
        prefs.update(engine="microsoft", voice=DEFAULT_VOICE)
    if prefs["engine"] == "eleven":
        from app import jobs

        eleven = jobs.get_voice_provider(db, prefs["voice"])
    return speak(text, prefs["engine"], prefs["voice"], prefs["effect"], eleven)
