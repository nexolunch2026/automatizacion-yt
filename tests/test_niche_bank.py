from app import assistant, niche_bank
from app.assistant import Incoming
from app.db import SessionLocal
from app.models import Channel, Project
from app.providers.ai import ProviderError
from tests.test_assistant import ai  # noqa: F401
from tests.test_projects import brand_channel, create_channel

BANK = niche_bank.Bank(
    ideas=[
        {"topic": "El caso Dyatlov", "format": "Misterio sin resolver", "hook": "9 muertos."},
        {"topic": "El vuelo MH370", "format": "Misterio sin resolver", "hook": "Desapareció."},
        {"topic": "La Santa Compaña", "format": "Leyenda", "hook": "Galicia, de noche."},
        {"topic": "el caso dyatlov", "format": "Leyenda", "hook": "Repetido."},
        {"topic": "  ", "format": "Leyenda", "hook": "Vacío."},
        {"topic": "🔥🔥", "format": "Leyenda", "hook": "Solo símbolos."},
    ]
    + [{"topic": f"Caso real número {n}", "format": "Otro", "hook": "x"} for n in range(9)]
)


def fake_bank(monkeypatch, ai, bank=BANK):  # noqa: F811
    prompts = []
    original = ai.generate_json

    def answer(prompt, schema):
        if schema is niche_bank.Bank:
            prompts.append(prompt)
            if isinstance(bank, Exception):
                raise bank
            return bank
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", answer)
    return prompts


def test_other_niches_get_their_own_bank_once(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)  # nicho «casos raros», no de marcas
    prompts = fake_bank(monkeypatch, ai)
    with SessionLocal() as db:
        reply = assistant.bank_replies(db)[0]
        assert "Banco de historias — casos raros" in reply.text
        assert "El caso Dyatlov" in reply.text and "🪝 9 muertos." in reply.text
        assert reply.text.count("Dyatlov") == 1 and "Vacío" not in reply.text  # sin repetidos
        assert "Solo símbolos" not in reply.text
        # Formatos variados: tras un «Misterio» va la «Leyenda» antes que el otro misterio.
        assert reply.text.index("Santa Compaña") < reply.text.index("MH370")
        assert "30 TEMAS" in prompts[0] and "casos raros" in prompts[0]

        assistant.handle(db, Incoming(chat_id=1, button="idea:0"), trusted=True)
        assert db.query(Project).filter_by(topic="El caso Dyatlov").count() == 1
        again = assistant.bank_replies(db)[0].text
    assert len(prompts) == 1  # el banco se guarda: no gasta Gemini otra vez
    assert "Dyatlov" not in again and "Llevas 1 de 12 temas" in again


def test_changing_niche_makes_a_new_bank(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    prompts = fake_bank(monkeypatch, ai)
    with SessionLocal() as db:
        assistant.bank_replies(db)
        db.get(Channel, 1).niche = "finanzas personales"
        db.commit()
        reply = assistant.bank_replies(db)[0]
    assert len(prompts) == 2 and "finanzas personales" in reply.text


def test_gemini_failure_is_explained(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    fake_bank(monkeypatch, ai, ProviderError("Google está saturado."))
    with SessionLocal() as db:
        reply = assistant.bank_replies(db)[0]
        assert "No pude crear el banco" in reply.text and "saturado" in reply.text
        assert niche_bank.stored(db, db.get(Channel, 1), "casos raros") is None


def test_brand_channels_keep_the_fixed_bank(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    brand_channel()
    prompts = fake_bank(monkeypatch, ai)
    with SessionLocal() as db:
        reply = assistant.bank_replies(db)[0]
    assert "Banco de historias" in reply.text and prompts == []


def test_a_tiny_bank_is_not_saved(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    fake_bank(monkeypatch, ai, niche_bank.Bank(ideas=BANK.ideas[:3]))
    with SessionLocal() as db:
        reply = assistant.bank_replies(db)[0]
        assert "no me dio temas útiles" in reply.text
        assert niche_bank.stored(db, db.get(Channel, 1), "casos raros") is None


def test_broken_saved_bank_is_ignored(logged_in, ai):  # noqa: F811
    from app.settings_store import set_setting

    create_channel(logged_in)
    with SessionLocal() as db:
        channel = db.get(Channel, 1)
        for raw in ("[1, 2]", '{"niche": "casos raros", "ideas": [{"hook": "sin tema"}]}'):
            set_setting(db, niche_bank.KEY.format(1), raw)
            assert niche_bank.stored(db, channel, "casos raros") is None
        set_setting(
            db, niche_bank.KEY.format(1), '{"niche": "casos raros", "ideas": [{"topic": "X caso"}]}'
        )
        assert niche_bank.stored(db, channel, "casos raros") == [
            {"topic": "X caso", "format": "", "hook": ""}
        ]
