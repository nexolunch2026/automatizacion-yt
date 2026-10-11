from app import playlists
from app.db import SessionLocal
from app.models import StageResult, Video
from app.profile import save as save_profile
from tests.test_projects import create_channel, project_data


def projects(client, n):
    create_channel(client)
    for _ in range(n):
        client.post("/proyectos/nuevo", data=project_data())


def video(db, vid, title, published, project_id=None, structure=""):
    db.add(Video(video_id=vid, title=title, published=published, project_id=project_id))
    if project_id and structure:
        db.add(
            StageResult(project_id=project_id, stage="script", data={"structure_name": structure})
        )


def test_needs_two_videos(logged_in):
    with SessionLocal() as db:
        assert playlists.suggest(db) == []
        video(db, "a", "Kodak", "2026-09-01")
        db.commit()
        assert playlists.suggest(db) == []


def test_groups_by_script_format(logged_in):
    projects(logged_in, 4)
    with SessionLocal() as db:
        save_profile(db, "Simón", "Anatomía De Una Marca", "marcas", "España")
        video(db, "a", "Kodak", "2026-09-01", 1, "Ascenso y caída")
        video(db, "b", "Coca-Cola contra Pepsi", "2026-09-05", 2, "Rivalidad")
        video(db, "c", "Nokia", "2026-09-10", 3, "Ascenso y caída")
        video(db, "d", "Sin proyecto", "2026-09-12")
        db.commit()
        found = playlists.suggest(db)
    assert found[0]["title"] == "Ascenso y caída | Anatomía De Una Marca"
    assert found[0]["videos"] == ["Kodak", "Nokia"]  # del más viejo al más nuevo
    assert "2 vídeos de Anatomía De Una Marca" in found[0]["description"]
    # La rivalidad solo tiene un vídeo: va con los demás, para que no se pierda ninguno.
    assert found[1]["title"] == "Más historias | Anatomía De Una Marca"
    assert found[1]["videos"] == ["Coca-Cola contra Pepsi", "Sin proyecto"]


def test_without_formats_one_list_with_everything(logged_in):
    with SessionLocal() as db:
        video(db, "z", "Sin fecha", "")
        video(db, "a", "Kodak", "2026-09-01")
        video(db, "b", "Nokia", "2026-09-10")
        db.commit()
        found = playlists.suggest(db)
    assert [f["title"] for f in found] == ["Todas las historias"]
    assert found[0]["videos"] == ["Kodak", "Nokia", "Sin fecha"]  # sin fecha, al final


def test_card_on_the_performance_page(logged_in):
    page = logged_in.get("/rendimiento").text
    assert "Listas de reproducción" not in page
    with SessionLocal() as db:
        video(db, "a", "Kodak", "2026-09-01")
        video(db, "b", "Nokia", "2026-09-10")
        db.commit()
    page = logged_in.get("/rendimiento").text
    assert "Listas de reproducción" in page and 'data-copy="lista-desc-1"' in page
