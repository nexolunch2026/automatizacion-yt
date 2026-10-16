from app.pipeline.monetization import _promise_check, title_brands, title_words


def script(text):
    return {"sections": [{"kind": "hook", "title": "", "paragraphs": [{"id": "p", "text": text}]}]}


def check(title, text):
    found = _promise_check({"script": script(text)}, title)
    return found[0] if found else None


def test_title_words_skip_filler():
    assert title_words("La historia de Kodak: el secreto que nadie vio") == ["kodak"]
    assert title_words("Nokia y BlackBerry: la caída de los móviles") == [
        "nokia",
        "blackberry",
        "caida",
        "moviles",
    ]


def test_opening_that_mentions_the_title_passes():
    found = check(
        "Nokia y BlackBerry: la caída de los móviles",
        "En 2007 Nokia vendía uno de cada tres móviles del planeta. " * 3,
    )
    assert found["status"] == "ok"


def test_opening_that_ignores_the_title_warns():
    filler = " ".join(["palabra"] * 200)
    found = check(
        "Nokia y BlackBerry: la caída de los móviles",
        f"Imagina una fábrica de papel en Finlandia. {filler}. Nokia.",  # Nokia sale tarde
    )
    assert found["status"] == "warn"
    assert "«nokia»" in found["fix"] and "primeros 45 segundos" in found["fix"]


def test_short_brand_names_count_and_must_appear():
    assert title_brands("¿Por qué cayó Seat? La caída de Nike y Zara") == ["seat", "nike", "zara"]
    opening = "Una tienda gallega abrió en 1975 y cambió la moda para siempre. " * 3
    assert check("Zara: de tienda gallega a imperio", opening)["status"] == "warn"
    assert (
        check("Zara: de tienda gallega a imperio", "Zara abrió en 1975. " + opening)["status"]
        == "ok"
    )


def test_short_titles_or_no_script_are_not_checked():
    assert check("la caída", "Algo") is None
    assert _promise_check({}, "Nokia y BlackBerry") == []
    assert check("Nokia y BlackBerry", "Muy corto.") is None
