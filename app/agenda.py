"""Lo que JARVIS sabe de tu día: tus tareas, las del estudio, el tiempo y el ordenador.

- Tareas personales: las que le dictas («anota: comprar micrófono»).
- Tareas del estudio: salen solas de los proyectos (elegir enfoque, revisar un borrador,
  subir un vídeo a YouTube, mirar un error).
"""

import logging
import shutil
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.config import DATA_DIR
from app.models import Job, Project
from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


# ---------------------------------------------------------------- tareas personales


def _load(db: Session) -> list[dict]:
    import json

    raw = get_setting(db, "jarvis_tasks")
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def _save(db: Session, tasks: list[dict]) -> None:
    import json

    set_setting(db, "jarvis_tasks", json.dumps(tasks, ensure_ascii=False))


def personal_tasks(db: Session, now: datetime | None = None) -> list[dict]:
    """Pendientes y las hechas hoy (las de días anteriores ya terminadas se ocultan)."""
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    return [t for t in _load(db) if not t.get("done") or t.get("done") == today]


def add_task(db: Session, text: str) -> dict:
    tasks = _load(db)
    task = {"id": max((t["id"] for t in tasks), default=0) + 1, "text": text[:200], "done": ""}
    tasks.append(task)
    _save(db, tasks)
    return task


def find_task(db: Session, query: str) -> dict | None:
    """Por número («la 2») o por parte del texto («micrófono»)."""
    from app.assistant import normalize

    pending = [t for t in _load(db) if not t.get("done")]
    query = query.strip()
    digits = "".join(ch for ch in query if ch.isdigit())
    if digits and len(digits) <= 3:
        index = int(digits) - 1
        if 0 <= index < len(pending):
            return pending[index]
    words = [w for w in normalize(query).split() if len(w) > 2]
    best, score = None, 0
    for task in pending:
        text = normalize(task["text"])
        hits = sum(1 for w in words if w in text)
        if hits > score:
            best, score = task, hits
    return best


def complete_task(db: Session, task_id: int, now: datetime | None = None) -> None:
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    tasks = _load(db)
    for task in tasks:
        if task["id"] == task_id:
            task["done"] = today
    _save(db, tasks)


def delete_task(db: Session, task_id: int) -> None:
    _save(db, [t for t in _load(db) if t["id"] != task_id])


# ---------------------------------------------------------------- tareas del estudio


def studio_tasks(db: Session) -> list[dict]:
    """Lo que el estudio necesita de ti ahora mismo."""
    found = []
    projects = db.scalars(select(Project).order_by(Project.id.desc()).limit(30)).all()
    for project in projects:
        if project.status == "Publicado":
            continue
        latest = jobs.latest_jobs(db, project.id)
        if any(j.active for j in latest.values()):
            continue  # está trabajando; no te pide nada
        failed = [s for s, j in latest.items() if j.status == "failed"]
        strategy = jobs.get_result(db, project.id, "strategy")
        edit = jobs.get_result(db, project.id, "edit") or {}
        renders = edit.get("renders", {})
        link = f"/proyectos/{project.id}"
        if failed:
            text = f"Revisar el error de «{project.title}»"
            found.append({"text": text, "kind": "error", "link": link})
        elif strategy and not strategy.get("selected") and strategy.get("concepts"):
            text = f"Elegir el enfoque de «{project.title}»"
            found.append({"text": text, "kind": "choice", "link": f"{link}/estrategia"})
        elif "final" in renders:
            text = f"Subir «{project.title}» a YouTube"
            found.append({"text": text, "kind": "upload", "link": f"{link}/publicacion"})
        elif "preview" in renders:
            text = f"Revisar el borrador de «{project.title}»"
            found.append({"text": text, "kind": "review", "link": f"{link}/video"})
    return found


def production(db: Session) -> list[dict]:
    """Lo que se está fabricando ahora (para la pantalla)."""
    from app.models import STAGES

    rows = db.scalars(
        select(Job).where(Job.status.in_(("queued", "running"))).order_by(Job.id)
    ).all()
    items = []
    for job in rows:
        project = db.get(Project, job.project_id)
        if project:
            items.append(
                {
                    "project": project.title,
                    "stage": STAGES.get(job.stage, job.stage),
                    "progress": job.progress if job.status == "running" else 0,
                    "message": job.message if job.status == "running" else "En cola",
                    "running": job.status == "running",
                }
            )
    return items


# ---------------------------------------------------------------- tiempo y ordenador

WEATHER_CODES = {
    0: "despejado",
    1: "casi despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "con niebla",
    48: "con niebla",
    51: "con llovizna",
    53: "con llovizna",
    55: "con llovizna",
    61: "con lluvia ligera",
    63: "con lluvia",
    65: "con lluvia fuerte",
    80: "con chubascos",
    81: "con chubascos",
    82: "con chubascos fuertes",
    95: "con tormenta",
    96: "con tormenta",
    99: "con tormenta",
}
_weather_cache: dict[str, tuple[float, dict | None]] = {}


def fetch_weather(city: str) -> dict | None:
    """El tiempo de hoy con Open-Meteo (gratis, sin clave). Se reemplaza en los tests."""
    with httpx.Client(timeout=10) as client:
        found = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "es"},
        ).json()
        places = found.get("results") or []
        if not places:
            return None
        place = places[0]
        data = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
        ).json()
    current, daily = data.get("current", {}), data.get("daily", {})
    return {
        "city": place.get("name", city),
        "temp": round(current.get("temperature_2m", 0)),
        "sky": WEATHER_CODES.get(current.get("weather_code"), ""),
        "max": round((daily.get("temperature_2m_max") or [0])[0]),
        "min": round((daily.get("temperature_2m_min") or [0])[0]),
        "rain": (daily.get("precipitation_probability_max") or [0])[0] or 0,
    }


def weather(db: Session) -> dict | None:
    city = (get_setting(db, "jarvis_city") or "").strip()
    if not city:
        return None
    cached = _weather_cache.get(city)
    if cached and time.time() - cached[0] < 1800:
        return cached[1]
    try:
        data = fetch_weather(city)
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        log.warning("No se pudo consultar el tiempo: %s", exc)
        data = None
    _weather_cache[city] = (time.time(), data)
    return data


def system() -> dict:
    """Cómo está el ordenador (procesador, memoria y disco)."""
    disk = shutil.disk_usage(DATA_DIR)
    info = {"disk_free_gb": round(disk.free / 1e9, 1), "disk": round(disk.used / disk.total * 100)}
    try:
        import psutil

        info["cpu"] = round(psutil.cpu_percent(interval=None))
        info["ram"] = round(psutil.virtual_memory().percent)
    except ImportError:
        info["cpu"] = info["ram"] = None
    return info


# ---------------------------------------------------------------- resumen hablado


def greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Buenos días"
    if now.hour < 19:
        return "Buenas tardes"
    return "Buenas noches"


def spoken_date(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]} {now.day} de {MONTHS[now.month - 1]}"


def spoken_time(now: datetime) -> str:
    return f"{now.hour}:{now.minute:02}"


def briefing_text(db: Session, now: datetime | None = None, name: str = "") -> str:
    """El resumen que JARVIS dice al despertar."""
    now = now or datetime.now()
    parts = [
        f"{greeting(now)}{', ' + name if name else ''}. Hoy es {spoken_date(now)} "
        f"y son las {spoken_time(now)}."
    ]
    sky = weather(db)
    if sky:
        rain = f" Probabilidad de lluvia: {sky['rain']} por ciento." if sky["rain"] >= 30 else ""
        parts.append(
            f"En {sky['city']} hace {sky['temp']} grados, {sky['sky']}; máxima de "
            f"{sky['max']}.{rain}"
        )
    making = production(db)
    if making:
        running = next((m for m in making if m["running"]), making[0])
        parts.append(
            f"En producción: {running['project']}, en {running['stage'].lower()}, "
            f"al {running['progress']} por ciento."
        )
    studio = studio_tasks(db)
    mine = [t for t in personal_tasks(db, now) if not t.get("done")]
    total = len(studio) + len(mine)
    if total == 0:
        parts.append("No tienes tareas pendientes. ¿Hacemos un vídeo nuevo?")
    else:
        parts.append(f"Tienes {total} tarea{'s' if total != 1 else ''} para hoy.")
        for task in (studio + mine)[:5]:
            parts.append(f"{task['text']}.")
    return " ".join(parts)
