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


def _load_secret_key() -> str:
    """Genera la clave de sesiones la primera vez y la reutiliza después."""
    path = DATA_DIR / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = _load_secret_key()
