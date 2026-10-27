"""¿QUÉ MINIATURA GANÓ?: apuntar el resultado de «Probar y comparar» para aprender.

YouTube Studio prueba hasta 3 miniaturas durante unos 14 días y dice cuál gana. JARVIS lo
recuerda a las dos semanas, Simón apunta la ganadora con un botón y aquí se guarda cómo era
(dónde iba el texto y si llevaba una cifra). Con varias apuntadas, sale qué estilo funciona
en su canal. No usa IA ni internet.
"""

import json
import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

KEY = "thumb_winners"  # vídeo → {"n", "text", "layout", "number", "date"}
MIN_FOR_LESSON = 2  # con una sola ganadora todavía no se puede sacar nada
LAYOUT_NAMES = {"left": "texto a la izquierda", "bottom": "texto abajo",
                "center": "texto en el centro"}  # fmt: skip


def _load(db: Session) -> dict | None:
    """Lo guardado, o None si está dañado."""
    try:
        data = json.loads(get_setting(db, KEY) or "{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        log.warning("La lista de miniaturas ganadoras está dañada")
        return None
    return data


def winners(db: Session) -> dict[str, dict]:
    data = _load(db) or {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def record(db: Session, video_id: str, n: int, variant: dict | None) -> None:
    """Apunta la ganadora (n = 1, 2 o 3) o que no se probó (n = 0). Si lo guardado estaba
    dañado, se aparta una copia antes de empezar de nuevo (no se pierde)."""
    data = _load(db)
    if data is None:
        set_setting(db, KEY + "_danado", get_setting(db, KEY) or "")
        data = {}
    entry = {"n": n, "date": datetime.now().strftime("%Y-%m-%d")}
    if n and variant:
        text = str(variant.get("text") or "")
        entry |= {
            "text": text,
            "layout": str(variant.get("layout") or ""),
            "number": bool(re.search(r"\d", text)),
        }
    data[video_id] = entry
    set_setting(db, KEY, json.dumps(data, ensure_ascii=False))


def lesson(db: Session) -> str:
    """Qué estilo de miniatura suele ganar en el canal, o "" si aún hay pocas apuntadas."""
    won = [w for w in winners(db).values() if w.get("n")]
    if len(won) < MIN_FOR_LESSON:
        return ""
    layouts: dict[str, int] = {}
    for w in won:
        if w.get("layout") in LAYOUT_NAMES:
            layouts[w["layout"]] = layouts.get(w["layout"], 0) + 1
    layout, times = max(layouts.items(), key=lambda item: item[1]) if layouts else ("", 0)
    parts = []
    if times > len(won) / 2:
        parts.append(f"{times} de {len(won)} ganadoras llevan el {LAYOUT_NAMES[layout]}")
    numbers = sum(1 for w in won if w.get("number"))
    if numbers > len(won) / 2:
        parts.append(f"{numbers} de {len(won)} llevan una cifra")
    elif numbers == 0:
        parts.append("ninguna lleva cifras: en tu canal ganan las palabras")
    if not parts:
        return f"Llevas {len(won)} ganadoras apuntadas y aún no se repite un estilo claro."
    return "En tu canal, " + " y ".join(parts) + "."
