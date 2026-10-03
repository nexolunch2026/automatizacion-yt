import pytest

from app import pc
from app.assistant import Incoming, handle, quick_intent
from app.db import SessionLocal
from tests.test_assistant import ai  # noqa: F401


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pc, "RUN", lambda kind, value: seen.append((kind, value)))
    folders = {**pc.FOLDERS, "descargas": tmp_path}
    monkeypatch.setattr(pc, "FOLDERS", folders)
    return seen


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("Abre descargas", "folder:descargas"),
        ("abre la carpeta de documentos", "folder:documentos"),
        ("abre la calculadora", "program:calculadora"),
        ("Ábreme el bloc de notas", "program:bloc de notas"),
        ("sube el volumen", "volume_up"),
        ("Jarvis, baja el volumen", "volume_down"),
        ("siguiente canción", "next"),
        ("bloquea el ordenador", "lock"),
    ],
)
def test_understands_pc_orders(text, target):
    intent = quick_intent(text)
    assert (intent.action, intent.target) == ("pc", target)


def test_websites_still_open_in_the_browser():
    assert quick_intent("abre youtube studio").action == "open"


def test_pc_actions_run_on_windows(calls, logged_in):
    with SessionLocal() as db:
        say = lambda t: handle(db, Incoming(chat_id=1, text=t), trusted=True)[0].text  # noqa: E731
        assert "Abro la carpeta descargas" in say("abre descargas")
        assert "Abro calculadora" in say("abre la calculadora")
        assert "Subo el volumen" in say("sube el volumen")
        assert "Bloqueo el ordenador" in say("bloquea el pc")
    assert calls[0][0] == "start" and calls[1] == ("start", "calc")
    assert calls[2] == ("keys", (175, 5)) and calls[3] == ("lock", None)


def test_missing_folder_is_explained(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "FOLDERS", {**pc.FOLDERS, "musica": tmp_path / "no-existe"})
    assert "No encuentro la carpeta" in pc.do("folder", "musica")
    assert calls == []


def test_outside_windows_nothing_runs(monkeypatch):
    monkeypatch.setattr(pc, "is_windows", lambda: False)
    assert "solo puedo hacerlo" in pc.do("volume_up")
