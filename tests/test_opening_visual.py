from app.pipeline.monetization import _audience_checks, _opening_visual_check


def results(kind, seconds=10.0):
    return {
        "storyboard": {"scenes": [
            {"number": 2, "paragraph_id": "p2", "seconds": 30},
            {"number": 1, "paragraph_id": "p1", "seconds": seconds},
        ]},
        "visuals": {"items": {"p1": {"kind": kind}, "p2": {"kind": "card"}}},
    }  # fmt: skip


def check(data):
    found = [c for c in _audience_checks(data) if c["key"] == "opening_visual"]
    return found[0] if found else None


def test_image_opening_is_ok_because_it_is_split_into_short_shots():
    assert check(results("image", 20))["status"] == "ok"  # 20 s → planos de 5 s


def test_text_card_or_long_stock_clip_at_the_start_warns():
    card = check(results("card"))
    assert card["status"] == "warn" and "tarjeta" in card["title"] and card["link"] == "visuales"
    clip = check(results("video", 14))
    assert clip["status"] == "warn" and "14 s" in clip["title"]
    assert check(results("video", 6))["status"] == "ok"


def test_chart_or_missing_visual_at_the_start():
    chart = results("card", 12)
    chart["storyboard"]["scenes"][1]["chart"] = {"type": "bar"}
    found = check(chart)
    assert found["status"] == "warn" and "gráfico" in found["fix"]  # un solo plano de 12 s
    missing = results("image")
    del missing["visuals"]["items"]["p1"]  # el montaje pondría una tarjeta de texto
    assert "tarjeta" in check(missing)["title"]
    long_image = check(results("image", 40))  # 4 planos de 10 s
    assert long_image["status"] == "warn" and "acorta el primer párrafo" in long_image["fix"]


def test_nothing_to_say_without_visuals_or_odd_data():
    assert check({}) is None
    assert (
        check({"storyboard": {"scenes": [{"number": 1, "paragraph_id": "p1", "seconds": 5}]}})
        is None
    )
    odd = results("image")
    odd["storyboard"]["scenes"][1]["seconds"] = "x"
    assert _opening_visual_check(odd) == []  # sin duración no se dice «bien»
    odd["storyboard"]["scenes"][1] |= {"seconds": 5, "number": "uno"}
    assert _opening_visual_check(odd)[0]["status"] == "warn"  # «p2» (tarjeta) va primero
    assert _opening_visual_check({"storyboard": {"scenes": [None]}, "visuals": {"items": []}}) == []
