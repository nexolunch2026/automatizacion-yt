"""Dónde se guardan tus datos y sus copias de seguridad.

- Los datos (cuentas, proyectos, vídeos, claves) viven en una carpeta fija de tu usuario,
  `C:\\Usuarios\\<tú>\\FacelessStudio`, fuera de OneDrive y separada del programa. Así da
  igual qué copia del programa abras o dónde la tengas: siempre ves los mismos datos.
- Antes se guardaban dentro de la carpeta del programa (`datos`). La primera vez se copian
  solos al sitio nuevo y la carpeta vieja se renombra para que no confunda.
- Cada día se guarda una copia pequeña de lo importante (base de datos y claves, sin los
  vídeos) en OneDrive si lo tienes, o si no en la carpeta de copias.
"""

import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

MOVED_NAME = "datos (copiados a FacelessStudio)"
DAILY_TO_KEEP = 14
NOTE = """Tus datos ya no están aquí.

Desde la versión 0.18, Faceless Studio guarda los proyectos, vídeos y claves en:
{target}

Esta carpeta es la copia antigua. Cuando compruebes que en el programa están todos tus
proyectos, puedes borrarla para liberar espacio.
"""


def home_dir() -> Path:
    return Path(os.environ.get("FACELESS_HOME", Path.home() / "FacelessStudio"))


def migrate_legacy(old: Path, new: Path) -> bool:
    """Copia los datos de la carpeta del programa al sitio nuevo (solo la primera vez)."""
    if (new / "faceless.db").exists() or not (old / "faceless.db").exists():
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    temp = new.parent / (new.name + ".copiando")
    shutil.rmtree(temp, ignore_errors=True)
    shutil.copytree(old, temp)
    # Comprueba que la base de datos copiada se abre bien antes de darla por buena.
    # (en Windows hay que cerrar la conexión: «with» solo confirma, no cierra el archivo)
    conn = sqlite3.connect(temp / "faceless.db")
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if ok != "ok":
        shutil.rmtree(temp, ignore_errors=True)
        raise ValueError(f"La base de datos antigua está dañada ({ok}); no se ha movido.")
    if new.exists():
        shutil.rmtree(new)  # carpeta vacía creada antes (sin base de datos)
    temp.rename(new)
    try:
        (old / "LEEME - tus datos se movieron.txt").write_text(
            NOTE.format(target=new), encoding="utf-8"
        )
        old.rename(old.parent / MOVED_NAME)
    except OSError:
        pass  # OneDrive o el antivirus pueden bloquear el nombre: no pasa nada
    return True


def cloud_folder() -> Path | None:
    """La carpeta de OneDrive del usuario (Windows la indica en %OneDrive%)."""
    for var in ("OneDrive", "OneDriveConsumer"):
        value = os.environ.get(var)
        if value and Path(value).is_dir():
            return Path(value) / "FacelessStudio-copias"
    return None


def backup_folder(data_dir: Path) -> Path:
    return cloud_folder() or data_dir.parent / "copias_de_seguridad" / "diarias"


def daily_backup(data_dir: Path, now: datetime | None = None, target: Path | None = None) -> Path:
    """ZIP con la base de datos (copiada de forma segura aunque el programa esté abierto),
    las claves y la música pequeña. Sin vídeos ni imágenes: ocupa muy poco."""
    now = now or datetime.now()
    target = target or backup_folder(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    out = target / f"faceless-{now:%Y-%m-%d}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "faceless.db"
        source, dest = sqlite3.connect(data_dir / "faceless.db"), sqlite3.connect(snapshot)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        partial = out.with_suffix(".tmp")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, "datos/faceless.db")
            for name in ("secret.key", "encryption.key"):
                if (data_dir / name).exists():
                    zf.write(data_dir / name, f"datos/{name}")
            zf.writestr(
                "COMO RESTAURAR.txt",
                "1. Cierra la ventana negra de Faceless Studio.\n"
                f"2. Copia el contenido de la carpeta «datos» de este ZIP en:\n   {data_dir}\n"
                "   (reemplaza los archivos).\n"
                "3. Abre el programa. Los vídeos e imágenes no van en esta copia: si se\n"
                "   perdieron, se pueden volver a generar desde cada proyecto.\n",
            )
        partial.replace(out)
    for old in sorted(target.glob("faceless-*.zip"))[:-DAILY_TO_KEEP]:
        old.unlink(missing_ok=True)
    return out
