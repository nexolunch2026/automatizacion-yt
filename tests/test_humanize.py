from app.pipeline.humanize import humanize_instruction, paragraph_issues, script_issues
from app.pipeline.monetization import _audience_checks
from tests.test_strategy_script import ai, with_script  # noqa: F401

LONG = " ".join(f"w{i}" for i in range(35)) + "."  # 35 palabras distintas
GOOD = "Nike nació en 1964. Phil Knight vendía zapatillas desde su coche."


def script(*texts: str) -> dict:
    paragraphs = [{"id": f"p{i}", "text": t} for i, t in enumerate(texts)]
    return {"sections": [{"kind": "development", "title": "", "paragraphs": paragraphs}]}


def kinds(text: str) -> list[str]:
    return [i["kind"] for i in paragraph_issues(text)]


def test_clean_paragraph_has_no_issues():
    assert paragraph_issues(GOOD) == []


def test_long_sentence_is_flagged():
    issues = paragraph_issues(f"Empieza bien. {LONG}")
    assert [i["kind"] for i in issues] == ["long"]
    assert issues[0]["text"] == LONG and "35 palabras" in issues[0]["detail"]


def test_repeated_word_is_flagged_but_common_words_are_not():
    text = "La fábrica creció. La fábrica dudó. Al final la fábrica cayó porque porque porque sí."
    issues = paragraph_issues(text)
    assert [i["kind"] for i in issues] == ["repeat"]
    assert "«fábrica» se repite 3 veces" in issues[0]["detail"]


def test_filler_is_found_without_accents_and_whole_words():
    assert kinds("Básicamente, la empresa quebró.") == ["filler"]
    assert kinds("Cabe destacar que nadie lo vio venir.") == ["filler"]
    assert kinds("Fue una idea irrealmente buena.") == []  # no es «realmente»


def test_brand_name_from_the_title_is_not_a_repetition():
    text = "Kodak inventó la cámara digital. Kodak la escondió. Al final Kodak quebró."
    assert kinds(text) == ["repeat"]
    assert paragraph_issues(text, {"kodak"}) == []
    found = script_issues({"title": "La caída de Kodak", **script(text)})
    assert found["paragraphs"] == {}
    assert kinds("La empresa creció, la empresa dudó y la empresa cayó.") == []


def test_issues_keep_the_accents_of_the_script():
    issues = paragraph_issues("Básicamente, la decisión fue mala. Otra decisión. Una decisión más.")
    assert [i["text"] for i in issues] == ["decisión", "básicamente"]
    assert "«decisión» se repite 3 veces" in issues[0]["detail"]


def test_script_issues_counts_by_kind():
    found = script_issues(script(GOOD, LONG, "Literalmente todo cambió."))
    assert set(found["paragraphs"]) == {"p1", "p2"}
    assert found["counts"] == {"long": 1, "repeat": 0, "filler": 1}
    assert found["total"] == 3
    assert script_issues(None)["total"] == 0


def test_instruction_only_mentions_flagged_sentences():
    instruction = humanize_instruction(f"Empieza bien. {LONG} Básicamente, eso.")
    assert "SOLO" in instruction
    assert LONG in instruction and "«básicamente»" in instruction
    assert "Empieza bien" not in instruction
    assert "natural" in humanize_instruction(GOOD)


def test_quality_check_warns_when_many_paragraphs_sound_robotic():
    def check(s):
        return next(c for c in _audience_checks({"script": s}) if c["key"] == "human")

    assert check(script(*[GOOD] * 10))["status"] == "ok"
    assert check(script(*[GOOD] * 9, LONG))["status"] == "ok"  # 10 %: se tolera
    bad = check(script(*[GOOD] * 6, LONG, LONG))
    assert bad["status"] == "warn" and "2 párrafos" in bad["title"]


def test_humanize_rewrites_only_that_paragraph(with_script, monkeypatch):  # noqa: F811
    from app import stages_web
    from app.providers.ai import ProviderError
    from tests.test_strategy_script import first_paragraph_id, script_data

    pid = first_paragraph_id()
    with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "save", "text": LONG})
    page = with_script.get("/proyectos/1/guion").text
    assert "Hacerlo más humano" in page and "Frase de 35 palabras" in page
    assert "Guion más humano" in page

    seen = {}

    def fake_rewrite(db, project, research, script, paragraph_id, action, tone):
        seen["action"] = action
        for section in script["sections"]:
            for p in section["paragraphs"]:
                if p["id"] == paragraph_id:
                    p["text"] = "Frase corta. Otra frase corta."
        return script

    def fail(*args):
        raise ProviderError("Google está saturado.")

    monkeypatch.setattr(stages_web, "rewrite_with_ai", fail)
    r = with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "humanize"})
    assert r.status_code == 400 and "Hacerlo más humano" in r.text  # siguen las marcas

    monkeypatch.setattr(stages_web, "rewrite_with_ai", fake_rewrite)
    with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "humanize"})
    assert seen["action"] == "humanize"
    assert script_data()["sections"][1]["paragraphs"][0]["text"] == "Frase corta. Otra frase corta."


def test_rewrite_paragraph_sends_humanize_instruction():
    from types import SimpleNamespace

    from app.pipeline.script import Rewrite, rewrite_paragraph

    class AI:
        def generate_json(self, prompt, model):
            self.prompt = prompt
            return Rewrite(text="Corto.", sources=[])

    fake = AI()
    s = {"title": "T", "sections": script(GOOD, LONG)["sections"]}
    project = SimpleNamespace(language="español")
    out = rewrite_paragraph(project, {}, s, "p1", "humanize", fake)
    assert "Parte en dos o tres frases cortas" in fake.prompt and LONG in fake.prompt
    assert out["sections"][0]["paragraphs"][1]["text"] == "Corto."
    assert out["sections"][0]["paragraphs"][0]["text"] == GOOD
