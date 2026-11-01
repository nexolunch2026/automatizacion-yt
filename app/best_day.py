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


def _usable(rows: list[dict]) -> list[dict]:
    """Vídeos largos hechos con el programa, con hora exacta y cifras de las 48 h."""
    return [
        r
        for r in rows
        if r.get("project_id")  # hecho con el programa: se sabe que no es un Short
        and not r.get("is_short")
        and r.get("exact_time")  # con la hora exacta, las 48 h se cuentan bien
        and r.get("views_48h") is not None
        and r.get("weekday") is not None
        and r.get("days", 0) >= 2
    ]


def best_day(rows: list[dict], current_day: int) -> dict:
    """{"status": "few" | "one_day" | "same" | "best", "text", "day", "ratio", ...}.
    `current_day` es el día en que publicas ahora (0 = lunes)."""
    from app.agenda import WEEKDAYS

    usable = _usable(rows)
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


# Franjas del día: (nombre, desde, hasta, hora que se propone). De madrugada no se propone.
BANDS = [
    ("por la mañana", 6, 12, 10),
    ("al mediodía", 12, 15, 13),
    ("por la tarde", 15, 19, 17),
    ("por la noche", 19, 24, 20),
]


def _band(hour: int) -> int | None:
    return next((i for i, (_, start, end, _h) in enumerate(BANDS) if start <= hour < end), None)


def best_hour(rows: list[dict], current_hour: int) -> dict:
    """Igual que el mejor día, pero por franjas del día (mañana, mediodía, tarde, noche).
    {"status": "few" | "one_band" | "same" | "best", "text", "hour"}."""
    # De madrugada no se propone publicar: esos vídeos no entran en la comparación.
    usable = [
        r for r in _usable(rows) if isinstance(r.get("hour"), int) and _band(r["hour"]) is not None
    ]
    if len(usable) < MIN_VIDEOS:
        return {"status": "few", "hour": None, "text": ""}  # ya lo explica el mejor día
    by_band: dict[int, list[int]] = {}
    for r in usable:
        by_band.setdefault(_band(r["hour"]), []).append(r["views_48h"])
    counted = {b: median(v) for b, v in by_band.items() if len(v) >= MIN_PER_DAY}
    if len(by_band) == 1:
        return {
            "status": "one_band",
            "hour": None,
            "text": "Casi siempre publicas a la misma hora, así que no hay con qué comparar.",
        }
    if len(counted) < 2:
        return {
            "status": "few",
            "hour": None,
            "text": "Aún hay pocos vídeos en cada franja horaria para saber cuál te va mejor.",
        }
    band, value = max(counted.items(), key=lambda item: item[1])
    others = [
        r["views_48h"] for r in usable if _band(r["hour"]) in counted and _band(r["hour"]) != band
    ]
    normal = median(others) if others else 0
    ratio = value / normal if normal else 0
    if ratio < RATIO:
        return {
            "status": "same",
            "hour": None,
            "text": "La hora no cambia mucho tus visitas: sigue con tu hora de siempre.",
        }
    name, _start, _end, hour = BANDS[band]
    text = (
        f"Tus vídeos que salen {name} consiguen unas {round(value)} visitas en 48 h (de "
        f"{len(by_band[band])} vídeos), un {round((ratio - 1) * 100)} % más que a otras horas."
    )
    if _band(current_hour) != band:
        text += f" Ahora publicas a las {current_hour}:00: prueba a las {hour}:00 unas semanas."
    else:
        text += " Ya publicas en esa franja: sigue así."
    return {"status": "best", "hour": hour, "ratio": round(ratio, 1), "text": text,
            "change": _band(current_hour) != band}  # fmt: skip


def advice_both(
    db: Session, current_day: int, current_hour: int
) -> tuple[dict | None, dict | None]:
    """El consejo de día y el de hora, leyendo las cifras una sola vez. Si fallan, se
    apunta en el registro y no se enseña nada: el plan de la semana sale igual."""
    from app.analytics import video_rows

    try:
        rows = video_rows(db)
        return best_day(rows, current_day), best_hour(rows, current_hour)
    except Exception:
        log.warning("No se pudo calcular el mejor día y hora para publicar", exc_info=True)
        return None, None
