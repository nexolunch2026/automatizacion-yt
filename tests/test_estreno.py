"""Rediseño «Estreno»: aprobaciones, calendario fijo, claqueta y carpeta para subir."""

from datetime import date

from app import estreno, jobs
from app.db import SessionLocal
from app.models import Project, User
from tests.test_thumbnail import make_video_project


def test_calendar_days_and_slots(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    friday = date(2026, 11, 6)
    with SessionLocal() as db:
        project = db.get(Project, 1)
        assert estreno.is_ready(db, project)  # montado y sin publicar
        days = estreno.week(db, [project], friday, today=friday)
        long_days = [d["name"] for d in days if d["long"]]
        assert long_days == ["Sábado", "Martes", "Jueves"]
        # Sin fecha: se propone el primer día de vídeo largo libre (el sábado 7)
        saturday = next(d for d in days if d["date"] == date(2026, 11, 7))
        assert saturday["items"][0]["proposed"] and saturday["items"][0]["label"] == "Sin ver"
        # Con fecha elegida, va ese día y deja de ser propuesta
        estreno.set_date(db, 1, date(2026, 11, 10))
        days = estreno.week(db, [project], friday, today=friday)
        tuesday = next(d for d in days if d["date"] == date(2026, 11, 10))
        assert tuesday["items"][0]["project"].id == 1 and not tuesday["items"][0]["proposed"]
        slots = estreno.next_slots(db, project, today=friday)
        assert [s["name"] for s in slots] == ["Sábado", "Martes", "Jueves"]


def test_approvals_reset_when_video_is_remade(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, 1)
        estreno.approve(db, 1, user)
        assert [p["ok"] for p in estreno.approvals_view(db, 1)] == [True]
        # Otro montaje (el archivo cambia): hay que volver a verlo
        data = estreno.get(db, 1)
        data["render_file"] = "video/otro.mp4@1"
        estreno._save(db, 1, data)
        assert [p["ok"] for p in estreno.approvals_view(db, 1)] == [False]


def test_launch_page_buttons(logged_in, monkeypatch, tmp_path):
    make_video_project(logged_in, monkeypatch)
    page = logged_in.get("/proyectos/1/estreno").text
    assert "Preparar carpeta para subir" in page and "Lo he visto: aprobado" in page
    assert "Vídeo montado" in page and "Datos comprobados" in page

    page = logged_in.post("/proyectos/1/estreno/aprobar", data={"yes": "1"}).text
    assert "Aprobado: queda apuntado a tu nombre" in page and "Quitar mi aprobación" in page

    day = estreno.next_slots(SessionLocal(), SessionLocal().get(Project, 1))[0]["date"]
    page = logged_in.post("/proyectos/1/estreno/fecha", data={"day": day.isoformat()}).text
    assert "Fecha guardada" in page and estreno.nice_date(day) in page
    assert logged_in.post("/proyectos/1/estreno/fecha", data={"day": "mañana"}).status_code == 400

    monkeypatch.setattr(estreno, "upload_root", lambda: tmp_path / "subir")
    page = logged_in.post("/proyectos/1/estreno/carpeta").text
    assert "Carpeta para subir lista" in page
    folder = next((tmp_path / "subir").iterdir())
    assert (folder / "video.mp4").exists() and (folder / "textos.txt").exists()
    assert (folder / "LEEME.txt").exists()


def test_home_shows_premiere_week_and_posters(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        estreno.approve(db, 1, db.get(User, 1))
    page = logged_in.get("/").text
    assert "Próximo estreno" in page and "Preparar el estreno" in page
    assert "Próximos 7 días" in page and "x-film" in page
    assert "visto bueno" in page


def test_display_names(logged_in):
    from app.settings_store import set_setting

    with SessionLocal() as db:
        assert estreno._pretty("sceballos28") == "Sceballos"
        set_setting(db, "display_name:1", "Simón")
        assert estreno.team(db)[0]["name"] == "Simón"


def test_checklist_counts_missing_facts(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        lines = estreno.checklist(db, db.get(Project, 1))
        facts = next(line for line in lines if line["label"] == "Datos comprobados")
        assert not facts["ok"] and facts["detail"] == "sin comprobar"
        assert jobs.get_result(db, 1, "edit")
