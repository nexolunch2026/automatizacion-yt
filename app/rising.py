"""VÍDEO QUE DESPEGA: avisar cuando un vídeo nuevo va mucho mejor de lo normal.

Las primeras 48 horas deciden mucho: si un vídeo arranca al doble de lo habitual, es el
momento de empujarlo (responder comentarios, sacar un Short que lleve a él) y de preparar
otro parecido. Sin IA ni internet: compara sus visitas con las que suelen tener tus vídeos
a las 48 horas (de las cifras que ya guarda Rendimiento).
"""

from datetime import datetime, timedelta

RATIO = 2.0  # el doble de lo normal
MIN_HOURS = 12  # antes, las cifras bailan demasiado
MAX_HOURS = 72  # pasado el arranque, ya no es «despegar»
MIN_OTHERS = 2  # hacen falta al menos 2 vídeos para saber qué es lo normal
FRESH = timedelta(hours=6)  # cifras más viejas no sirven para hablar de «ahora»


def rising(rows: list[dict], now: datetime) -> list[dict]:
    """Los vídeos en su arranque que van al doble (o más) de lo normal en tu canal.
    Cada uno: {video_id, title, views, hours, ratio}."""
    # Lo normal: las visitas a las 48 h de los vídeos que ya las cumplieron.
    finished = {
        r["video_id"]: r["views_48h"]
        for r in rows
        if r["days"] >= 2 and r.get("views_48h") is not None
    }
    found = []
    for row in rows:
        hours = row["days"] * 24
        if not MIN_HOURS <= hours <= MAX_HOURS or not row.get("exact_time"):
            continue  # sin la hora exacta de publicación, la edad puede fallar un día
        if row.get("updated") and now - row["updated"] > FRESH:
            continue  # las cifras no se han actualizado: no se puede saber
        others = [views for vid, views in finished.items() if vid != row["video_id"]]
        if len(others) < MIN_OTHERS:
            continue
        normal = sum(others) / len(others)
        # Lo normal a esa misma edad: las visitas llegan sobre todo al principio, así que
        # a las 12 h un vídeo ya suele llevar la mitad de las de 48 h.
        expected = normal * (min(hours, 48) / 48) ** 0.5
        if expected <= 0:
            continue
        ratio = row["views"] / expected
        if ratio >= RATIO:
            found.append(
                {
                    "video_id": row["video_id"],
                    "title": row["title"],
                    "views": row["views"],
                    "hours": round(hours),
                    "ratio": round(ratio, 1),
                }
            )
    return found
