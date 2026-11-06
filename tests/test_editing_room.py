from app import editing_room


def results(with_second_image=True):
    items = {"p1": {"file": "001.jpg", "provider": "flow"}}
    if with_second_image:
        items["p2"] = {"file": "002.jpg", "provider": "flow"}
    return {
        "storyboard": {
            "scenes": [
                {"number": 1, "paragraph_id": "p1", "narration": "Primera  escena.", "seconds": 5},
                {"number": 2, "paragraph_id": "p2", "narration": "Segunda.", "seconds": 5},
            ]
        },
        "voice": {
            "takes": [{"paragraph_id": "p1", "seconds": 3}, {"paragraph_id": "p2", "seconds": 9}]
        },
        "visuals": {"items": items},
    }


def test_timeline_uses_real_voice_times(tmp_path, monkeypatch):
    monkeypatch.setattr(editing_room, "project_dir", lambda pid: tmp_path)
    t = editing_room.timeline(7, results())
    first, second = t["scenes"]
    assert (first["start"], second["start"]) == (0, 3)
    assert (first["width"], second["width"]) == (25.0, 75.0)
    assert first["img"] == "/proyectos/7/archivos/visuales/001.jpg"
    assert first["text"] == "Primera escena."
    assert t["total"] == "0:12" and t["wave"] == []  # sin narracion.wav no hay onda


def test_copilot_warns_about_missing_and_repeated_images(tmp_path, monkeypatch):
    monkeypatch.setattr(editing_room, "project_dir", lambda pid: tmp_path)
    tips = editing_room.copilot(7, results(with_second_image=False), None)
    assert tips[0]["level"] == "fail" and "escenas 2" in tips[0]["text"]

    (tmp_path / "visuales").mkdir()
    (tmp_path / "visuales" / "001.jpg").write_bytes(b"x" * 10)
    (tmp_path / "visuales" / "002.jpg").write_bytes(b"y" * 10)  # mismo tamaño: repetida
    tips = editing_room.copilot(7, results(), None)
    assert tips[0]["level"] == "warn" and "(2)" in tips[0]["text"]
