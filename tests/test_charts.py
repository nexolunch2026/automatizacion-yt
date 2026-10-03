from PIL import Image

from app import jobs
from app.db import SessionLocal
from app.pipeline import charts
from app.pipeline.charts import ChartPlan, ChartSpec, Point
from tests.test_research import FakeAI
from tests.test_strategy_script import make_project, run_all

PARAGRAPHS = [
    {"id": "a", "text": "En 2007 Nokia tenía el 49,4 % del mercado."},
    {"id": "b", "text": "En 2013 le quedaba apenas un 3 %. Perdió 63.000 millones."},
]


def spec(**kw):
    base = {"paragraph": 2, "kind": "counter", "title": "Lo que perdió", "unit": "millones",
            "points": [Point(label="pérdida", value=63000)]}  # fmt: skip
    return ChartSpec(**{**base, **kw})


def test_numbers_are_found_in_any_spanish_format():
    assert charts.value_in_text(63000, "perdió 63.000 millones")
    assert charts.value_in_text(49.4, "el 49,4 % del mercado")
    assert charts.value_in_text(3, "un 3 %")
    assert not charts.value_in_text(3, "en 2013")  # el 3 de 2013 no cuenta
    assert not charts.value_in_text(64000, "perdió 63.000 millones")


def test_invented_numbers_are_rejected():
    assert charts.validate(spec(), PARAGRAPHS, "")["paragraph_id"] == "b"
    invented = spec(points=[Point(label="pérdida", value=80000)])
    assert charts.validate(invented, PARAGRAPHS, "") is None
    # La cifra puede estar en la investigación
    assert charts.validate(invented, PARAGRAPHS, "pérdidas de 80.000 millones")
    bars = spec(paragraph=1, kind="bars", points=[Point(label="2007", value=49.4),
                                                  Point(label="2013", value=3)])  # fmt: skip
    assert charts.validate(bars, PARAGRAPHS, PARAGRAPHS[1]["text"])["kind"] == "bars"
    assert charts.validate(spec(kind="line"), PARAGRAPHS, "") is None  # pocas cifras
    assert charts.validate(spec(paragraph=9), PARAGRAPHS, "") is None


def test_frames_and_clip(tmp_path):
    points = [{"label": "2007", "value": 49.4}, {"label": "2013", "value": 3}]
    chart = {"kind": "bars", "title": "Cuota de Nokia", "unit": "%", "points": points}
    for kind in ("bars", "line", "counter"):
        data = {**chart, "kind": kind}
        if kind == "line":
            data["points"] = data["points"] + [{"label": "2015", "value": 1}]
        image = charts.preview(data, (320, 180), tmp_path / f"{kind}.png")
        assert Image.open(image).size == (320, 180)
    clip = charts.chart_clip(chart, tmp_path / "g.mp4", (192, 108), 12, 2.0)
    assert clip.stat().st_size > 500
    assert charts.fmt(63000) == "63.000" and charts.fmt(49.4) == "49,4"


class ChartAI(FakeAI):
    def generate_json(self, prompt, schema):
        if schema is ChartPlan:
            return ChartPlan(charts=[
                ChartSpec(paragraph=2, kind="counter", title="Año de la quiebra",
                          points=[Point(label="quiebra", value=2001)]),
                ChartSpec(paragraph=3, kind="counter", title="Inventado",
                          points=[Point(label="x", value=12345)]),
            ])  # fmt: skip
        return super().generate_json(prompt, schema)


def test_storyboard_gets_charts_and_video_renders_them(logged_in, monkeypatch):
    fake = ChartAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    make_project(logged_in, "automatico")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    with SessionLocal() as db:
        board = jobs.get_result(db, 1, "storyboard")
        edit = jobs.get_result(db, 1, "edit")
    charted = [s for s in board["scenes"] if s.get("chart")]
    assert len(charted) == 1 and charted[0]["chart"]["title"] == "Año de la quiebra"
    assert edit["renders"]["preview"]["seconds"] > 0  # el montaje con gráfico funciona

    pid = charted[0]["paragraph_id"]
    page = logged_in.get("/proyectos/1/escenas").text
    assert "Año de la quiebra" in page and "Buscar cifras para gráficos" in page
    image = logged_in.get(f"/proyectos/1/escenas/graficos/{pid}.png")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"

    logged_in.post(f"/proyectos/1/escenas/graficos/{pid}/quitar")
    with SessionLocal() as db:
        assert not any(s.get("chart") for s in jobs.get_result(db, 1, "storyboard")["scenes"])
    assert logged_in.get(f"/proyectos/1/escenas/graficos/{pid}.png").status_code == 404

    logged_in.post("/proyectos/1/escenas/graficos")
    run_all()
    with SessionLocal() as db:
        board2 = jobs.get_result(db, 1, "storyboard")
    assert [s["narration"] for s in board2["scenes"]] == [s["narration"] for s in board["scenes"]]
    assert sum(1 for s in board2["scenes"] if s.get("chart")) == 1
