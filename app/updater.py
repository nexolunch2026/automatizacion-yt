"""Actualiza Faceless Studio a la última versión sin tocar la carpeta `datos`.

Uso: doble clic en Actualizar.bat (que ejecuta `python -m app.updater`).
"""

import io
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import httpx

from app.config import DATA_DIR, HOST, PORT, ROOT, VERSION

REPO = "nexolunch2026/automatizacion-yt"
BRANCH = "claude/hola-5p4ttp"
PUBLIC_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
# Con token (repositorio privado) se usa la API de GitHub.
API_URL = f"https://api.github.com/repos/{REPO}/zipball/{BRANCH}"
# Lo que nunca se sobrescribe: tus datos, el entorno de Python y las copias de seguridad.
PROTECTED = {"datos", ".venv", "copias_de_seguridad", ".git"}
BACKUPS_TO_KEEP = 5


class UpdateError(Exception):
    pass


def saved_github_token() -> str | None:
    """El token de GitHub guardado en Configuración (solo hace falta si el repo es privado)."""
    from app.db import SessionLocal, init_db
    from app.settings_store import get_api_key

    init_db()
    with SessionLocal() as db:
        return get_api_key(db, "github")


def download(token: str | None = None, transport: httpx.BaseTransport | None = None) -> bytes:
    if token:
        url = API_URL
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    else:
        url, headers = PUBLIC_URL, {}
    try:
        with httpx.Client(transport=transport, timeout=60, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise UpdateError(
            f"No se pudo descargar la versión nueva. Revisa tu internet. ({exc})"
        ) from exc
    if response.status_code in (401, 403, 404):
        if token:
            raise UpdateError(
                "GitHub rechazó el token. Revisa en Configuración que esté bien copiado "
                "y que no haya caducado."
            )
        raise UpdateError(
            "El repositorio es privado, así que GitHub no deja descargarlo sin permiso. "
            "Pon un token de GitHub en Configuración (o haz público el repositorio)."
        )
    if response.status_code >= 400:
        raise UpdateError(f"GitHub respondió con un error ({response.status_code}).")
    return response.content


def read_version(config_text: str) -> str:
    match = re.search(r'^VERSION = "([^"]+)"', config_text, re.MULTILINE)
    return match.group(1) if match else "?"


def extract(zip_bytes: bytes, target: Path) -> Path:
    """Descomprime y devuelve la carpeta principal (la que contiene Iniciar.bat)."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            archive.extractall(target)
    except zipfile.BadZipFile as exc:
        raise UpdateError("El archivo descargado está dañado. Vuelve a intentarlo.") from exc
    for candidate in [target, *target.iterdir()]:
        if (candidate / "Iniciar.bat").exists() and (candidate / "app").is_dir():
            return candidate
    raise UpdateError("La descarga no contiene el programa. Avisa a Claude.")


def backup_data(root: Path, data_dir: Path) -> Path | None:
    """Copia de seguridad de `datos` antes de actualizar (se guardan las 5 últimas)."""
    if not data_dir.exists():
        return None
    backups = root / "copias_de_seguridad"
    backups.mkdir(exist_ok=True)
    target = backups / f"datos-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copytree(data_dir, target)
    for old in sorted(backups.glob("datos-*"))[:-BACKUPS_TO_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return target


def install(source: Path, root: Path) -> int:
    """Copia los archivos nuevos encima de los viejos, sin tocar las carpetas protegidas."""
    copied = 0
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if relative.parts[0] in PROTECTED or not path.is_file():
            continue
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def update(root: Path = ROOT, data_dir: Path = DATA_DIR, fetch=None) -> str:
    fetch = fetch or (lambda: download(saved_github_token()))
    with tempfile.TemporaryDirectory(prefix="faceless-update-") as tmp:
        source = extract(fetch(), Path(tmp))
        new_version = read_version((source / "app" / "config.py").read_text(encoding="utf-8"))
        backup_data(root, data_dir)
        install(source, root)
    return new_version


def main() -> None:
    from app.__main__ import port_in_use

    print("\n  Actualizando Faceless Studio...")
    print(f"  Versión actual: {VERSION}\n")
    if port_in_use(HOST, PORT):
        print("  ATENCION: el programa está abierto.")
        print("  Cierra la ventana negra de Faceless Studio y vuelve a hacer doble clic")
        print("  en Actualizar.\n")
        sys.exit(1)
    try:
        new_version = update()
    except UpdateError as exc:
        print(f"  No se pudo actualizar: {exc}\n")
        sys.exit(1)
    if new_version == VERSION:
        print(f"  Ya tenías la última versión ({VERSION}). Todo sigue igual.\n")
    else:
        print(f"  ¡Listo! Actualizado de la versión {VERSION} a la {new_version}.\n")
    print("  Tus datos (cuentas, proyectos, clave) se han conservado.")
    print("  Ahora haz doble clic en Iniciar.\n")


if __name__ == "__main__":
    main()
