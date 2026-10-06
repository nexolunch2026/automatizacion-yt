import httpx

from app import assistant, demand
from app.db import SessionLocal
from tests.test_assistant import JarvisAI, ai  # noqa: F401
from tests.test_projects import create_channel


def test_score_levels():
    many = [f"nokia {w}" for w in "uno dos tres cuatro cinco seis siete ocho".split()]
    assert demand.score("Nokia", many)["level"] == "alta"
    assert demand.score("Nokia", many[:5])["icon"] == "📈"
    assert demand.score("Nokia", many[:1])["level"] == "baja"
    unrelated = ["recetas de pasta", "gatos graciosos"]
    assert demand.score("Nokia", unrelated) == {
        "level": "sin datos",
        "icon": "",
        "count": 0,
        "searches": [],
    }
    assert demand.score("Kodák", ["kodak historia"])["count"] == 1  # sin tildes


def test_rank_keeps_order_within_level():
    items = [
        {"name": "a", "demand": {"level": "baja"}},
        {"name": "b", "demand": {"level": "alta"}},
        {"name": "c", "demand": {"level": "sin datos"}},
        {"name": "d", "demand": {"level": "alta"}},
    ]
    assert [x["name"] for x in demand.rank(items)] == ["b", "d", "a", "c"]


def test_fetch_parses_and_caches(monkeypatch):
    calls = []

    def download(term, language):
        calls.append(term)
        if term == "sin red":
            raise httpx.ConnectError("x")
        if term == "rara":
            return "no es json"
        return '["nokia", ["nokia historia", "nokia 3310", 5]]'

    monkeypatch.setattr(demand, "_download", download)
    demand._cache.clear()
    assert demand.fetch("Nokia") == ["nokia historia", "nokia 3310"]
    assert demand.fetch("nokia ") == ["nokia historia", "nokia 3310"]
    assert calls == ["Nokia"]  # la segunda vez sale de la memoria
    assert demand.fetch("sin red") == [] and demand.fetch("  ") == []
    assert demand.fetch("rara") == []


def test_ideas_are_sorted_by_demand(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    searches = {"error de kodak": ["kodak error", "kodak quiebra", "kodak historia", "kodak"]}
    monkeypatch.setattr(demand, "fetch", lambda term, language="es": searches.get(term.lower(), []))
    original = JarvisAI.generate_json

    def with_keywords(self, prompt, schema):
        if schema is assistant.IdeaList:
            assert "keyword" in prompt or "BUSQUE" in prompt
            return assistant.IdeaList(
                ideas=[
                    {"topic": "La caída de Nokia", "hook": "De reina a olvidada", "keyword": "x"},
                    {
                        "topic": "El error de Kodak",
                        "hook": "Inventó la cámara digital",
                        "keyword": "error de Kodak",
                    },
                ]
            )
        return original(self, prompt, schema)

    monkeypatch.setattr(JarvisAI, "generate_json", with_keywords)
    with SessionLocal() as db:
        text = assistant._ideas(db)[0].text
        first = text.index("El error de Kodak")
        assert first < text.index("La caída de Nokia")  # la que se busca, primero
        assert "📈 Demanda media en YouTube" in text and "«kodak error»" in text
        assert assistant._json_setting(db, "telegram_ideas", [])[0] == "El error de Kodak"
