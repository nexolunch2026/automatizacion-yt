def create_channel(client, name="Misterios"):
    return client.post(
        "/canales", data={"name": name, "niche": "casos raros", "language": "Español"}
    )


def project_data(**overrides):
    data = {
        "channel_id": 1,
        "topic": "Empresas que desaparecieron misteriosamente",
        "title": "",
        "duration": "5–10 min",
        "language": "Español",
        "video_type": "Misterio",
        "automation_mode": "asistido",
    }
    data.update(overrides)
    return data


def test_new_video_asks_for_channel_first(logged_in):
    r = logged_in.get("/proyectos/nuevo", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/canales?primero=1"


def test_create_channel(logged_in):
    r = create_channel(logged_in)
    assert r.status_code == 200
    assert "Misterios" in r.text

    r = logged_in.post("/canales", data={"name": "  ", "language": "Español"})
    assert r.status_code == 400


def test_create_project_and_see_it(logged_in):
    create_channel(logged_in)
    r = logged_in.post("/proyectos/nuevo", data=project_data())
    assert r.status_code == 200
    assert "Empresas que desaparecieron misteriosamente" in r.text
    assert "Disponible" in r.text
    assert "Próximamente" in r.text

    dashboard = logged_in.get("/").text
    assert "Empresas que desaparecieron misteriosamente" in dashboard
    assert "Idea" in dashboard


def test_create_project_validation(logged_in):
    create_channel(logged_in)
    r = logged_in.post("/proyectos/nuevo", data=project_data(topic="  "))
    assert r.status_code == 400
    assert "Escribe la idea" in r.text

    r = logged_in.post("/proyectos/nuevo", data=project_data(video_type="Inventado"))
    assert r.status_code == 400

    r = logged_in.post("/proyectos/nuevo", data=project_data(channel_id=99))
    assert r.status_code == 400


def test_filter_dashboard_by_channel(logged_in):
    create_channel(logged_in, "Misterios")
    create_channel(logged_in, "Historia")
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Tema de misterio", channel_id=1))
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Tema de historia", channel_id=2))

    page = logged_in.get("/?canal=2").text
    assert "Tema de historia" in page
    assert "Tema de misterio" not in page


def test_delete_project(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    r = logged_in.post("/proyectos/1/borrar")
    assert r.status_code == 200
    assert logged_in.get("/proyectos/1").status_code == 404


def brand_channel(channel_id=1):
    """Pone el canal en el nicho de marcas (la ficha de siempre: «La lección de la marca»)."""
    from app.db import SessionLocal
    from app.models import Channel

    with SessionLocal() as db:
        db.get(Channel, channel_id).niche = "historias de marcas y empresas"
        db.commit()
