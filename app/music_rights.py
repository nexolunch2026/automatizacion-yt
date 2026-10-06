"""De dónde sale cada canción de la biblioteca de música y con qué licencia.

YouTube puede quitar la monetización (o poner reclamaciones de Content ID) si la música
no es libre para canales monetizados. Aquí se apunta el origen de cada canción una vez, y
el control de calidad y los créditos del vídeo lo usan.
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

KEY = "music_licenses"
# clave → (nombre, ¿segura para monetizar?, ¿pide atribución en la descripción?)
SOURCES = {
    "youtube": ("Biblioteca de audio de YouTube", True, False),
    "pixabay": ("Pixabay Music", True, False),
    "comprada": ("Comprada o con suscripción (Epidemic Sound, Artlist…)", True, False),
    "cc_by": ("Creative Commons con atribución (CC BY)", True, True),
    "propia": ("Hecha por mí o con IA con licencia comercial", True, False),
    "desconocida": ("No lo sé", False, False),
}
MAX_CREDIT = 300


def licenses(db: Session) -> dict[str, dict]:
    try:
        data = json.loads(get_setting(db, KEY) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(db: Session, name: str, source: str, credit: str = "") -> None:
    data = licenses(db)
    if source not in SOURCES:
        data.pop(name, None)
    else:
        data[name] = {
            "source": source,
            "credit": " ".join(credit.split())[:MAX_CREDIT],
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
    set_setting(db, KEY, json.dumps(data, ensure_ascii=False))


def forget(db: Session, name: str) -> None:
    data = licenses(db)
    if data.pop(name, None) is not None:
        set_setting(db, KEY, json.dumps(data, ensure_ascii=False))


def status(info: dict | None) -> str:
    """«ok», «credit» (falta el texto de atribución), «unknown» (sin apuntar o no se sabe)."""
    if not info or info.get("source") not in SOURCES:
        return "unknown"
    _, safe, needs_credit = SOURCES[info["source"]]
    if not safe:
        return "unknown"
    if needs_credit and not info.get("credit"):
        return "credit"
    return "ok"


def credit_line(db: Session, name: str | None) -> str:
    """Lo que hay que poner en la descripción sobre la música del vídeo."""
    info = licenses(db).get(name or "")
    if not name or not info:
        return ""
    label = SOURCES.get(info.get("source"), ("",))[0]
    if info.get("credit"):
        return f"Música: {info['credit']}"
    return f"Música: {name.rsplit('.', 1)[0]} ({label})" if label else ""
