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


def test_dashboard_shows_summary_thumbnails_and_active_menu(logged_in):
    from tests.test_strategy_script import make_project

    make_project(logged_in)
    page = logged_in.get("/").text
    assert "En marcha" in page and "Nota media de calidad" in page
    assert 'href="/" class="active"' in page  # el menú marca la página actual
    assert 'href="/canales" class="active"' in logged_in.get("/canales").text


def test_page_titles_and_icon(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="La caída de Nokia", title="Nokia"))
    assert "<title>Nokia · Faceless Studio</title>" in logged_in.get("/proyectos/1").text
    assert "<title>Canales · Faceless Studio</title>" in logged_in.get("/canales").text
    assert "<title>Faceless Studio</title>" in logged_in.get("/").text
    assert "favicon.svg" in logged_in.get("/").text
    assert logged_in.get("/static/favicon.svg").status_code == 200


def test_global_status_pill(logged_in):
    from app import jobs
    from app.db import SessionLocal

    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    assert logged_in.get("/estado-global").json() == {"count": 0}
    with SessionLocal() as db:
        jobs.enqueue(db, 1, "research")
    status = logged_in.get("/estado-global").json()
    assert status["count"] == 1 and status["project_id"] == 1 and status["running"] is False
    assert 'id="busy"' in logged_in.get("/").text


def test_quick_start_creates_and_researches(logged_in):
    from app import jobs
    from app.db import SessionLocal
    from app.models import Project

    create_channel(logged_in)
    assert "¿Sobre qué hacemos el próximo vídeo?" in logged_in.get("/").text
    r = logged_in.post("/rapido", data={"topic": "  top 10 marcas que desaparecieron "})
    assert r.url.path == "/proyectos/1"
    with SessionLocal() as db:
        project = db.get(Project, 1)
        assert project.topic == "top 10 marcas que desaparecieron"
        assert project.video_format == "lista"
        assert jobs.latest_jobs(db, 1)["research"].status == "queued"
    assert logged_in.post("/rapido", data={"topic": "  "}).url.path == "/"
