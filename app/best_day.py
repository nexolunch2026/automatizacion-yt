"""MEJOR DÍA PARA PUBLICAR: con tus propias cifras, qué día salen mejor tus vídeos.

Sin IA ni internet: mira las visitas de cada vídeo largo en sus primeras 48 horas (las que
guarda Rendimiento) y las agrupa por el día de la semana en que se publicó. De cada día
coge el valor del medio (la mediana) para que un solo vídeo con suerte no decida, y lo
compara con los demás días. Solo da un consejo cuando
hay datos suficientes y la diferencia es clara.
"""

import logging
from statistics import median

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

MIN_VIDEOS = 6  # con menos vídeos, cualquier diferencia es casualidad
MIN_PER_DAY = 3  # un día cuenta si se publicaron al menos 3 vídeos en él
RATIO = 1.3  # el mejor día tiene que sacar al menos un 30 % más que los demás días


def best_day(rows: list[dict], current_day: int) -> dict:
    """{"status": "few" | "one_day" | "same" | "best", "text", "day", "ratio", ...}.
    `current_day` es el día en que publicas ahora (0 = lunes)."""
    from app.agenda import WEEKDAYS

    usable = [
        r
        for r in rows
        if r.get("project_id")  # hecho con el programa: se sabe que no es un Short
        and not r.get("is_short")
        and r.get("exact_time")  # con la hora exacta, las 48 h se cuentan bien
        and r.get("views_48h") is not None
        and r.get("weekday") is not None
        and r.get("days", 0) >= 2
    ]
    if len(usable) < MIN_VIDEOS:
        missing = MIN_VIDEOS - len(usable)
        return {
            "status": "few",
            "day": None,
            "text": f"Aún faltan {missing} vídeos largos con sus cifras de las primeras 48 h "
            "para saber qué día te va mejor.",
        }
    by_day: dict[int, list[int]] = {}
    for r in usable:
        by_day.setdefault(r["weekday"], []).append(r["views_48h"])
    counted = {d: median(v) for d, v in by_day.items() if len(v) >= MIN_PER_DAY}
    if len(counted) < 2:
        return {
            "status": "one_day",
            "day": None,
            "text": "Casi siempre publicas el mismo día, así que no hay con qué comparar. "
            "Si quieres saberlo, prueba otro día durante dos semanas.",
        }
    day, value = max(counted.items(), key=lambda item: item[1])
    normal = median(r["views_48h"] for r in usable if r["weekday"] != day)  # los demás días
    ratio = value / normal if normal else 0
    if ratio < RATIO:
        return {
            "status": "same",
            "day": None,
            "text": "Tus vídeos van parecido salgan el día que salgan: sigue con tu día de "
            "siempre (lo que más cuenta es ser constante).",
        }
    name = WEEKDAYS[day]
    text = (
        f"Tus vídeos que salen en {name} consiguen unas {round(value)} visitas en 48 h (de "
        f"{len(by_day[day])} vídeos), un {round((ratio - 1) * 100)} % más que los de otros días."
    )
    if day != current_day:
        text += (
            f" Ahora publicas los {WEEKDAYS[current_day]}: prueba a cambiar al {name} unas "
            "semanas y mira si se nota (el tema y la miniatura también cuentan)."
        )
    else:
        text += " Ya publicas ese día: sigue así."
    return {"status": "best", "day": day, "ratio": round(ratio, 1), "text": text}


def advice(db: Session, current_day: int) -> dict | None:
    """El consejo para la página Semana y JARVIS. Si las cifras fallan, se apunta en el
    registro y no se enseña nada: el plan de la semana tiene que salir igual."""
    from app.analytics import video_rows

    try:
        return best_day(video_rows(db), current_day)
    except Exception:
        log.warning("No se pudo calcular el mejor día para publicar", exc_info=True)
        return None
