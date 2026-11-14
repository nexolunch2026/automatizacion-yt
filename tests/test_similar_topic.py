"""Aviso de tema repetido: si en el mismo canal ya hay un vídeo sobre el mismo protagonista,
la página del vídeo lo dice (sin impedir nada)."""

from app import coach
from app.db import SessionLocal
from app.models import Channel, Project
from tests.test_projects import create_channel, project_data


def test_subject_words_use_the_part_before_the_colon():
    assert coach.subject_words("La historia de Gareth Bale: del Southampton al Madrid") == {
        "gareth",
        "bale",
    }
    assert coach.subject_words("Coca-Cola contra Pepsi") == {"cocacola", "pepsi"}
    assert coach.subject_words("LG: la caída") == {"lg"}
    assert coach.subject_words("El Real Madrid") == {"madrid"}  # «Real» es genérico
    assert coach.subject_words("la caída de una marca") == set()
    assert coach.subject_words("") == set()


def make(client, topic, title=""):
    client.post("/proyectos/nuevo", data=project_data(topic=topic, title=title or topic))


def test_similar_projects_same_channel_only(logged_in):
    create_channel(logged_in)
    make(logged_in, "El ascenso y la caída de Gareth Bale")  # 1
    make(logged_in, "Real Madrid: la era de los galácticos")  # 2
    make(logged_in, "Pepsi: la guerra de las colas")  # 3
    make(logged_in, "La historia de Gareth Bale: del Southampton al Real Madrid")  # 4
    make(logged_in, "Coca-Cola contra Pepsi")  # 5
    make(logged_in, "una idea sin nombres propios")  # 6
    with SessionLocal() as db:
        bale = db.get(Project, 4)
        assert [p.id for p in coach.similar_projects(db, bale)] == [1]  # no Real Madrid
        assert [p.id for p in coach.similar_projects(db, db.get(Project, 5))] == [3]
        assert coach.similar_projects(db, db.get(Project, 6)) == []
        assert [p.id for p in coach.similar_projects(db, db.get(Project, 3))] == [5]
        other = Channel(name="ModoOffside", niche="fútbol", created_by=1)
        db.add(other)
        db.commit()
        db.get(Project, 1).channel_id = other.id  # en otro canal ya no cuenta
        db.commit()
        assert coach.similar_projects(db, bale) == []


def test_project_page_shows_the_notice(logged_in):
    create_channel(logged_in)
    make(logged_in, "Kodak: la cámara digital que nadie quiso", "Kodak y su gran error")
    make(logged_in, "Kodak: el ascenso y la caída")
    page = logged_in.get("/proyectos/2").text
    assert "Ojo, tema repetido" in page and "«Kodak y su gran error»" in page
    assert "Ojo, tema repetido" not in logged_in.get("/proyectos/99999").text


def test_no_false_alarms_for_wider_or_generic_titles(logged_in):
    create_channel(logged_in)
    make(logged_in, "Nike: la historia", "Nike: la historia")  # 1
    make(logged_in, "Nike, Adidas y Puma: la guerra de las zapatillas")  # 2
    make(logged_in, "Banco Santander: auge", "Banco Santander: auge")  # 3
    make(logged_in, "Banco Popular: la caída", "Banco Popular: la caída")  # 4
    with SessionLocal() as db:
        assert coach.similar_projects(db, db.get(Project, 1)) == []  # 2 nombres más: otro tema
        assert coach.similar_projects(db, db.get(Project, 3)) == []  # «Banco» no cuenta
