"""PIPER SIN SUSTOS: que la voz gratuita nunca pueda apagar el programa.

Piper usa espeak-ng (una librería en C) para la pronunciación. En Windows, espeak-ng no
sabe leer su carpeta de datos si la ruta tiene tildes o eñes (p. ej. «C:\\Users\\Simón») y
entonces busca otra carpeta que no existe y CIERRA TODO EL PROGRAMA, sin dar error de
Python. Si había un vídeo a medias en el paso de voz, el programa se cerraba nada más
abrirlo, una y otra vez.

- En Windows, los datos de espeak-ng se copian una vez a una carpeta con ruta sencilla.
- Antes de usar Piper por primera vez se prueba en un proceso aparte: si falla, solo
  falla la voz (con un mensaje claro) y el programa sigue encendido.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import DATA_DIR
from app.providers.ai import ProviderError

CHECK = (
    "import sys\n"
    "from piper.phonemize_espeak import EspeakPhonemizer\n"
    "EspeakPhonemizer(sys.argv[1]).phonemize('es', 'hola')\n"
)
_checked: dict[str, bool] = {}


def simple(path: Path) -> bool:
    text = str(path)
    return text.isascii() and "onedrive" not in text.lower()


def candidates() -> list[Path]:
    bases = [DATA_DIR.parent]
    if public := os.environ.get("PUBLIC"):
        bases.append(Path(public) / "FacelessStudio")
    bases.append(Path(os.environ.get("SystemDrive", "C:") + "\\") / "FacelessStudio")
    return [base / "espeak-ng-data" for base in bases if simple(base)]


def _same(source: Path, target: Path) -> bool:
    try:
        return (target / "phontab").stat().st_size == (source / "phontab").stat().st_size
    except OSError:
        return False


def data_dir(source: Path, places: list[Path] | None = None) -> Path:
    """Una carpeta de datos de espeak-ng que espeak-ng pueda leer."""
    if sys.platform != "win32" or simple(source):
        return source
    for target in candidates() if places is None else places:
        if _same(source, target):
            return target
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError:
            continue
        if _same(source, target):
            return target
    return source


def check(espeak_dir: Path, run=subprocess.run) -> None:
    """Prueba espeak-ng en un proceso aparte (una vez). Si se cierra, avisa sin caerse."""
    key = str(espeak_dir)
    if key not in _checked:
        try:
            done = run(
                [sys.executable, "-c", CHECK, key],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            _checked[key] = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _checked[key] = False
    if not _checked[key]:
        raise ProviderError(
            "La voz gratuita (Piper) no funciona en este ordenador. Prueba a actualizar el "
            "programa o elige una voz de ElevenLabs en el paso de voz.",
            detail=f"espeak-ng no arrancó con {key}",
        )
