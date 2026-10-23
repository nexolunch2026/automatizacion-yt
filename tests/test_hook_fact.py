import pytest

from app.pipeline.monetization import _audience_checks, first_sentence, is_concrete


def script(*texts):
    paragraphs = [{"id": f"p{i}", "text": t} for i, t in enumerate(texts)]
    return {"sections": [{"kind": "hook", "title": "", "paragraphs": paragraphs}]}


def check(s):
    found = [c for c in _audience_checks({"script": s}) if c["key"] == "hook_fact"]
    return found[0] if found else None


@pytest.mark.parametrize(
    "sentence",
    [
        "En 1975, un ingeniero inventó la cámara digital.",
        "Perdieron 63.000 millones de dólares en un año.",
        "Perdieron miles de millones sin que nadie lo viera.",
        "¿Cómo perdió Kodak la cámara digital?",
        "Un ingeniero de Kodak inventó la cámara digital.",
        "Kodak inventó la cámara digital y la escondió.",
        "IBM lo tuvo todo.",
        "El 40 % de sus clientes se fue en un mes.",
    ],
)
def test_concrete_openings(sentence):
    assert is_concrete(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Esta es una historia increíble que te va a sorprender.",
        "Hoy hablamos de una empresa que lo tuvo todo y lo perdió.",
        "Nadie lo vio venir.",
        "¿Alguna vez te has preguntado cómo funciona el mundo?",
        "Dijo: «Nunca más» y se fue.",
        "Esto es increíble, de verdad. ¿Lo sabías?",
    ],
)
def test_vague_openings(sentence):
    assert not is_concrete(sentence)


def test_quality_check_warns_on_vague_first_sentence():
    vague = check(script("Esta es una historia increíble. Kodak inventó la cámara en 1975."))
    assert vague["status"] == "warn" and "Esta es una historia increíble." in vague["detail"]
    assert "dato más sorprendente" in vague["fix"] and vague["link"] == "guion"
    good = check(script("En 1975, Kodak inventó la cámara digital. Y la escondió."))
    assert good["status"] == "ok"


def test_abbreviations_are_not_a_sentence():
    s = script("EE. UU. prohibió la venta de Huawei en 2019. Nadie lo esperaba.")
    assert first_sentence(s) == "EE. UU. prohibió la venta de Huawei en 2019."


def test_first_sentence_skips_empty_paragraphs_and_partial_data():
    s = {"sections": [{"paragraphs": [{"id": "a"}, {"text": "  "}, {"text": "Hola. Adiós."}]}]}
    assert first_sentence(s) == "Hola. Adiós."  # trozos cortos: se juntan
    assert first_sentence({"sections": [{}]}) == ""
    assert check({"sections": [{"kind": "hook", "paragraphs": [{"id": "a", "text": ""}]}]}) is None
