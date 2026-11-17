"""«Más historias del canal» en la descripción: enlaces a otros vídeos largos del mismo
canal (primero los parecidos, luego los más vistos), sin Shorts."""

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import Channel, Project, Video, VideoStat
from app.pipeline.end_screen import related_links
from app.pipeline.seo import build_description
from tests.test_projects import create_channel, project_data


def add_video(db, vid, title, project_id=None, views=0, days_ago=1):
    db.add(Video(video_id=vid, title=title, published="2026-10-01", project_id=project_id))
    taken = datetime.now() - timedelta(days=days_ago)
    db.add(VideoStat(video_id=vid, taken_at=taken, views=views))
    db.commit()


def test_similar_first_then_most_viewed_without_shorts(logged_in):
    create_channel(logged_in)
    for topic in ("Kodak: el error de la cámara digital", "Nokia", "Polaroid", "BlackBerry"):
        logged_in.post("/proyectos/nuevo", data=project_data(topic=topic, title=topic))
    with SessionLocal() as db:
        add_video(db, "nokiaaaaaaa", "La caída de Nokia", 2, views=900)
        add_video(db, "polaroidaaa", "Polaroid: la cámara instantánea", 3, views=50)
        add_video(db, "blackberryy", "BlackBerry", 4, views=400)
        add_video(db, "shortkodakk", "Polaroid en 60 segundos #shorts", 3, views=9999)
        add_video(db, "mismokodakk", "Kodak", 1, views=5000)  # el propio vídeo: no
        links = related_links(db, db.get(Project, 1))
    titles = [x["title"] for x in links]
    assert titles == ["Polaroid: la cámara instantánea", "La caída de Nokia", "BlackBerry"]
    assert links[0]["url"] == "https://youtu.be/polaroidaaa"


def test_other_channels_are_not_linked(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.add(Channel(name="ModoOffside", niche="fútbol", created_by=1))
        db.commit()
        db.add(Project(channel_id=2, title="Bale", topic="Bale", duration="10–15 min",
                       language="Español", video_type="Documental", automation_mode="manual",
                       created_by=1))  # fmt: skip
        db.commit()
        add_video(db, "baleaaaaaaa", "Gareth Bale", 2, views=10)
        add_video(db, "sinproyecto", "Vídeo suelto", None, views=10)  # 2 canales: no se sabe
        assert related_links(db, db.get(Project, 1)) == []


def test_description_section():
    related = [{"title": "La caída de Nokia", "url": "https://youtu.be/nokiaaaaaaa"}]
    text = build_description("Intro.", [], {}, "", [], False, "", related)
    assert "▶️ Más historias del canal\n- La caída de Nokia: https://youtu.be/nokiaaaaaaa" in text
    assert "Más historias" not in build_description("Intro.", [], {}, "", [], False)


def test_short_projects_and_stale_videos_are_left_out(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Nokia", title="Nokia",
                                                         duration="Short"))  # fmt: skip
    with SessionLocal() as db:
        add_video(db, "nokiashortt", "La caída de Nokia", 2, views=900)  # Short sin «#shorts»
        add_video(db, "privadoaaaa", "Polaroid", None, views=500, days_ago=40)  # ya no sale
        add_video(db, "buenoaaaaaa", "Yahoo <2000>\nla caída", None, views=10)
        links = related_links(db, db.get(Project, 1))
    assert [x["url"] for x in links] == ["https://youtu.be/buenoaaaaaa"]
    text = build_description("Intro.", [], {}, "", [], False, "", links)
    assert "- Yahoo 2000 la caída: https://youtu.be/buenoaaaaaa" in text


def test_program_made_shorts_and_long_descriptions(logged_in):
    from app.models import StageResult
    from app.pipeline.monetization import _own_description

    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        shorts = {"shorts": [{"title": "El día que Kodak lo perdió todo"}]}
        db.add(StageResult(project_id=1, stage="shorts", data=shorts))
        db.commit()
        add_video(db, "shortkodak1", "El día que Kodak lo perdió todo", None, views=9000)
        add_video(db, "largonokia1", "La caída de Nokia", None, views=10)
        links = related_links(db, db.get(Project, 1))
    assert [x["url"] for x in links] == ["https://youtu.be/largonokia1"]
    related = [{"title": "La masacre de los precios", "url": "https://youtu.be/x"}]
    text = build_description("Intro.", [], {}, "", ["#kodak"], True, "Voz: X", related)
    assert "masacre" not in _own_description(text)  # no es texto de este vídeo
    intro = "x" * 4850  # cabe sin los enlaces, pero no con ellos
    long = build_description(intro, [], {}, "", ["#kodak"], True, "Voz: X", related)
    assert "Más historias" not in long and long.endswith("#kodak") and "Voz: X" in long
