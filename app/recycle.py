"""SHORTS DE VÍDEOS QUE YA FUNCIONARON: sacar más partido a tus mejores vídeos.

Un vídeo que ya gustó tiene momentos que funcionarán como Short, y cada Short lleva gente
de vuelta al vídeo largo. Sin IA ni internet: busca tus vídeos publicados con más visitas
que tienen su proyecto en el programa y dice, para cada uno, el siguiente paso: hacer sus
Shorts, ponerles el enlace al vídeo largo o subirlos.
"""

from sqlalchemy.orm import Session

from app import jobs

LIMIT = 3


def suggest(db: Session, rows: list[dict]) -> list[dict]:
    """Hasta 3 vídeos (los de más visitas) con lo que toca hacer con sus Shorts."""
    found = []
    for row in sorted(rows, key=lambda r: r["views"] or 0, reverse=True):
        project_id = row.get("project_id")
        if not project_id or not jobs.get_result(db, project_id, "voice"):
            continue  # sin proyecto o sin narración no se pueden sacar Shorts
        shorts = jobs.get_result(db, project_id, "shorts") or {}
        count = len(shorts.get("shorts", []))
        if not count:
            step = "make"
        elif not shorts.get("long_url"):
            step = "link"
        else:
            step = "upload"
        found.append(
            {
                "project_id": project_id,
                "title": row["title"],
                "views": row["views"],
                "url": row["url"],
                "shorts": count,
                "step": step,
            }
        )
        if len(found) == LIMIT:
            break
    return found
