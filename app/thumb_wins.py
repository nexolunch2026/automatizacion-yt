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


def preference(db: Session) -> dict:
    """Lo que suele ganar: {"count", "layout" (o ""), "layout_times", "number" (True, False
    o None si no hay mayoría), "numbers"}. Solo cuenta con 2 o más ganadoras."""
    won = [w for w in winners(db).values() if w.get("n")]
    found = {"count": len(won), "layout": "", "layout_times": 0, "number": None, "numbers": 0}
    if len(won) < MIN_FOR_LESSON:
        return found
    layouts: dict[str, int] = {}
    for w in won:
        if isinstance(w.get("layout"), str) and w["layout"] in LAYOUT_NAMES:
            layouts[w["layout"]] = layouts.get(w["layout"], 0) + 1
    layout, times = max(layouts.items(), key=lambda item: item[1]) if layouts else ("", 0)
    if times > len(won) / 2:
        found |= {"layout": layout, "layout_times": times}
    numbers = sum(1 for w in won if w.get("number"))
    found["numbers"] = numbers
    if numbers > len(won) / 2:
        found["number"] = True
    elif numbers == 0:
        found["number"] = False
    return found


def lesson(db: Session) -> str:
    """Qué estilo de miniatura suele ganar en el canal, o "" si aún hay pocas apuntadas."""
    found = preference(db)
    won = found["count"]
    if won < MIN_FOR_LESSON:
        return ""
    parts = []
    if found["layout"]:
        parts.append(
            f"{found['layout_times']} de {won} ganadoras llevan el {LAYOUT_NAMES[found['layout']]}"
        )
    if found["number"] is True:
        parts.append(f"{found['numbers']} de {won} llevan una cifra")
    elif found["number"] is False:
        parts.append("ninguna lleva cifras: en tu canal ganan las palabras")
    if not parts:
        return f"Llevas {won} ganadoras apuntadas y aún no se repite un estilo claro."
    return "En tu canal, " + " y ".join(parts) + "."


def prompt_hint(db: Session) -> str:
    """Una frase para Gemini al escribir los textos de las miniaturas ("" si no se sabe)."""
    found = preference(db)
    if found["number"] is True:
        return (
            "En este canal suelen ganar las miniaturas con una cifra: que al menos dos de "
            "los textos lleven una cifra o un año real del guion."
        )
    if found["number"] is False:
        return (
            "En este canal suelen ganar las miniaturas solo con palabras (sin cifras): que "
            "al menos dos de los textos sean solo palabras."
        )
    return ""
