"""REVISAR MI ORDENADOR: comprobar en un minuto que todo lo que usa el programa funciona.

Cada comprobación dice si está bien (✅), si conviene mirarlo (⚠️) o si falla (❌), y qué
hacer en palabras sencillas. Nace del día en que la voz gratuita cerraba el programa por
una carpeta con tilde: mejor verlo aquí que con el programa cerrándose.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, ROOT, VERSION

OK, WARN, FAIL = "ok", "warn", "fail"
GB = 1024**3


@dataclass
class Check:
    name: str
    state: str
    detail: str
    fix: str = ""


def folders(root: Path = ROOT, data: Path = DATA_DIR) -> Check:
    places = f"Programa: {root} · Datos: {data}"
    if "onedrive" in f"{root} {data}".lower():
        return Check(
            "Carpetas",
            WARN,
            places,
            "Están dentro de OneDrive: puede llenarse con los vídeos y bloquear archivos. "
            "Mejor instalar el programa fuera de OneDrive.",
        )
    return Check("Carpetas", OK, places)


def disk(data: Path = DATA_DIR, usage=shutil.disk_usage) -> Check:
    free = usage(data).free / GB
    text = f"{free:.1f} GB libres"
    if free < 2:
        return Check("Espacio en disco", FAIL, text, "Libera espacio: cada vídeo ocupa 1–3 GB.")
    if free < 10:
        return Check(
            "Espacio en disco", WARN, text, "Queda poco: borra proyectos viejos que ya subiste."
        )
    return Check("Espacio en disco", OK, text)


def video_tools(run=subprocess.run) -> Check:
    try:
        from app.pipeline.render import ffmpeg_exe

        done = run([ffmpeg_exe(), "-version"], capture_output=True, timeout=30, check=False)
        ok = done.returncode == 0
    except (OSError, RuntimeError, subprocess.SubprocessError):
        ok = False
    if ok:
        return Check("Montaje de vídeo (ffmpeg)", OK, "Listo para montar vídeos")
    return Check(
        "Montaje de vídeo (ffmpeg)",
        FAIL,
        "No arranca",
        "Pulsa Actualizar; si sigue igual, avisa a Claude.",
    )


def free_voice() -> Check:
    from app.providers import piper_safe
    from app.providers.ai import ProviderError

    try:
        from piper.phonemize_espeak import ESPEAK_DATA_DIR
    except ImportError:
        return Check("Voz gratuita (Piper)", FAIL, "No está instalada", "Pulsa Actualizar.")
    folder = piper_safe.data_dir(ESPEAK_DATA_DIR)
    try:
        piper_safe.check(folder)
    except ProviderError:
        return Check(
            "Voz gratuita (Piper)",
            FAIL,
            "La pronunciación (espeak-ng) no arranca en este ordenador",
            "Actualiza el programa. Mientras tanto usa una voz de ElevenLabs.",
        )
    return Check("Voz gratuita (Piper)", OK, "Funciona")


def keys(db: Session) -> list[Check]:
    from app.settings_store import api_key_hint

    found = []
    if api_key_hint(db, "gemini"):
        found.append(Check("Gemini", OK, "Clave guardada (pruébala en Configuración)"))
    else:
        found.append(
            Check("Gemini", FAIL, "Sin clave", "Ponla en Configuración: sin ella no hay guiones.")
        )
    if api_key_hint(db, "youtube"):
        found.append(Check("YouTube", OK, "Clave guardada: cifras exactas y comentarios"))
    else:
        found.append(
            Check(
                "YouTube",
                WARN,
                "Sin clave (opcional)",
                "Con la clave gratuita ves cifras exactas y lo que pide tu audiencia.",
            )
        )
    return found


def internet(get=None) -> Check:
    try:
        if get is None:
            with httpx.Client(timeout=8) as client:
                client.get("https://www.google.com/generate_204")
        else:
            get()
    except httpx.HTTPError:
        return Check(
            "Internet", FAIL, "Sin conexión", "Revisa el wifi: la investigación lo necesita."
        )
    return Check("Internet", OK, "Conectado")


def stuck_jobs(db: Session) -> Check:
    from app.models import Job

    count = db.scalar(
        select(func.count()).select_from(Job).where(Job.message == "Detenida tras varios cierres")
    )
    if count:
        return Check(
            "Tareas detenidas",
            WARN,
            f"{count} paso(s) detenido(s) porque el programa se cerraba",
            "Ábrelos desde el proyecto y pulsa «Reintentar» tras actualizar.",
        )
    return Check("Tareas detenidas", OK, "Ninguna")


def run_all(db: Session) -> list[Check]:
    checks = [Check("Versión", OK, f"Faceless Studio {VERSION}"), folders(), disk()]
    checks += [video_tools(), free_voice(), internet(), *keys(db), stuck_jobs(db)]
    return checks


def summary(checks: list[Check]) -> str:
    fails = sum(c.state == FAIL for c in checks)
    warns = sum(c.state == WARN for c in checks)
    if fails:
        return f"❌ {fails} cosa(s) fallan y {warns} conviene mirarlas."
    if warns:
        return f"⚠️ Todo funciona; {warns} cosa(s) conviene mirarlas."
    return "✅ Todo en orden."
