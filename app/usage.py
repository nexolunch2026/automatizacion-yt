"""CONSUMO: cuánto gasta cada vídeo (llamadas a Gemini, texto procesado y créditos de
ElevenLabs), por etapa y por mes. Idea sacada de «AS Video Studio».

Mientras el trabajador hace una tarea, `measure()` abre un contador; los proveedores
apuntan lo que gastan con `record()` y al terminar se suma al proyecto.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

KINDS = ("gemini_calls", "gemini_tokens", "eleven_credits")
_meter: ContextVar[dict | None] = ContextVar("usage_meter", default=None)


def record(kind: str, amount: int = 1) -> None:
    """Apunta un gasto en el contador abierto (si no hay ninguno, no hace nada)."""
    meter = _meter.get()
    if meter is not None and kind in KINDS and amount:
        meter[kind] = meter.get(kind, 0) + int(amount)


@contextmanager
def measure() -> Iterator[dict]:
    meter: dict = {}
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def _load(db: Session, key: str) -> dict:
    try:
        data = json.loads(get_setting(db, key) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(db: Session, project_id: int, stage: str, meter: dict, now: datetime | None = None):
    """Suma lo gastado en una tarea al proyecto (por etapa) y al mes."""
    if not any(meter.get(k) for k in KINDS):
        return
    key = f"usage:{project_id}"
    data = _load(db, key)
    by_stage = data.setdefault(stage, {})
    for kind in KINDS:
        by_stage[kind] = by_stage.get(kind, 0) + meter.get(kind, 0)
    set_setting(db, key, json.dumps(data))
    month_key = f"usage_month:{(now or datetime.now()).strftime('%Y-%m')}"
    month = _load(db, month_key)
    for kind in KINDS:
        month[kind] = month.get(kind, 0) + meter.get(kind, 0)
    set_setting(db, month_key, json.dumps(month))


def project_usage(db: Session, project_id: int) -> dict:
    stages = _load(db, f"usage:{project_id}")
    total = {k: sum(s.get(k, 0) for s in stages.values()) for k in KINDS}
    return {"stages": stages, "total": total}


def month_usage(db: Session, now: datetime | None = None) -> dict:
    data = _load(db, f"usage_month:{(now or datetime.now()).strftime('%Y-%m')}")
    return {k: data.get(k, 0) for k in KINDS}
