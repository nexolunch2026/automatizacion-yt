import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Todo lo que genera la app (base de datos, vídeos, audio…) vive en una carpeta fija del
# usuario (C:\Usuarios\<tú>\FacelessStudio\datos), fuera de la carpeta del programa y de
# OneDrive. Los datos de versiones anteriores (dentro del programa) se copian ahí solos.
if "FACELESS_DATA_DIR" in os.environ:
    DATA_DIR = Path(os.environ["FACELESS_DATA_DIR"])
else:
    from app.storage import home_dir, migrate_legacy

    DATA_DIR = home_dir() / "datos"
    try:
        if migrate_legacy(ROOT / "datos", DATA_DIR):
            print(f"\n  Tus datos se copiaron a su sitio nuevo: {DATA_DIR}")
    except (OSError, ValueError) as exc:  # sin espacio, archivo bloqueado…
        print(f"  AVISO: no se pudieron copiar los datos antiguos: {exc}")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'faceless.db'}"

HOST = os.environ.get("FACELESS_HOST", "127.0.0.1")
PORT = int(os.environ.get("FACELESS_PORT", "8000"))

# Solo dos cuentas: el dueño y su amigo.
MAX_USERS = 2

# El trabajador en segundo plano se desactiva en los tests.
WORKER_ENABLED = os.environ.get("FACELESS_WORKER", "1") == "1"


def _load_or_create(filename: str, generate) -> str:
    """Genera una clave la primera vez y la reutiliza después."""
    path = DATA_DIR / filename
    if not path.exists():
        path.write_text(generate(), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def _fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


SECRET_KEY = _load_or_create("secret.key", lambda: secrets.token_urlsafe(48))
# Cifra las claves API guardadas en la base de datos.
ENCRYPTION_KEY = _load_or_create("encryption.key", _fernet_key)

# Se muestra en la pantalla para saber qué versión está abierta.
VERSION = "0.66.2"
