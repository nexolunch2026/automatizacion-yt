from app.pipeline.monetization import _audience_checks, pace_fix, voice_pace
from app.pipeline.voice import take_key

WORDS = " ".join(["palabra"] * 75)  # 75 palabras
VOICE = "es_ES-davefx-medium"


def script(*texts):
    paragraphs = [{"id": f"p{i}", "text": t} for i, t in enumerate(texts)]
    return {"sections": [{"kind": "development", "title": "", "paragraphs": paragraphs}]}


def voice(texts, seconds, speed="Normal", name=VOICE):
    takes = [
        {"paragraph_id": f"p{i}", "key": take_key(t, name, speed), "seconds": s}
        for i, (t, s) in enumerate(zip(texts, seconds, strict=True))
    ]
    return {"voice": name, "speed": speed, "takes": takes}


def check(s, v):
    found = [c for c in _audience_checks({"script": s, "voice": v}) if c["key"] == "pace_voice"]
    return found[0] if found else None


def test_pace_in_words_per_minute():
    assert voice_pace(script(WORDS, WORDS), voice([WORDS, WORDS], [30, 30])) == 150
    assert voice_pace(script(WORDS), voice([WORDS], [10])) is None  # muy poco grabado
    assert voice_pace(script(WORDS), {}) is None
    assert voice_pace(script(WORDS), voice([WORDS], [30], name="en_US-ryan-high")) is None


def test_takes_of_edited_or_removed_paragraphs_do_not_count():
    recorded = voice([WORDS, WORDS, "viejo"], [30, 5, 500])
    edited = script(WORDS, "Ahora este párrafo es otro y aún no se ha grabado.")
    assert voice_pace(edited, recorded) == 150  # solo cuenta p0 (el p1 grabado es viejo)
    assert voice_pace(script(WORDS), recorded) == 150  # «viejo» y p1 ya no están
    assert voice_pace(script(WORDS, WORDS), recorded) == 257  # al día: 150 palabras en 35 s


def test_odd_stored_data_is_ignored():
    good = voice([WORDS, WORDS], [30, 30])
    good["takes"] += [None, {"paragraph_id": ["p0"]}, {"paragraph_id": "p0", "seconds": "x"}]
    assert voice_pace(script(WORDS, WORDS), good) == 150
    broken = {"sections": [None, {"paragraphs": [None, {"id": 3, "text": "x"}]}]}
    assert voice_pace(broken, good) is None
    assert voice_pace(script(WORDS), "error") is None


def test_advice_depends_on_the_current_speed():
    assert "«Lenta»" in pace_fix(220, "Normal") and "«Normal»" in pace_fix(220, "Rápida")
    assert "parte las frases" in pace_fix(220, "Lenta")
    assert "«Rápida»" in pace_fix(100, "Normal") and "quita frases" in pace_fix(100, "Rápida")


def test_quality_check_warns_when_too_fast_or_too_slow():
    normal = check(script(WORDS, WORDS), voice([WORDS, WORDS], [30, 30]))
    assert normal["status"] == "ok" and "150 palabras" in normal["title"]
    fast = check(script(WORDS, WORDS), voice([WORDS, WORDS], [20, 20]))  # 225 por minuto
    assert fast["status"] == "warn" and "deprisa" in fast["title"] and "«Lenta»" in fast["fix"]
    slow = check(script(WORDS, WORDS), voice([WORDS, WORDS], [45, 45]))  # 100 por minuto
    assert slow["status"] == "warn" and "lenta" in slow["title"] and slow["link"] == "voz"
    assert check(script(WORDS), {}) is None  # sin voz no hay aviso
