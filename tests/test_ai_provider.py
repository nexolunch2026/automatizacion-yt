from types import SimpleNamespace as N

from app.providers.ai import FALLBACK_MODEL, _friendly_error, insert_citations, pick_flash_model


def test_pick_latest_stable_flash():
    names = [
        "models/gemini-2.5-flash",
        "models/gemini-3.5-flash",
        "models/gemini-3.5-flash-lite",
        "models/gemini-4-flash-preview",
        "models/gemini-3.1-pro",
        "models/gemini-2.5-flash-preview-tts",
    ]
    assert pick_flash_model(names) == "gemini-3.5-flash"
    assert pick_flash_model([]) == FALLBACK_MODEL


def test_insert_citations_uses_utf8_byte_offsets():
    text = "Año 1998: Enron cayó. Más datos."
    end = len("Año 1998: Enron cayó.".encode())
    supports = [
        N(segment=N(end_index=end), grounding_chunk_indices=[2, 0]),
        N(segment=N(end_index=len(text.encode())), grounding_chunk_indices=[1]),
        N(segment=None, grounding_chunk_indices=[0]),
    ]
    assert insert_citations(text, supports) == "Año 1998: Enron cayó.[1][3] Más datos.[2]"


def test_friendly_errors():
    assert not _friendly_error(400, "API key not valid").transient
    assert "clave" in str(_friendly_error(403, "forbidden"))
    assert _friendly_error(429, "quota").transient
    assert _friendly_error(503, "unavailable").transient
