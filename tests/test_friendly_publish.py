from types import SimpleNamespace

from app.pipeline.monetization import _ads_checks, flagged_words

PROJECT = SimpleNamespace(duration="Largo")


def check(results, key):
    checks = _ads_checks(PROJECT, results, "La caída de Kodak")
    found = [c for c in checks if c["key"] == key]
    return found[0] if found else None


def thumbs(*texts, selected=None):
    return {"variants": [{"text": t} for t in texts], "selected": selected}


def test_profanity_with_ñ_is_found():
    assert flagged_words("¡Qué coño pasó con Kodak!")[0] == ["coño"]
    assert flagged_words("El cono de helado")[0] == []  # «cono» no es «coño»


def test_clean_texts_are_ok_and_nothing_is_said_without_them():
    results = {
        "thumbnail": thumbs("EL FIN DE KODAK", selected=0),
        "publish": {"description": "Kodak inventó la cámara digital.", "tags": ["Kodak"]},
    }
    assert check(results, "friendly_thumb")["status"] == "ok"
    assert check(results, "friendly_texts")["status"] == "ok"
    assert check({}, "friendly_thumb") is None and check({}, "friendly_texts") is None
    only_thumb = {"thumbnail": thumbs("EL FIN", selected=0)}
    assert check(only_thumb, "friendly_texts") is None  # no se dice «bien» sin revisar


def test_sensitive_word_in_the_thumbnail():
    chosen = check({"thumbnail": thumbs("LA MASACRE", "EL FIN", selected=0)}, "friendly_thumb")
    assert chosen["status"] == "fail" and chosen["link"] == "miniatura"
    assert "masacre" in chosen["detail"]
    other = check({"thumbnail": thumbs("LA MASACRE", "EL FIN", selected=1)}, "friendly_thumb")
    assert other["status"] == "ok"  # se eligió la buena
    draft = check({"thumbnail": thumbs("EL FIN", "LA MASACRE")}, "friendly_thumb")
    assert draft["status"] == "warn" and "elige otra" in draft["fix"]  # aún sin elegir


def test_description_tags_and_pinned_comment_say_where():
    swear = check({"publish": {"description": "Todo se fue a la mierda."}}, "friendly_texts")
    assert swear["status"] == "fail" and "la descripción" in swear["title"]
    tags = check(
        {"publish": {"description": "Kodak.", "tags": "terrorismo, kodak"}}, "friendly_texts"
    )
    assert tags["status"] == "warn" and tags["title"] == "Temas delicados en las etiquetas"
    pinned = check({"publish": {"pinned_comment": "¿Fue un genocidio?"}}, "friendly_texts")
    assert "el comentario fijado" in pinned["title"]


def test_sources_and_links_added_by_the_program_do_not_count():
    description = (
        "Kodak inventó la cámara digital.\n\n📚 Fuentes\n- La masacre de la bolsa: "
        "https://ejemplo.com/puta-noticia\n\n#Kodak"
    )
    found = check({"publish": {"description": description}}, "friendly_texts")
    assert found["status"] == "ok"


def test_odd_stored_data_does_not_break():
    results = {"thumbnail": {"variants": [None, {"text": None}], "selected": "0"},
               "publish": {"tags": None, "description": None}}  # fmt: skip
    assert check(results, "friendly_thumb") is None and check(results, "friendly_texts") is None
    assert check({"thumbnail": [1], "publish": "roto"}, "friendly_texts") is None
