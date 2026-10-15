"""SHORTS DE VÍDEOS QUE YA FUNCIONARON: sacar más partido a tus mejores vídeos.

Un vídeo que ya gustó tiene momentos que funcionarán como Short, y cada Short lleva gente
de vuelta al vídeo largo. Sin IA ni internet: busca tus vídeos publicados con más visitas
que tienen su proyecto en el programa y dice, para cada uno, el siguiente paso: hacer sus
Shorts, ponerles el enlace al vídeo largo o subirlos.
"""

from sqlalchemy.orm import Session

from app import jobs
from app.models import Project

LIMIT = 3


def suggest(db: Session, rows: list[dict]) -> list[dict]:
    """Hasta 3 vídeos (los de más visitas) con lo que toca hacer con sus Shorts."""
    found = []
    for row in sorted(rows, key=lambda r: r["views"] or 0, reverse=True):
        project_id = row.get("project_id")
        project = db.get(Project, project_id) if project_id else None
        if project is None or jobs.is_portrait(project):
            continue  # sin proyecto, o ya es un Short
        if not all(jobs.get_result(db, project_id, s) for s in ("script", "storyboard", "voice")):
            continue  # le falta guion, escenas o narración: no se pueden sacar Shorts
        shorts = jobs.get_result(db, project_id, "shorts") or {}
        count = len(shorts.get("shorts", []))
        job = jobs.latest_jobs(db, project_id).get("shorts")
        if job and job.active:
            step = "working"
        elif not count and shorts.get("note"):
            continue  # ya se intentó y el vídeo no da para Shorts
        elif job and job.status == "failed" and not count:
            step = "failed"
        elif not count:
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
