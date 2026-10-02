"""Guarda preferencias y claves API. Las claves se cifran y nunca se vuelven a mostrar."""

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import ENCRYPTION_KEY
from app.models import Setting

_fernet = Fernet(ENCRYPTION_KEY.encode())


def _key(provider: str) -> str:
    return f"api_key:{provider}"


def save_api_key(db: Session, provider: str, api_key: str) -> None:
    token = _fernet.encrypt(api_key.encode()).decode()
    db.merge(Setting(key=_key(provider), value=token))
    db.commit()


def get_api_key(db: Session, provider: str) -> str | None:
    row = db.get(Setting, _key(provider))
    if row is None:
        return None
    try:
        return _fernet.decrypt(row.value.encode()).decode()
    except InvalidToken:
        return None


def delete_api_key(db: Session, provider: str) -> None:
    row = db.get(Setting, _key(provider))
    if row is not None:
        db.delete(row)
        db.commit()


def api_key_hint(db: Session, provider: str) -> str | None:
    """Solo los 4 últimos caracteres, para que el usuario sepa qué clave tiene guardada."""
    key = get_api_key(db, provider)
    return f"••••{key[-4:]}" if key else None
