from app import info, learning, profile
from app.db import SessionLocal
from app.settings_store import get_setting, set_setting
from tests.conftest import register
from tests.test_strategy_script import make_project


def test_new_install_asks_for_the_profile(client):
    response = register(client)
    assert response.url.path == "/bienvenida"
    page = response.text
    assert "Te damos la bienvenida" in page and "Pasárselo a otra persona" in page
    assert "instalar.ps1" in page
    assert "Completar mi perfil" in client.get("/").text
    with SessionLocal() as db:
        assert not profile.is_set(db)
        assert info.youtube(db) is None  # sin canal no se consulta nada
        assert profile.owner(db) == ""
        assert "un canal de YouTube" in profile.about(db)


def test_save_profile_shapes_the_texts_for_the_ai(logged_in):
    logged_in.post(
        "/bienvenida",
        data={
            "owner": "  Ana  ",
            "channel": "Misterios del Mundo",
            "handle": "@MisteriosDelMundo",
            "niche": "documentales sobre misterios sin resolver",
            "country": "México",
        },
    )
    page = logged_in.get("/bienvenida").text
    assert "Mi perfil" in page and "Misterios del Mundo" in page
    assert "Completar mi perfil" not in logged_in.get("/").text
    with SessionLocal() as db:
        about = profile.about(db)
        assert "«Misterios del Mundo»" in about and "misterios sin resolver" in about
        assert "Lo lleva Ana, desde México" in about
        assert info.channel_handle(db) == "@MisteriosDelMundo"
        assert info.news_region(db)["gl"] == "MX"
        assert "Misterios del Mundo" in learning.prompt(about)


def test_unknown_country_and_empty_niche_fall_back(logged_in):
    with SessionLocal() as db:
        p = profile.save(db, "", "", "", "Narnia")
        assert p["country"] == "Otro" and p["niche"] == profile.DEFAULT_NICHE
        assert "desde" not in profile.about(db)


def test_old_installs_keep_the_original_channel(logged_in):
    make_project(logged_in)
    with SessionLocal() as db:
        set_setting(db, "profile", "")
        profile.migrate(db)
        p = profile.get(db)
        assert p["owner"] == "Simón" and p["channel"] == "Anatomía De Una Marca"
        assert get_setting(db, "youtube_channel") == "@AnatomiaDeUnaMarca"


def test_migration_respects_a_channel_already_written(logged_in):
    make_project(logged_in)
    with SessionLocal() as db:
        set_setting(db, "profile", "")
        set_setting(db, "youtube_channel", "@OtroCanal")
        profile.migrate(db)
        assert get_setting(db, "youtube_channel") == "@OtroCanal"
        profile.save(db, "Ana", "X", "", "España")
        profile.migrate(db)  # con perfil ya guardado no toca nada
        assert profile.owner(db) == "Ana"


def test_fresh_install_is_not_migrated(logged_in):
    with SessionLocal() as db:
        profile.migrate(db)
        assert not profile.is_set(db)
