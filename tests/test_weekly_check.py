from datetime import datetime

from app import assistant, system_check
from app.db import SessionLocal
from app.settings_store import set_setting
from app.system_check import FAIL, OK, WARN, Check
from tests.test_assistant import ai  # noqa: F401

weekly_check = assistant.weekly_check  # la de verdad (conftest la apaga en las demás pruebas)

MONDAY = datetime(2026, 10, 5, 10, 0)  # lunes, después de las 9 (hora del piloto)
BAD = [
    Check("Versión", OK, "Faceless Studio"),
    Check("Espacio en disco", FAIL, "1.2 GB libres", "Libera espacio."),
    Check("YouTube", WARN, "Sin clave (opcional)", "Con la clave…"),
]


def linked(db):
    set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')


def fake_checks(monkeypatch, checks):
    calls = []
    monkeypatch.setattr(system_check, "run_all", lambda db: calls.append(1) or checks)
    return calls


def test_monday_check_warns_once_a_week_only_about_problems(logged_in, ai, monkeypatch):  # noqa: F811
    calls = fake_checks(monkeypatch, BAD)
    with SessionLocal() as db:
        assert weekly_check(db, MONDAY) == []  # sin Telegram vinculado, nada
        assert calls == []
        linked(db)
        assert weekly_check(db, MONDAY.replace(hour=7)) == []  # aún es pronto
        reply = weekly_check(db, MONDAY)[0]
        assert "Revisión semanal del ordenador" in reply.text
        assert "Espacio en disco" in reply.text and "Libera espacio." in reply.text
        assert "YouTube" not in reply.text and "Versión" not in reply.text
        assert reply.buttons == [[("🩺 Revisar otra vez", "syscheck")]]
        assert weekly_check(db, MONDAY.replace(hour=18)) == []  # ya avisó
        assert len(calls) == 1
        assert weekly_check(db, datetime(2026, 10, 12, 10)) != []  # otro lunes


def test_all_good_means_silence(logged_in, ai, monkeypatch):  # noqa: F811
    fake_checks(monkeypatch, [BAD[0], BAD[2]])  # solo falta la clave opcional
    with SessionLocal() as db:
        linked(db)
        assert weekly_check(db, MONDAY) == []


def test_pc_off_on_monday_checks_the_next_day_it_opens(logged_in, ai, monkeypatch):  # noqa: F811
    fake_checks(monkeypatch, BAD)
    with SessionLocal() as db:
        linked(db)
        assert weekly_check(db, datetime(2026, 10, 7, 8, 0)) != []  # miércoles


def test_a_failing_check_is_told_not_hidden(logged_in, ai, monkeypatch):  # noqa: F811
    def broken(db):
        raise OSError("disco desconectado")

    monkeypatch.setattr(system_check, "run_all", broken)
    with SessionLocal() as db:
        linked(db)
        reply = weekly_check(db, MONDAY)[0]
        assert "No pude hacer la revisión" in reply.text and reply.buttons
        assert weekly_check(db, MONDAY) == []  # no lo reintenta en bucle


def test_without_internet_it_tries_again_in_an_hour(logged_in, ai, monkeypatch):  # noqa: F811
    offline = [Check("Internet", FAIL, "Sin conexión", "Revisa el wifi."), BAD[1]]
    calls = fake_checks(monkeypatch, offline)
    with SessionLocal() as db:
        linked(db)
        assert weekly_check(db, MONDAY) == []  # el aviso no llegaría
        assert weekly_check(db, MONDAY.replace(minute=30)) == []  # espera 1 hora
        assert len(calls) == 1
        calls_back = fake_checks(monkeypatch, BAD)
        reply = weekly_check(db, MONDAY.replace(hour=11, minute=5))[0]
        assert "Espacio en disco" in reply.text and len(calls_back) == 1


def test_button_runs_the_full_check(logged_in, ai, monkeypatch):  # noqa: F811
    fake_checks(monkeypatch, BAD)
    with SessionLocal() as db:
        reply = assistant._button(db, "syscheck")[0]
    assert "🩺" in reply.text and "Espacio en disco" in reply.text and "Versión" in reply.text
