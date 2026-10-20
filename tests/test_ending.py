from app.pipeline.monetization import _audience_checks, farewell_tail

STORY = "Kodak inventó la cámara digital en 1975 y la guardó en un cajón por miedo."
LONG_BYE = (
    "Y hasta aquí la historia de hoy. Si te ha gustado, suscríbete y activa la campanita. "
    "Dale a like y comparte este vídeo con tus amigos, que nos ayuda mucho a seguir. "
    "No olvides comentar qué marca quieres que contemos la próxima semana en el canal. "
    "Muchas gracias por ver el vídeo hasta el final. Nos vemos en el próximo, adiós."
)
NEXT = "Y si quieres otra historia, te dejo aquí en pantalla «La caída de Nokia». Nos vemos allí."


def script(*texts: str) -> dict:
    paragraphs = [{"id": f"p{i}", "text": t} for i, t in enumerate(texts)]
    return {"sections": [{"kind": "cta", "title": "", "paragraphs": paragraphs}]}


def check(s):
    return next(c for c in _audience_checks({"script": s}) if c["key"] == "ending")


def test_long_goodbye_at_the_end_warns():
    seconds, leads = farewell_tail(script(STORY, LONG_BYE))
    assert seconds > 12 and not leads
    found = check(script(STORY, LONG_BYE))
    assert found["status"] == "warn" and found["title"].startswith("Despedida de ")
    assert "Pantalla final" in found["fix"] and found["link"] == "guion"


def test_ending_that_leads_to_another_video_is_ok():
    seconds, leads = farewell_tail(script(STORY, NEXT))
    assert leads and seconds < 2
    found = check(script(STORY, NEXT))
    assert found["status"] == "ok" and "otro vídeo" in found["title"]


def test_story_ending_without_goodbye_is_ok():
    assert farewell_tail(script(STORY)) == (0.0, False)
    assert check(script(STORY))["title"] == "Final sin despedida larga"


def test_goodbye_in_the_middle_does_not_count():
    assert farewell_tail(script(LONG_BYE, STORY)) == (0.0, False)


def test_one_short_goodbye_is_fine():
    assert check(script(STORY, "Suscríbete si te gustó."))["status"] == "ok"


def test_accents_and_whole_words():
    bye = "Gracias por ver. Adiós. Nos vemos. Suscríbete. Chao. Hasta la próxima. Adios."
    assert farewell_tail(script(STORY, bye))[0] > 4
    story = "El chaos de 2008 hundió a Chaoyang Motors y su dueño suscribió un préstamo."
    assert farewell_tail(script(story)) == (0.0, False)


def test_story_sentences_that_sound_like_goodbye_do_not_count():
    end = (
        "Eso es todo lo que Kodak tenía. Y hasta aquí llegó la empresa. Pero esa es otra historia."
    )
    assert farewell_tail(script(STORY, end)) == (0.0, False)
    long_story = (
        "Gracias por ver aquel anuncio, millones de personas compraron una cámara que la "
        "empresa ya sabía que estaba condenada a desaparecer en menos de diez años."
    )
    assert farewell_tail(script(long_story))[0] == 0


def test_partial_scripts_do_not_break_the_review():
    broken = {"sections": [{"kind": "cta"}, {"paragraphs": [{"id": "p0"}, {"text": None}]}]}
    assert farewell_tail(broken) is None
    empty = script("", "  ")
    assert not [c for c in _audience_checks({"script": empty}) if c["key"] == "ending"]


def test_no_script_no_check():
    assert not [c for c in _audience_checks({}) if c["key"] == "ending"]
    assert not [c for c in _audience_checks({"script": {"sections": []}}) if c["key"] == "ending"]
