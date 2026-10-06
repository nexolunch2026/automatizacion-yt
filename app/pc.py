"""JARVIS controla el ordenador (Windows): abrir carpetas y programas, volumen y música.

El programa corre en el propio ordenador del creador, así que puede pedirle cosas a Windows.
Nada peligroso: no apaga, no borra y no instala nada. Fuera de Windows (o en las pruebas)
no se ejecuta nada: `RUN` se reemplaza.
"""

import os
import subprocess
from pathlib import Path

from app.config import DATA_DIR

HOME = Path.home()

# Carpetas que se pueden abrir con la voz (clave sin tildes, en minúsculas).
FOLDERS = {
    "descargas": HOME / "Downloads",
    "documentos": HOME / "Documents",
    "escritorio": HOME / "Desktop",
    "imagenes": HOME / "Pictures",
    "fotos": HOME / "Pictures",
    "mis videos": HOME / "Videos",
    "musica": HOME / "Music",
    "datos": DATA_DIR,
    "carpeta de datos": DATA_DIR,
    "carpeta de proyectos": DATA_DIR / "proyectos",
    "copias de seguridad": DATA_DIR.parent / "copias_de_seguridad",
}

# Programas de Windows: nombre → lo que se lanza (programa o dirección especial).
PROGRAMS = {
    "calculadora": "calc",
    "bloc de notas": "notepad",
    "notas": "notepad",
    "explorador": "explorer",
    "explorador de archivos": "explorer",
    "archivos": "explorer",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "spotify": "spotify:",
    "configuracion de windows": "ms-settings:",
    "ajustes de windows": "ms-settings:",
    "camara": "microsoft.windows.camera:",
    "reloj": "ms-clock:",
    "alarmas": "ms-clock:",
}

# Teclas multimedia (código de tecla virtual de Windows) y cuántas veces pulsarlas.
MEDIA_KEYS = {
    "volume_up": (175, 5, "🔊 Subo el volumen."),
    "volume_down": (174, 5, "🔉 Bajo el volumen."),
    "mute": (173, 1, "🔇 Sonido silenciado (dilo otra vez para quitarlo)."),
    "play_pause": (179, 1, "⏯️ Hecho: pausa / continuar."),
    "next": (176, 1, "⏭️ Siguiente canción."),
    "previous": (177, 1, "⏮️ Canción anterior."),
}

# Frases fijas (sin tildes, en minúsculas) → acción.
PHRASES = {
    "sube el volumen": "volume_up",
    "subele al volumen": "volume_up",
    "mas volumen": "volume_up",
    "sube volumen": "volume_up",
    "baja el volumen": "volume_down",
    "bajale al volumen": "volume_down",
    "menos volumen": "volume_down",
    "baja volumen": "volume_down",
    "silencio": "mute",
    "silencia": "mute",
    "quita el sonido": "mute",
    "pon el sonido": "mute",
    "pausa": "play_pause",
    "pausa la musica": "play_pause",
    "para la musica": "play_pause",
    "continua la musica": "play_pause",
    "reanuda la musica": "play_pause",
    "siguiente cancion": "next",
    "pasa la cancion": "next",
    "cancion anterior": "previous",
    "bloquea el ordenador": "lock",
    "bloquea el pc": "lock",
    "bloquea el computador": "lock",
}


def is_windows() -> bool:
    return os.name == "nt"


def _run(kind: str, value) -> None:
    """Le pide algo a Windows sin abrir ventanas negras."""
    if kind == "start":
        os.startfile(str(value))  # noqa: S606 — carpetas y programas de la lista de arriba
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if kind == "keys":
        code, times = value
        script = (
            "$w = New-Object -ComObject WScript.Shell; "
            f"1..{times} | % {{ $w.SendKeys([char]{code}) }}"
        )
        subprocess.Popen(["powershell", "-NoProfile", "-Command", script], creationflags=flags)
    elif kind == "lock":
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], creationflags=flags)


RUN = _run  # se reemplaza en las pruebas


def find_target(norm: str) -> tuple[str, object] | None:
    """¿«abre …» se refiere a una carpeta o a un programa del ordenador?"""
    norm = norm.strip(" .")
    for prefix in (
        "la carpeta de ",
        "carpeta de ",
        "la carpeta ",
        "carpeta ",
        "el ",
        "la ",
        "mi ",
        "mis ",
    ):
        if norm.startswith(prefix) and norm[len(prefix) :] in FOLDERS:
            return "folder", norm[len(prefix) :]
    if norm in FOLDERS:
        return "folder", norm
    for prefix in ("el programa ", "la app ", "el ", "la ", ""):
        name = norm[len(prefix) :] if norm.startswith(prefix) else None
        if name in PROGRAMS:
            return "program", name
    return None


def do(action: str, name: str = "") -> str:
    """Hace la acción y devuelve lo que JARVIS contesta."""
    if not is_windows() and RUN is _run:
        return "Eso solo puedo hacerlo en el ordenador con Windows donde está el programa."
    if action == "folder":
        path = FOLDERS[name]
        if not Path(path).exists():
            return f"No encuentro la carpeta «{name}» en este ordenador."
        RUN("start", path)
        return f"📂 Abro la carpeta {name}."
    if action == "program":
        RUN("start", PROGRAMS[name])
        return f"🖥️ Abro {name}."
    if action == "lock":
        RUN("lock", None)
        return "🔒 Bloqueo el ordenador. Hasta ahora."
    if action in MEDIA_KEYS:
        code, times, text = MEDIA_KEYS[action]
        RUN("keys", (code, times))
        return text
    return "No sé hacer eso en el ordenador todavía."
