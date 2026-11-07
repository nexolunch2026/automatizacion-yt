"""PREPARAR EL ESTRENO: lo que pasa entre «el vídeo está montado» y «sale en YouTube».

- Aprobaciones: cada uno de vosotros pulsa «Aprobado» después de ver el vídeo. Si el vídeo
  cambia después (otro montaje), las aprobaciones se borran: hay que volver a verlo.
- Calendario fijo: vídeos largos martes, jueves y sábado; Shorts lunes, miércoles, viernes y
  domingo; todo a las 18:00. Se propone la fecha solo y se puede cambiar.
- La claqueta: la lista de lo que lleva el vídeo (vídeo, miniatura, textos, subtítulos,
  Shorts, datos comprobados) y si algo se quedó viejo.
- Carpeta para subir: lo deja todo en `FacelessStudio/subir/<vídeo>` como las carpetas
  SUBIR_ que se hacían a mano.
"""

import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.media import project_dir
from app.models import Project, StageResult, User

STAGE = "estreno"
HOUR = "18:00"
LONG_DAYS = (1, 3, 5)  # martes, jueves, sábado (lunes = 0)
SHORT_DAYS = (0, 2, 4, 6)
DAY_NAMES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


# ---------------------------------------------------------------- datos guardados


def _row(db: Session, project_id: int) -> StageResult | None:
    return db.scalar(
        select(StageResult).where(StageResult.project_id == project_id, StageResult.stage == STAGE)
    )


def get(db: Session, project_id: int) -> dict:
    data = dict((_row(db, project_id) or StageResult(data={})).data or {})
    render = _render(db, project_id)
    # Si el vídeo se volvió a montar después de aprobarlo, las aprobaciones ya no valen.
    if data.get("render_file") and render and data["render_file"] != render:
        data["approvals"] = {}
    return data


def _save(db: Session, project_id: int, data: dict) -> None:
    row = _row(db, project_id)
    if row is None:
        db.add(StageResult(project_id=project_id, stage=STAGE, data=data))
    else:
        row.data = data
    db.commit()


def _render(db: Session, project_id: int) -> str:
    """Una «huella» del último montaje: archivo + fecha (cambia si se vuelve a montar)."""
    from app.pipeline.monetization import last_render

    render = last_render({"edit": jobs.get_result(db, project_id, "edit") or {}})
    path = project_dir(project_id) / render["file"] if render.get("file") else None
    if path is None or not path.exists():
        return ""
    return f"{render['file']}@{int(path.stat().st_mtime)}"


def approve(db: Session, project_id: int, user: User, yes: bool = True) -> dict:
    data = get(db, project_id)
    approvals = dict(data.get("approvals") or {})
    if yes:
        approvals[str(user.id)] = datetime.now().isoformat(timespec="minutes")
    else:
        approvals.pop(str(user.id), None)
    data.update(approvals=approvals, render_file=_render(db, project_id))
    _save(db, project_id, data)
    return data


def set_date(db: Session, project_id: int, day: date | None) -> dict:
    data = get(db, project_id)
    data["date"] = day.isoformat() if day else None
    _save(db, project_id, data)
    return data


def team(db: Session) -> list[dict]:
    """Las personas que aprueban (las cuentas del programa)."""
    from app.settings_store import get_setting

    users = db.scalars(select(User).order_by(User.id)).all()
    out = []
    for u in users:
        name = (get_setting(db, f"display_name:{u.id}") or "").strip() or _pretty(u.username)
        out.append({"id": u.id, "name": name, "initial": name[:1].upper()})
    return out


def _pretty(username: str) -> str:
    """«sceballos28» → «Sceballos». Los nombres de usuario no siempre son bonitos."""
    letters = re.sub(r"[\d_.\-]+", " ", username or "").strip().split()
    return (letters[0] if letters else username or "?").capitalize()


def approvals_view(db: Session, project_id: int) -> list[dict]:
    given = get(db, project_id).get("approvals") or {}
    out = []
    for person in team(db):
        when = given.get(str(person["id"]))
        out.append({**person, "ok": bool(when), "when": _when(when) if when else ""})
    return out


def _when(iso: str) -> str:
    moment = datetime.fromisoformat(iso)
    today = date.today()
    if moment.date() == today:
        return f"hoy, {moment:%H:%M}"
    if moment.date() == today - timedelta(days=1):
        return f"ayer, {moment:%H:%M}"
    return f"{moment.day} {MONTHS[moment.month - 1]}, {moment:%H:%M}"


# ---------------------------------------------------------------- calendario


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def is_ready(db: Session, project: Project) -> bool:
    from app import coach

    if project.status == "Publicado" or project.id in coach._published_ids(db):
        return False
    return bool(_render(db, project.id))


def week(db: Session, projects: list[Project], start: date, today: date | None = None) -> list:
    """Los 7 días de la semana con lo que sale cada día (lo elegido y lo propuesto)."""
    today = today or date.today()
    days = [start + timedelta(days=i) for i in range(7)]
    longs: dict[date, list] = {d: [] for d in days}
    people = len(team(db)) or 1
    ready = [p for p in projects if is_ready(db, p)]
    chosen = {p.id: get(db, p.id).get("date") for p in ready}
    for p in ready:
        when = chosen.get(p.id)
        if when and date.fromisoformat(when) in longs:
            longs[date.fromisoformat(when)].append((p, False))
    # Los que no tienen fecha: al siguiente día de vídeo largo libre de su canal.
    pending = sorted(
        (p for p in ready if not chosen.get(p.id)),
        key=lambda p: (-len(get(db, p.id).get("approvals") or {}), p.id),
    )
    for p in pending:
        for d in days:
            if (
                d.weekday() in LONG_DAYS
                and d >= today
                and not any(q.channel_id == p.channel_id for q, _ in longs[d])
            ):
                longs[d].append((p, True))
                break
    out = []
    for d in days:
        long_day = d.weekday() in LONG_DAYS
        items = []
        for p, proposed in longs[d]:
            approvals = len(get(db, p.id).get("approvals") or {})
            items.append(
                {
                    "project": p,
                    "proposed": proposed,
                    "state": "ok" if approvals >= people else ("wait" if approvals else "new"),
                    "label": "Listo" if approvals >= people else (
                        "Falta uno" if approvals else "Sin ver"
                    ),
                }
            )  # fmt: skip
        out.append(
            {
                "date": d,
                "name": DAY_NAMES[d.weekday()],
                "kind": "Vídeos largos" if long_day else "Shorts",
                "long": long_day,
                "today": d == today,
                "items": items,
            }
        )
    # Shorts: los de cada vídeo largo, en los días de Shorts que siguen a su estreno.
    for day in out:
        if not day["long"]:
            continue
        for item in day["items"]:
            shorts = (jobs.get_result(db, item["project"].id, "shorts") or {}).get("shorts", [])
            free = [x for x in out if not x["long"] and x["date"] > day["date"]]
            for n, (slot, _short) in enumerate(zip(free, shorts, strict=False), 1):
                slot["items"].append(
                    {"project": item["project"], "short": n, "proposed": True,
                     "state": item["state"], "label": f"Short {n}"}
                )  # fmt: skip
    return out


def holes(db: Session, day: dict, channels: list) -> list:
    """Canales sin vídeo en un día de vídeo largo."""
    if not day["long"]:
        return []
    used = {i["project"].channel_id for i in day["items"]}
    return [c for c in channels if c.id not in used]


# ---------------------------------------------------------------- la claqueta


def checklist(db: Session, project: Project) -> list[dict]:
    """Lo que lleva el vídeo, en orden. Cada línea: {label, ok, detail, link}."""
    from app import factcheck
    from app.pipeline.monetization import last_render

    pid = project.id
    folder = project_dir(pid)
    render = last_render({"edit": jobs.get_result(db, pid, "edit") or {}})
    seconds = int(round(float(render.get("seconds") or 0)))
    thumb = jobs.get_result(db, pid, "thumbnail") or {}
    seo = jobs.get_result(db, pid, "publish") or {}
    shorts = (jobs.get_result(db, pid, "shorts") or {}).get("shorts", [])
    facts = jobs.get_result(db, pid, factcheck.STAGE)
    stale = jobs.stale_stages(db, pid)
    to_check = (facts or {}).get("summary", {}).get("corregir", 0)
    selected = thumb.get("selected")
    variants = thumb.get("variants") or []
    chosen_text = (
        variants[selected]["text"] if isinstance(selected, int) and selected < len(variants) else ""
    )
    lines = [
        {"label": "Vídeo montado", "ok": bool(render.get("file")) and "edit" not in stale,
         "detail": f"{seconds // 60}:{seconds % 60:02d}" if seconds else "falta montarlo",
         "link": "video"},
        {"label": "Miniatura elegida", "ok": isinstance(selected, int) and "thumbnail" not in stale,
         "detail": f"«{chosen_text.replace('|', '/')}»" if chosen_text else "elige una",
         "link": "miniatura"},
        {"label": "Título, descripción y fuentes", "ok": bool(seo) and "publish" not in stale,
         "detail": (seo.get("titles") or [""])[0][:42] if seo else "faltan los textos",
         "link": "publicacion"},
        {"label": "Subtítulos", "ok": (folder / "video" / "subtitulos.srt").exists(),
         "detail": "listos" if (folder / "video" / "subtitulos.srt").exists() else "faltan",
         "link": "video"},
        {"label": "Shorts", "ok": bool(shorts) and "shorts" not in stale,
         "detail": f"{len(shorts)} listos" if shorts else "faltan", "link": "shorts"},
        {"label": "Datos comprobados", "ok": bool(facts) and not to_check,
         "detail": (f"{to_check} para revisar" if to_check else
                    f"{facts['summary'].get('confirmado', 0)} confirmados") if facts
         else "sin comprobar", "link": "guion#datos"},
    ]  # fmt: skip
    return lines


# ---------------------------------------------------------------- carpeta para subir


def upload_root() -> Path:
    from app.storage import home_dir

    return home_dir() / "subir"


def prepare_folder(db: Session, project: Project) -> Path:
    """Copia todo lo necesario para subirlo a YouTube en una carpeta (no borra nada)."""
    from app.pipeline.monetization import last_render
    from app.upload_pack import STEPS, slug, texts

    pid = project.id
    folder = project_dir(pid)
    render = last_render({"edit": jobs.get_result(db, pid, "edit") or {}})
    video = folder / render["file"] if render.get("file") else None
    if video is None or not video.exists():
        raise ValueError("Primero hay que montar el vídeo.")
    out = upload_root() / slug(project.title)
    (out / "shorts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, out / "video.mp4")
    srt = folder / "video" / "subtitulos.srt"
    if srt.exists():
        shutil.copy2(srt, out / "subtitulos.srt")
    thumb = jobs.get_result(db, pid, "thumbnail") or {}
    variants = thumb.get("variants") or []
    selected = thumb.get("selected")
    if variants:
        index = selected if isinstance(selected, int) and 0 <= selected < len(variants) else 0
        image = folder / "miniaturas" / variants[index]["file"]
        if image.exists():
            shutil.copy2(image, out / "miniatura.jpg")
    seo = jobs.get_result(db, pid, "publish") or {}
    script = jobs.get_result(db, pid, "script") or {}
    (out / "textos.txt").write_text(texts(project, seo, script), encoding="utf-8")
    (out / "LEEME.txt").write_text(STEPS, encoding="utf-8")
    for n, short in enumerate((jobs.get_result(db, pid, "shorts") or {}).get("shorts", []), 1):
        for key, name in (("file", f"short-{n}.mp4"), ("cover", f"short-{n}-portada.jpg")):
            path = folder / short[key] if short.get(key) else None
            if path is not None and path.exists():
                shutil.copy2(path, out / "shorts" / name)
        (out / "shorts" / f"short-{n}.txt").write_text(
            f"TÍTULO\n{short.get('title', '')}\n\nDESCRIPCIÓN\n{short.get('description', '')}\n",
            encoding="utf-8",
        )
    data = get(db, pid)
    data["folder"] = str(out)
    _save(db, pid, data)
    return out


def nice_date(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.day} · {HOUR}"


def next_slots(db: Session, project: Project, today: date | None = None, count: int = 3):
    """Los próximos días de vídeo largo, marcando los que ya tiene otro vídeo del canal."""
    today = today or date.today()
    taken = {}
    for other in db.scalars(select(Project).where(Project.channel_id == project.channel_id)):
        if other.id != project.id and (when := get(db, other.id).get("date")):
            taken[when] = other.title
    slots, day = [], today
    while len(slots) < count:
        if day.weekday() in LONG_DAYS:
            slots.append({"date": day, "name": DAY_NAMES[day.weekday()], "busy": taken.get(
                day.isoformat())})  # fmt: skip
        day += timedelta(days=1)
    return slots
