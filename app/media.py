"""Archivos generados de cada proyecto (audio, imágenes, vídeo) dentro de `datos/`."""

import shutil
from pathlib import Path

from app.config import DATA_DIR

PROJECTS_DIR = DATA_DIR / "proyectos"


def project_dir(project_id: int) -> Path:
    path = PROJECTS_DIR / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_path(project_id: int, relative: str) -> Path | None:
    """Ruta dentro de la carpeta del proyecto, o None si intenta salirse de ella."""
    base = project_dir(project_id).resolve()
    target = (base / relative).resolve()
    return target if target.is_relative_to(base) and target.is_file() else None


def delete_project_files(project_id: int) -> None:
    shutil.rmtree(PROJECTS_DIR / str(project_id), ignore_errors=True)
