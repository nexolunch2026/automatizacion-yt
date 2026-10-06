from app import assistant, info, niche, profile
from app.db import SessionLocal
from app.models import Channel
from app.providers.ai import ProviderError
from tests.test_assistant import ai  # noqa: F401
from tests.test_projects import brand_channel
from tests.test_strategy_script import make_project, run_all

FINANCE = niche.Kit(
    video_format="Explicaciones narradas de finanzas personales con casos reales",
    audience="Jóvenes que empiezan a ganar dinero",
    tone="Claro y cercano, sin prometer riqueza",
    structures=[
        niche.Structure(name="El error más caro", guide="Un error común y cuánto cuesta."),
        niche.Structure(name="Antes y después", guide="Cómo cambió la vida de alguien."),
        niche.Structure(name="El error más caro", guide="Repetida: debe tener otra clave."),
        niche.Structure(name="", guide="Sin nombre: se descarta."),
    ],
    closing_name="Tu siguiente paso",
    closing_guide="Una acción concreta para hacer hoy con el dinero.",
    title_tips=["Una cifra concreta en el título"],
    thumbnail_tips=["Un billete y una emoción"],
    idea_formats=["el error más caro", "reto de 30 días"],
    news_query="ahorro OR inflación OR tasas de interés",
    fact_topic="el dinero y la economía doméstica",
    avoid=["No dar consejos de inversión personalizados"],
)


class KitAI:
    def __init__(self, kit=FINANCE, error=None):
        self.kit, self.error, self.calls = kit, error, 0

    def generate_json(self, prompt, schema):
        assert schema is niche.Kit and "finanzas personales" in prompt
        self.calls += 1
        if self.error:
            raise self.error
        return self.kit


def make_channel(db, niche_text="finanzas personales"):
    channel = Channel(name="Dinero Claro", niche=niche_text, language="Español", created_by=1)
    db.add(channel)
    db.commit()
    return channel


def test_brand_channels_keep_their_kit_without_ai(logged_in):
    with SessionLocal() as db:
        channel = make_channel(db, "historias de marcas y empresas")
        kit = niche.ensure(db, channel, KitAI(error=AssertionError("no debe llamarse")))
    assert kit.closing_name == "La lección de la marca"
    assert [s.key for s in kit.structures][:2] == ["cronologia", "auge_caida"]


def test_other_niches_get_a_general_kit_until_the_ai_makes_one(logged_in):
    with SessionLocal() as db:
        channel = make_channel(db)
        general = niche.kit_for(db, channel)
        assert general.niche == "finanzas personales" and general.closing_name == "La idea clave"
        assert not niche.has_own_kit(db, channel)

        fake = KitAI()
        kit = niche.ensure(db, channel, fake)
        assert kit.closing_name == "Tu siguiente paso" and niche.has_own_kit(db, channel)
        assert [s.key for s in kit.structures] == [
            "el_error_mas_caro",
            "antes_y_despues",
            "el_error_mas_caro_2",
        ]
        niche.ensure(db, channel, fake)
        assert fake.calls == 1  # se crea una vez y se guarda

        channel.niche = "historia de España"  # otro nicho: la ficha vieja ya no vale
        db.commit()
        assert niche.kit_for(db, channel).niche == "historia de España"
        assert not niche.has_own_kit(db, channel)


def test_kit_errors_never_stop_a_video(logged_in):
    with SessionLocal() as db:
        channel = make_channel(db)
        kit = niche.ensure(db, channel, KitAI(error=ProviderError("sin cuota")))
        assert kit.closing_name == "La idea clave"
        broken = FINANCE.model_copy(update={"structures": []})
        kit = niche.ensure(db, channel, KitAI(kit=broken))
        assert len(kit.structures) >= 2  # sin estructuras útiles, las generales


def test_empty_channel_niche_uses_the_profile(logged_in):
    with SessionLocal() as db:
        profile.save(db, "Ana", "Cielo Rojo", "documentales sobre astronomía", "Chile")
        channel = make_channel(db, "")
        assert niche.kit_for(db, channel).niche == "documentales sobre astronomía"


def test_the_kit_reaches_strategy_and_script(logged_in, ai, monkeypatch):  # noqa: F811
    prompts = []
    original = ai.generate_json

    def spy(prompt, schema):
        if schema is niche.Kit:
            return FINANCE
        prompts.append(prompt)
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", spy)
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        db.get(Channel, 1).niche = "finanzas personales"
        db.commit()
    for stage in ("research", "strategy"):
        logged_in.post(f"/proyectos/1/etapas/{stage}")
        run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    strategy = next(p for p in prompts if "Propón 3 enfoques" in p)
    assert "Una cifra concreta en el título" in strategy
    assert "canales de documentales de empresas" not in strategy
    outline = next(p for p in prompts if "Haz el ESQUEMA" in p)
    assert "Estructura narrativa: El error más caro." in outline
    assert "No dar consejos de inversión personalizados" in outline
    ending = next(p for p in prompts if "«Conclusión:" in p)
    assert "«Tu siguiente paso»" in ending and "La lección de la marca" not in ending

    page = logged_in.get("/proyectos/1/guion").text
    assert "El error más caro" in page and "Ascenso y caída" not in page


def test_channels_page_shows_and_remakes_the_kit(logged_in, ai, monkeypatch):  # noqa: F811
    make_project(logged_in, "manual")
    logged_in.post("/canales/1/nicho", data={"niche": "  finanzas   personales "})
    page = logged_in.get("/canales").text
    assert "finanzas personales" in page and "Crear la ficha de mi nicho" in page
    monkeypatch.setattr(ai, "generate_json", lambda prompt, schema: FINANCE)
    logged_in.post("/canales/1/ficha")
    page = logged_in.get("/canales").text
    assert "Tu siguiente paso" in page and "Rehacer ficha" in page
    assert logged_in.post("/canales/9/ficha").status_code == 404


def test_ideas_radar_and_fact_follow_the_niche(logged_in, ai, monkeypatch):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        db.get(Channel, 1).niche = "finanzas personales"
        db.commit()
        niche.generate(db, db.get(Channel, 1), KitAI())
        assert niche.main_kit(db).fact_topic == "el dinero y la economía doméstica"

        bank = assistant.bank_replies(db)[0].text
        assert "marcas y empresas" in bank and "ideas" in bank

        prompts = []
        monkeypatch.setattr(
            ai, "generate_json", lambda prompt, schema: prompts.append(prompt) or schema(fact="x")
        )
        info.fact_of_day(db)
        assert "el dinero y la economía doméstica" in prompts[0]

        queries = []

        def fake_get(url, **params):
            queries.append(params.get("q", ""))
            raise info.httpx.ConnectError("sin red")

        monkeypatch.setattr(info, "_get", fake_get)
        info.brand_radar(db)
        assert queries and queries[0].startswith("ahorro OR inflación")

    brand_channel()
    with SessionLocal() as db:
        assert "Banco de historias" in assistant.bank_replies(db)[0].text


def test_ideas_without_gemini_in_other_niches_do_not_loop(logged_in, ai, monkeypatch):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        db.get(Channel, 1).niche = "finanzas personales"
        db.commit()

    def broken(prompt, schema):
        raise ProviderError("Google está saturado.", transient=True)

    monkeypatch.setattr(ai, "generate_json", broken)
    with SessionLocal() as db:
        text = assistant._ideas(db)[0].text
    assert "No pude pensar ideas" in text
