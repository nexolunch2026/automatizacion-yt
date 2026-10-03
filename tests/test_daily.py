import pytest

from app import daily
from app.assistant import Incoming, handle, quick_intent
from app.db import SessionLocal
from tests.test_assistant import ai  # noqa: F401


def say(db, text):
    return handle(db, Incoming(chat_id=1, text=text), trusted=True)[0].text


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("25 por 4", 100),
        ("3500 entre 7", 500),
        ("10 mas 5 menos 3", 12),
        ("el 15 por ciento de 80.000", 12000),
        ("15% de 200", 30),
        ("1.234,5 por 2", 2469),
        ("2 al cuadrado", 4),
        ("hola que tal", None),
        ("1 entre 0", None),
        ("9 ** 9999", None),  # nada de cuentas gigantes
    ],
)
def test_calculate(expression, value):
    assert daily.calculate(expression) == value


def test_say_number():
    assert daily.say_number(12000) == "12.000" and daily.say_number(2.5) == "2,5"
    assert daily.say_number(1234567.891) == "1.234.567,89"


@pytest.mark.parametrize(
    ("text", "action", "target"),
    [
        ("Añade leche y azúcar a la lista de la compra", "shopping", "add"),
        ("apunta pan en la lista", "shopping", "add"),
        ("ya compré la leche", "shopping", "remove"),
        ("quita el pan de la lista", "shopping", "remove"),
        ("¿Qué hay en la lista de la compra?", "shopping", "show"),
        ("borra la lista de la compra", "shopping", "clear"),
        ("¿Cuánto es 25 por 4?", "calc", ""),
        ("el 15 por ciento de 80000", "calc", ""),
    ],
)
def test_understands_daily_phrases(text, action, target):
    intent = quick_intent(text)
    assert (intent.action, intent.target) == (action, target)


def test_tasks_are_not_mistaken_for_the_shopping_list():
    assert quick_intent("borra la tarea comprar micrófono").action == "task_done"


def test_shopping_list_end_to_end(logged_in):
    with SessionLocal() as db:
        assert "leche, azúcar" in say(db, "Añade leche y azúcar a la lista de la compra")
        assert "ya estaba" in say(db, "añade leche a la lista")
        assert "• azúcar" in say(db, "qué hay en la lista")
        assert "Quedan 1" in say(db, "ya compré la leche")
        assert "no estaba" in say(db, "ya compré caviar")
        assert "borrada" in say(db, "borra la lista de la compra")
        assert "vacía" in say(db, "qué hay en la lista")
        assert "= <b>100</b>" in say(db, "¿Cuánto es 25 por 4?")
