import socket

import pytest

from app import __main__ as launcher
from app import running, updater

NETSTAT = """
Conexiones activas

  Proto  Dirección local          Dirección remota        Estado           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1012
  TCP    127.0.0.1:8000         127.0.0.1:51234        ESTABLISHED     7777
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       4321
  TCP    127.0.0.1:18000        0.0.0.0:0              LISTENING       999
  TCP    [::1]:8000             [::]:0                 LISTENING       4321
"""


def test_finds_the_process_listening_on_the_port():
    assert running.listener_pid(NETSTAT, 8000) == 4321
    assert running.listener_pid(NETSTAT, 18000) == 999
    assert running.listener_pid(NETSTAT, 9000) is None
    assert running.listener_pid("", 8000) is None


def test_only_python_is_closed():
    assert running.is_python('"python.exe","4321","Console","1","80.000 K"')
    assert running.is_python('"pythonw.exe","4321","Console","1","80.000 K"')
    assert not running.is_python('"chrome.exe","4321","Console","1","80.000 K"')
    assert not running.is_python("INFO: No hay tareas ejecutándose.")


@pytest.fixture
def busy_port():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    yield server
    server.close()


def test_stop_closes_our_program_on_windows(busy_port, monkeypatch):
    port = busy_port.getsockname()[1]
    calls = []

    def fake_run(args):
        calls.append(args[0])
        if args[0] == "netstat":
            return f"  TCP    127.0.0.1:{port}    0.0.0.0:0    LISTENING    4321\n"
        if args[0] == "tasklist":
            return '"python.exe","4321","Console","1","80.000 K"'
        busy_port.close()  # taskkill: el programa se apaga
        return ""

    monkeypatch.setattr(running.sys, "platform", "win32")
    monkeypatch.setattr(running, "_run", fake_run)
    assert running.stop("127.0.0.1", port, wait=3)
    assert calls == ["netstat", "tasklist", "taskkill"]


def test_stop_never_touches_another_program(busy_port, monkeypatch):
    port = busy_port.getsockname()[1]
    calls = []

    def fake_run(args):
        calls.append(args[0])
        if args[0] == "netstat":
            return f"  TCP    127.0.0.1:{port}    0.0.0.0:0    LISTENING    4321\n"
        return '"skype.exe","4321","Console","1","80.000 K"'

    monkeypatch.setattr(running.sys, "platform", "win32")
    monkeypatch.setattr(running, "_run", fake_run)
    assert not running.stop("127.0.0.1", port, wait=1)
    assert "taskkill" not in calls


def test_stop_with_nothing_running_is_fine():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert running.stop("127.0.0.1", free)


def test_updater_closes_the_open_program_first(monkeypatch, capsys):
    stopped = []
    monkeypatch.setattr(running, "port_in_use", lambda host, port: True)
    monkeypatch.setattr(running, "stop", lambda host, port: stopped.append(port) or True)
    monkeypatch.setattr(updater, "update", lambda: updater.VERSION)
    updater.main()
    out = capsys.readouterr().out
    assert stopped and "Lo apago para poder actualizar" in out and "Ya tenías" in out


def test_updater_explains_when_it_cannot_close_it(monkeypatch, capsys):
    monkeypatch.setattr(running, "port_in_use", lambda host, port: True)
    monkeypatch.setattr(running, "stop", lambda host, port: False)
    monkeypatch.setattr(updater, "update", lambda: pytest.fail("no debe actualizar"))
    with pytest.raises(SystemExit):
        updater.main()
    assert "Administrador de tareas" in capsys.readouterr().out


def test_start_when_already_open_just_opens_the_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "port_in_use", lambda host, port: True)
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(launcher.sys, "argv", ["app"])
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *a, **k: pytest.fail("no otro servidor"))
    with pytest.raises(SystemExit) as exit_info:
        launcher.main()
    assert exit_info.value.code == launcher.ALREADY_RUNNING
    assert opened == [f"http://{launcher.HOST}:{launcher.PORT}"]
