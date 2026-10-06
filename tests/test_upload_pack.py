import io
import zipfile

from tests.test_thumbnail import make_video_project


def test_upload_pack_has_everything(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    logged_in.post("/proyectos/1/etapas/publish")
    from tests.test_strategy_script import run_all

    run_all()
    page = logged_in.get("/proyectos/1/publicacion").text
    assert "Descargar todo para subir" in page
    r = logged_in.get("/proyectos/1/paquete")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "subida-" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as pack:
        names = set(pack.namelist())
        texts = pack.read("textos.txt").decode("utf-8")
    assert {"video.mp4", "textos.txt", "LEEME.txt", "miniatura.jpg"} <= names
    assert any(n.startswith("shorts/short-1") for n in names)
    assert texts.startswith("TÍTULO\n") and "DESCRIPCIÓN" in texts and "ETIQUETAS" in texts


def test_upload_pack_needs_a_video(logged_in):
    from tests.test_projects import create_channel, project_data

    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    r = logged_in.get("/proyectos/1/paquete")
    assert r.status_code == 400 and "montar el vídeo" in r.text
    assert logged_in.get("/proyectos/9/paquete").status_code == 404
