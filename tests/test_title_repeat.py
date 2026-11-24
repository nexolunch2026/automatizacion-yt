"""Título repetido en el canal: el control de calidad avisa si el título es casi igual al de
otro vídeo ya publicado del mismo canal (competirían en la búsqueda)."""

from app.db import SessionLocal
from app.models import Channel, Project, StageResult
from app.pipeline.monetization import _repeated_title_check, project_review
from tests.test_projects import create_channel, project_data
from tests.test_related_links import add_video


def check(db, project_id=1):
    checks = project_review(db, db.get(Project, project_id))["checks"]
    return next((c for c in checks if c["key"] == "title_repeat"), None)


def test_almost_same_title_is_warned(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak 2", title="Kodak 2"))
    with SessionLocal() as db:
        assert check(db) is None  # aún no hay nada publicado con que comparar
        add_video(db, "kodakviejoo", "La caída de Kodak: el error de la cámara digital", 2)
        publish = {"titles": ["La caída de Kodak: el error de la cámara digital!"]}
        db.add(StageResult(project_id=1, stage="publish", data=publish))
        db.commit()
        warned = check(db)
        assert warned["status"] == "warn"
        assert "«La caída de Kodak: el error de la cámara digital»" in warned["detail"]
        db.query(StageResult).filter_by(project_id=1).one().data = {
            "titles": ["Nokia: el gigante que no vio venir el iPhone"]
        }
        db.commit()
        assert check(db)["status"] == "ok"


def test_other_channels_and_shorts_do_not_count(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Bale", title="Gareth Bale"))
    with SessionLocal() as db:
        db.add(Channel(name="ModoOffside", niche="fútbol", created_by=1))
        db.commit()
        db.add(Project(channel_id=2, title="Gareth Bale", topic="Bale", duration="10–15 min",
                       language="Español", video_type="Documental", automation_mode="manual",
                       created_by=1))  # fmt: skip
        db.commit()
        add_video(db, "baleotrocan", "Gareth Bale", 2)  # del otro canal
        add_video(db, "baleshortaa", "Gareth Bale #shorts", None)  # un Short
        assert check(db) is None


def test_the_rule_itself():
    published = {"_channel_titles": ["Nokia: la caída", "Kodak y la foto digital"]}
    assert _repeated_title_check(published, "") == []
    assert _repeated_title_check(published, "¡¿…?!") == []  # sin letras: nada que comparar
    assert _repeated_title_check(published, "NOKIA — la caída")[0]["status"] == "warn"
    assert _repeated_title_check(published, "Polaroid: el final")[0]["status"] == "ok"
    assert _repeated_title_check({}, "Nokia: la caída") == []
    series = {"_channel_titles": ["Kodak", "Nokia: la historia completa, parte 1"]}
    assert _repeated_title_check(series, "Kodak 2")[0]["status"] == "ok"  # corto: solo igual
    assert _repeated_title_check(series, "kodak")[0]["status"] == "warn"
    part2 = _repeated_title_check(series, "Nokia: la historia completa, parte 2")
    assert part2[0]["status"] == "ok"  # una serie, no un repetido


def test_a_failure_is_said(logged_in, monkeypatch):
    from app.pipeline import end_screen

    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))

    def boom(db, project):
        raise RuntimeError("fallo")

    monkeypatch.setattr(end_screen, "channel_long_videos", boom)
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="publish", data={"titles": ["Kodak"]}))
        db.commit()
        assert check(db)["title"] == "No se pudo comparar el título"


def test_own_unlinked_upload_is_not_a_repeat(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        title = "La caída de Kodak: el error de la cámara digital"
        db.add(StageResult(project_id=1, stage="publish", data={"titles": [title]}))
        db.commit()
        add_video(db, "recienbido1", title, None)  # recién subido, aún sin enlazar
        assert check(db) is None  # no hay otro vídeo con el que comparar
