"""Botón «Comprobar datos con fuentes fiables» (sin internet: web y Gemini simulados)."""

import httpx

from app import factcheck, jobs
from app.db import SessionLocal
from tests.test_assistant import run_all
from tests.test_thumbnail import make_video_project

ARTICLE_EN = (
    "Theranos was a health technology company. It was valued at 9 billion dollars in 2014. "
    "Elizabeth Holmes was sentenced to 135 months in prison. " * 20
)
DOJ = (
    "<html><head><title>Holmes sentenced</title></head><body><p>"
    + (
        "Elizabeth Holmes was sentenced to 135 months in prison for defrauding investors. "
        "Theranos was valued at 9 billion dollars. " * 30
    )
    + "</p><script>var x = 'no';</script></body></html>"
)
REUTERS = (
    "<html><body><p>"
    + ("Theranos, valued at 9 billion dollars in 2014, collapsed. Holmes got 135 months. " * 30)
    + "</p></body></html>"
)


def fake_transport(seen: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "wikipedia.org" in url and "list=search" in url:
            return httpx.Response(200, json={"query": {"search": [{"title": "Theranos"}]}})
        if "wikipedia.org" in url:
            return httpx.Response(200, json={"query": {"pages": [{
                "title": "Theranos", "fullurl": "https://en.wikipedia.org/wiki/Theranos",
                "extract": ARTICLE_EN,
                "extlinks": [
                    {"url": "https://www.justice.gov/holmes"},
                    {"url": "https://www.reuters.com/theranos"},
                    {"url": "https://www.nytimes.com/paywall"},
                    {"url": "https://randomblog.example/opinion"},
                ],
            }]}})  # fmt: skip
        if "justice.gov" in url:
            return httpx.Response(200, text=DOJ, headers={"content-type": "text/html"})
        if "reuters.com" in url:
            return httpx.Response(200, text=REUTERS, headers={"content-type": "text/html"})
        if "nytimes.com" in url:
            return httpx.Response(403, text="paywall")
        if "archive.org/wayback" in url:
            return httpx.Response(200, json={"archived_snapshots": {}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


class FactAI:
    """Gemini simulado: saca 2 datos; el primero lo confirman, el segundo está mal."""

    def __init__(self, paragraph_id=""):
        self.paragraph_id = paragraph_id

    def generate_json(self, prompt, schema):
        if schema is factcheck.Claims:
            return schema(
                subject="Theranos",
                claims=[
                    {"paragraph_id": self.paragraph_id, "text": "Holmes, condenada a 135 meses",
                     "keywords": ["Holmes", "135 months", "sentenced"]},
                    {"paragraph_id": self.paragraph_id, "text": "Theranos valía 10.000 millones",
                     "keywords": ["Theranos", "valued", "billion", "2014"]},
                ],
            )  # fmt: skip
        if schema is factcheck.Verdicts:
            labels, current = {}, 0
            for line in prompt.splitlines():
                line = line.strip()
                if line.startswith("[S"):
                    labels.setdefault(current, []).append(line.split("]")[0] + "]")
                elif line.startswith("DATO "):
                    current = int(line.split()[1].rstrip(":"))
            return schema(
                verdicts=[
                    {"claim": 1, "supports": labels.get(1, []), "contradicts": [],
                     "correction": ""},
                    {"claim": 2, "supports": [], "contradicts": labels.get(2, [])[:1],
                     "correction": "Theranos llegó a valer 9.000 millones de dólares"},
                ]
            )  # fmt: skip
        raise AssertionError(schema)


def test_factcheck_goes_to_original_sources_and_flags_wrong_numbers():
    seen: list[str] = []
    web = factcheck.Web(transport=fake_transport(seen))
    script = {"sections": [{"paragraphs": [{"id": "a1", "text": "Holmes... 10.000 millones"}]}]}
    data = factcheck.run_factcheck(script, "Theranos", [], FactAI("a1"), lambda *_: None, web)
    sites = {s["site"] for s in data["sources"]}
    assert "Departamento de Justicia de EE. UU." in sites and "Reuters" in sites
    assert not any("randomblog" in u for u in seen)  # webs no fiables: ni se abren
    first, second = data["claims"]
    assert first["status"] == "confirmado"  # justice.gov es un documento oficial
    assert second["status"] == "corregir" and "9.000" in second["correction"]
    assert data["summary"]["corregir"] == 1
    described = factcheck.description_sources(data)
    assert described[0]["uri"].startswith("https://www.justice.gov")  # lo oficial, primero


def test_trust_levels_and_link_picking():
    assert factcheck.trust("https://www.sec.gov/x")[0] == 1
    assert factcheck.trust("https://edition.cnn.com/x")[0] == 2
    assert factcheck.trust("https://data.cityofx.gov/x")[0] == 1
    assert factcheck.trust("https://someblog.net/x")[0] == 0
    links = [f"https://www.bbc.com/{n}" for n in range(6)] + ["https://www.uefa.com/a"]
    picked = factcheck.pick_links(links)
    assert picked[0] == "https://www.uefa.com/a" and len(picked) == 1 + factcheck.PER_DOMAIN


def test_decide_needs_two_reliable_sites_or_an_official_one():
    src = [
        {"site": "Wikipedia (en)", "level": 3},
        {"site": "Reuters", "level": 2},
        {"site": "BBC", "level": 2},
        {"site": "UEFA", "level": 1},
    ]
    assert factcheck.decide([0], [], "", src) == "solo_wikipedia"
    assert factcheck.decide([0, 1], [], "", src) == "una_fuente"
    assert factcheck.decide([1, 2], [], "", src) == "confirmado"
    assert factcheck.decide([3], [], "", src) == "confirmado"
    assert factcheck.decide([], [], "", src) == "sin_confirmar"
    # Una «corrección» que dice lo mismo que el guion no cuenta
    claim = "El debut fue contra el Millwall en 2006"
    assert factcheck.decide([], [1], "El debut fue contra el Millwall en 2006.", src, claim) != (
        "corregir"
    )


def test_html_text_skips_scripts():
    title, text = factcheck.html_text(DOJ)
    assert title == "Holmes sentenced" and "var x" not in text and "135 months" in text


def test_script_page_button_and_results(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    page = logged_in.get("/proyectos/1/guion").text
    assert "Comprobar datos con fuentes fiables" in page
    with SessionLocal() as db:
        script = jobs.get_result(db, 1, "script")
    pid = script["sections"][0]["paragraphs"][0]["id"]
    seen: list[str] = []
    normal_ai = jobs.get_ai_provider
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: FactAI(pid))
    real_web = factcheck.Web(transport=fake_transport(seen))
    monkeypatch.setattr(factcheck, "Web", lambda: real_web)

    logged_in.post("/proyectos/1/guion/comprobar")
    run_all()
    page = logged_in.get("/proyectos/1/guion").text
    assert "1 confirmados" in page and "Revisar: una fuente dice otra cosa" in page
    assert "9.000 millones" in page and "Departamento de Justicia" in page

    # Los textos de Publicación usan ya las fuentes originales
    monkeypatch.setattr(jobs, "get_ai_provider", normal_ai)
    logged_in.post("/proyectos/1/etapas/publish")
    run_all()
    with SessionLocal() as db:
        description = jobs.get_result(db, 1, "publish")["description"]
    assert "justice.gov" in description


def test_factcheck_cannot_be_started_as_a_stage(logged_in):
    from tests.test_projects import create_channel

    create_channel(logged_in)
    assert logged_in.post("/proyectos/1/etapas/factcheck").status_code == 404
