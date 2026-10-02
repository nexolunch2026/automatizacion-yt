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


MUSIC_DIR = DATA_DIR / "musica"
MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}


def music_library() -> list[str]:
    """Canciones subidas por el usuario (la misma biblioteca para todos los proyectos)."""
    if not MUSIC_DIR.exists():
        return []
    return sorted(
        p.name for p in MUSIC_DIR.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS
    )


def music_path(name: str) -> Path | None:
    """Ruta de una canción de la biblioteca (o None si no existe o el nombre es raro)."""
    if not name or name not in music_library():
        return None
    return MUSIC_DIR / name
