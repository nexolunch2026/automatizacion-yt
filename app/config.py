import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Todo lo que genera la app (base de datos, vídeos, audio…) vive en esta carpeta.
DATA_DIR = Path(os.environ.get("FACELESS_DATA_DIR", ROOT / "datos"))
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
VERSION = "0.9.1"
