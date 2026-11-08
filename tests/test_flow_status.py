"""«¿Qué me falta en Flow?»: JARVIS dice cuántas escenas de cada vídeo siguen sin imagen y
por cuál conviene empezar."""

from app import assistant, flow, jobs
from app.db import SessionLocal
from app.models import Project, StageResult
from tests.test_assistant import ai  # noqa: F401
from tests.test_strategy_script import make_project


def board(*numbers, chart=()):
    return {"scenes": [
        {"number": n, "paragraph_id": f"p{n}", "visual_type": "grafico" if n in chart else "imagen"}
        for n in numbers
    ]}  # fmt: skip


def test_pending_scenes():
    visuals = {"items": {
        "p1": {"kind": "image", "provider": "flow"},
        "p2": {"kind": "image", "provider": "manual"},  # subida a mano: cuenta como hecha
        "p3": {"kind": "image", "provider": "pixabay"},  # de banco: falta la de Flow
        "p4": {"kind": "card"},
        "p7": {"kind": "image", "provider": "gemini", "ai": True},  # hecha con IA: hecha
    }}  # fmt: skip
    assert flow.pending_scenes(board(1, 2, 3, 4, 5, 6, 7, chart=(6,)), visuals) == [3, 4, 5]
    assert flow.pending_scenes(board(2, 1), {}) == [1, 2]
    odd = {"scenes": [{"number": "x", "paragraph_id": "a"}, "raro", {"number": 3}]}
    assert flow.pending_scenes(odd, {"items": "roto"}) == [1, 3]  # sin número: por su sitio


def add(db, project_id, stage, data):
    db.add(StageResult(project_id=project_id, stage=stage, data=data))
    db.commit()


def ask(db, text):
    return assistant.handle(db, assistant.Incoming(chat_id=1, text=text), trusted=True)


def test_jarvis_lists_what_is_missing_and_where_to_start(logged_in, ai):  # noqa: F811
    for _ in range(2):
        make_project(logged_in, "manual")
    with SessionLocal() as db:
        assert "Aún no hay vídeos con escenas" in ask(db, "¿Qué me falta en Flow?")[0].text
        db.get(Project, 1).title = "Kodak <1975>"
        db.get(Project, 2).title = "Bale"
        add(db, 1, "storyboard", board(*range(1, 13)))
        add(db, 1, "visuals", {"items": {"p1": {"provider": "flow"}}})
        add(db, 2, "storyboard", board(1, 2, 3))
        add(db, 2, "visuals", {"items": {"p1": {"provider": "flow"}}})
        text = ask(db, "qué me falta en flow")[0].text
    assert "«Kodak &lt;1975&gt;»: 11 escenas (n.º 2, 3, 4, 5, 6, 7, 8, 9 y 3 más)" in text
    assert "«Bale»: 2 escenas (n.º 2, 3)" in text
    assert "Empieza por «Bale»: es al que menos le falta" in text


def test_a_stopped_automatic_video_goes_first(logged_in, ai):  # noqa: F811
    for _ in range(2):
        make_project(logged_in, "manual")
    with SessionLocal() as db:
        db.get(Project, 1).automation_mode = "automatico"
        add(db, 1, "storyboard", board(1, 2, 3, 4, 5))
        add(db, 2, "storyboard", board(1))
        title = db.get(Project, 1).title
        text = ask(db, "flow")[0].text
        assert f"Empieza por «{title}»: está parado esperando las imágenes" in text
        jobs.enqueue(db, 1, "voice")  # aún trabajando: no está parado
        text = ask(db, "flow")[0].text
    assert "está parado" not in text


def test_everything_done(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        add(db, 1, "storyboard", board(1, 2, chart=(2,)))
        add(db, 1, "visuals", {"items": {"p1": {"provider": "flow"}}})
        assert "ya tienen sus imágenes" in ask(db, "qué imágenes faltan")[0].text


def test_published_and_empty_videos_are_skipped_and_broken_ones_named(logged_in, ai, monkeypatch):  # noqa: F811,E501
    for _ in range(3):
        make_project(logged_in, "manual")
    with SessionLocal() as db:
        db.get(Project, 1).status = "Publicado"
        add(db, 1, "storyboard", board(1, 2))  # ya subido: no cuenta
        add(db, 2, "storyboard", {"scenes": []})  # sin escenas: no cuenta
        add(db, 3, "storyboard", board(1))
        broken_title = db.get(Project, 3).title
        real = flow.pending_scenes

        def boom(board, visuals):
            raise ValueError("dato raro")

        monkeypatch.setattr(flow, "pending_scenes", boom)
        text = ask(db, "flow")[0].text
        assert "No pude revisar" in text and broken_title in text
        monkeypatch.setattr(flow, "pending_scenes", real)
        text = ask(db, "flow")[0].text
    # solo el n.º 3 (el publicado y el que no tiene escenas no salen)
    assert "1 escena (n.º 1)" in text and "No pude" not in text
    assert text.count("•") == 1
