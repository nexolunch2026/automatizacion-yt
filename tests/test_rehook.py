from app.pipeline.monetization import REHOOK_MAX_SECONDS, _audience_checks, rehook_gap


def para(words: int, end: str = ".") -> dict:
    return {"id": "x", "text": " ".join(["palabra"] * words) + end}


def script(*sections):
    return {"sections": [{"kind": k, "title": k, "paragraphs": ps} for k, ps in sections]}


def test_short_videos_are_not_checked():
    assert rehook_gap(script(("development", [para(200)]))) is None  # 80 s


def test_finds_the_longest_stretch_without_rehooks():
    s = script(
        ("hook", [para(100, "?")]),  # pregunta a los 40 s
        ("development", [para(250), para(250), para(100, ". Lo peor estaba por llegar.")]),
        ("development", [para(150, "?")]),
        ("conclusion", [para(500)]),  # el final no cuenta
    )
    start, end = rehook_gap(s)
    assert start == 40 and end == 282  # 4 minutos sin enganchar (la frase suma 5 palabras)
    check = next(c for c in _audience_checks({"script": s}) if c["key"] == "rehook")
    assert check["status"] == "warn" and "0:40 a 4:42" in check["title"]


def test_well_spaced_rehooks_pass():
    s = script(("development", [para(150, "?") for _ in range(6)]))  # cada 60 s
    start, end = rehook_gap(s)
    assert end - start <= REHOOK_MAX_SECONDS
    check = next(c for c in _audience_checks({"script": s}) if c["key"] == "rehook")
    assert check["status"] == "ok"
