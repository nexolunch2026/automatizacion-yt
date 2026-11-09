"""Control de calidad: datos comprobados con fuentes fiables (botón del Guion)."""

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import Project, StageResult
from app.pipeline.monetization import FACTS_STALE, _facts_check, project_review
from tests.test_strategy_script import make_project

SCRIPT = {"title": "Kodak", "sections": []}


def facts(confirmed=3, wrong=0, doubtful=0):
    claims = (
        [{"status": "confirmado"}] * confirmed
        + [{"status": "corregir"}] * wrong
        + [{"status": "una_fuente"}] * doubtful
    )
    return {"claims": claims, "summary": {}}  # el resumen no hace falta


def check(results):
    found = _facts_check(results)
    return found[0] if found else None


def test_no_script_no_check():
    assert check({}) is None


def test_not_checked_yet():
    found = check({"script": SCRIPT})
    assert found["status"] == "warn" and found["title"] == "Datos sin comprobar"
    assert "Comprobar datos con fuentes fiables" in found["fix"]
    assert found["link"] == "guion#datos"
    assert check({"script": SCRIPT, "factcheck": {"claims": []}})["status"] == "warn"


def test_wrong_facts_and_all_good():
    wrong = check({"script": SCRIPT, "factcheck": facts(wrong=2)})
    assert wrong["status"] == "warn" and wrong["title"] == "2 datos para corregir"
    one = check({"script": SCRIPT, "factcheck": facts(wrong=1)})
    assert one["title"] == "1 dato para corregir"
    good = check({"script": SCRIPT, "factcheck": facts(confirmed=5)})
    assert good["status"] == "ok" and "Los 5 datos" in good["detail"]


def test_doubtful_or_nothing_confirmed_is_not_ok():
    some = check({"script": SCRIPT, "factcheck": facts(confirmed=3, doubtful=2)})
    assert some["status"] == "warn" and some["title"] == "2 datos sin confirmar del todo"
    assert "3 confirmados" in some["detail"] and "con prudencia" in some["fix"]
    odd = check({"script": SCRIPT, "factcheck": {"claims": [{}, "raro"]}})
    assert odd["status"] == "warn" and "1 dato sin confirmar" in odd["title"]


def test_script_changed_after_checking():
    found = check({"script": SCRIPT, "factcheck": facts(wrong=1), FACTS_STALE: True})
    assert found["status"] == "warn" and "cambió después" in found["title"]  # va primero


def test_project_review_uses_the_dates(logged_in):
    make_project(logged_in, "manual")
    now = datetime.now()
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="script", data=SCRIPT, updated_at=now))
        db.add(StageResult(project_id=1, stage="factcheck", data=facts(),
                           updated_at=now - timedelta(hours=1)))  # fmt: skip
        db.commit()
        qc = project_review(db, db.get(Project, 1))
        found = next(c for c in qc["checks"] if c["key"] == "facts")
        assert "cambió después" in found["title"]
        row = db.query(StageResult).filter_by(project_id=1, stage="factcheck").one()
        row.updated_at = now + timedelta(hours=1)
        db.commit()
        qc = project_review(db, db.get(Project, 1))
        found = next(c for c in qc["checks"] if c["key"] == "facts")
    assert found["status"] == "ok"
