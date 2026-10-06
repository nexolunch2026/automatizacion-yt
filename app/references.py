"""REFERENCIAS: qué funciona en los canales que admiras (como vidIQ, gratis).

Guardas los @ de 3–8 canales de tu nicho. Se leen sus últimos vídeos (con la clave de
YouTube si la hay; si no, la página pública y su RSS) y se marcan los que van mucho mejor
de lo normal EN ESE canal (visitas por día frente a la mediana del canal): son temas que
ya han demostrado interés y que puedes contar a tu manera.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from statistics import median

from sqlalchemy.orm import Session

from app import info
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

KEY = "reference_channels"
MAX_CHANNELS = 8
OUTLIER = 2.0  # el doble de visitas por día que la mediana del canal
CACHE_SECONDS = 6 * 3600
HANDLE = re.compile(r"(@[\w.\-]{3,60})|(UC[\w-]{22})")


def handles(db: Session) -> list[str]:
    try:
        data = json.loads(get_setting(db, KEY) or "[]")
    except ValueError:
        return []
    return [h for h in data if isinstance(h, str)][:MAX_CHANNELS]


def add(db: Session, text: str) -> str | None:
    """Añade el canal (acepta «@Canal», un enlace o el id UC…). Devuelve el @ o None."""
    match = HANDLE.search(text or "")
    if not match:
        return None
    handle = match.group(0)
    current = handles(db)
    if handle.lower() not in {h.lower() for h in current}:
        set_setting(db, KEY, json.dumps((current + [handle])[:MAX_CHANNELS]))
    return handle


def remove(db: Session, handle: str) -> None:
    set_setting(db, KEY, json.dumps([h for h in handles(db) if h != handle]))


def _days_since(published: str, now: datetime) -> float:
    try:
        moment = datetime.fromisoformat(published.replace("Z", "+00:00")[:25])
    except ValueError:
        return 30.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max((now - moment).total_seconds() / 86400, 0.5)


def analyze(videos: list[dict], now: datetime | None = None) -> list[dict]:
    """Cada vídeo con sus visitas por día y cuántas veces supera la mediana del canal."""
    now = now or datetime.now(UTC)
    rows = []
    for v in videos:
        days = _days_since(v.get("published", ""), now)
        rows.append({**v, "days": round(days, 1), "per_day": round(v.get("views", 0) / days, 1)})
    # La media del canal, sin los recién subidos (sus primeras horas lo distorsionan todo).
    settled = [r["per_day"] for r in rows if r["days"] >= 2] or [r["per_day"] for r in rows]
    typical = median(settled) if settled else 0
    for r in rows:
        r["ratio"] = round(r["per_day"] / typical, 1) if typical else None
        # Un vídeo de horas aún no dice nada: solo cuentan los que llevan 2+ días.
        r["outlier"] = bool(r["ratio"] and r["ratio"] >= OUTLIER and r["days"] >= 2)
    return sorted(rows, key=lambda r: r["ratio"] or 0, reverse=True)


def _fetch(handle: str, key: str | None) -> dict:
    data = (
        info.fetch_youtube_api(handle, key, limit=15)
        if key
        else info.fetch_youtube_public(handle, limit=15)
    )
    return {"handle": handle, "name": data.get("name") or handle,
            "subscribers": data.get("subscribers"), "videos": data.get("latest") or []}  # fmt: skip


def channel(handle: str, key: str | None) -> dict:
    found = info.cached(f"ref:{handle}:{bool(key)}", CACHE_SECONDS, lambda: _fetch(handle, key))
    if not found:
        return {"handle": handle, "name": handle, "error": True, "videos": []}
    return {**found, "videos": analyze(found["videos"])}


def overview(db: Session) -> list[dict]:
    """Todos los canales de referencia (en paralelo: tarda lo que el más lento)."""
    key = get_api_key(db, "youtube")
    current = handles(db)
    if not current:
        return []
    with ThreadPoolExecutor(max_workers=min(len(current), 6)) as pool:
        return list(pool.map(lambda h: channel(h, key), current))


def top_outliers(channels: list[dict], limit: int = 6) -> list[dict]:
    """Los vídeos que más destacan de todos los canales, para la parte de arriba."""
    rows = [
        {**v, "channel": c["name"]} for c in channels for v in c.get("videos", []) if v["outlier"]
    ]
    return sorted(rows, key=lambda r: r["ratio"] or 0, reverse=True)[:limit]
