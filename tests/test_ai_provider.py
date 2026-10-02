from types import SimpleNamespace as N

import pytest
from google.genai import errors

from app.providers.ai import (
    FALLBACK_MODEL,
    GeminiProvider,
    ProviderError,
    _friendly_error,
    candidate_models,
    insert_citations,
    pick_flash_model,
)


def test_free_models_first_then_newest():
    names = [
        "models/gemini-2.5-flash",
        "models/gemini-3.5-flash",
        "models/gemini-3.5-flash-lite",
        "models/gemini-2.5-flash-lite",
        "models/gemini-4-flash-preview",
        "models/gemini-3.1-pro",
        "models/gemini-2.5-flash-preview-tts",
    ]
    assert candidate_models(names) == [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    assert pick_flash_model(["models/gemini-3.5-flash"]) == "gemini-3.5-flash"
    assert candidate_models([]) == [FALLBACK_MODEL]


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
    assert _friendly_error(429, "Quota exceeded per minute").transient
    assert _friendly_error(503, "unavailable").transient

    no_free = _friendly_error(429, "Quota exceeded. limit: 0, model: gemini-3.5-flash")
    assert not no_free.transient
    assert "gratuito" in str(no_free)

    daily = _friendly_error(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier limit: 20")
    assert not daily.transient
    assert "mañana" in str(daily)


def quota_error(model, limit=0):
    message = f"You exceeded your current quota. limit: {limit}, model: {model}"
    return errors.APIError(
        429, {"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}}
    )


class FakeModels:
    def __init__(self, available, failing):
        self.available = available
        self.failing = failing  # modelo -> excepción
        self.calls = []

    def list(self):
        return [N(name=f"models/{m}") for m in self.available]

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if model in self.failing:
            raise self.failing[model]
        return N(candidates=[N(grounding_metadata=None)], text='{"x": 1}', parsed=None)


def provider_with(fake):
    provider = GeminiProvider("clave-falsa")
    provider._client = N(models=fake)
    return provider


def test_falls_back_to_next_model_without_free_quota():
    fake = FakeModels(
        ["gemini-2.5-flash", "gemini-3.5-flash"],
        {"gemini-2.5-flash": quota_error("gemini-2.5-flash")},
    )
    provider = provider_with(fake)
    result = provider.grounded_research("tema")
    assert result.text == '{"x": 1}'
    assert provider.last_model == "gemini-3.5-flash"
    # La siguiente llamada va directamente al modelo que funcionó.
    provider.grounded_research("tema")
    assert fake.calls == ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.5-flash"]


def test_all_models_without_quota_gives_clear_error_with_detail():
    fake = FakeModels(
        ["gemini-2.5-flash", "gemini-3.5-flash"],
        {m: quota_error(m) for m in ["gemini-2.5-flash", "gemini-3.5-flash"]},
    )
    with pytest.raises(ProviderError) as info:
        provider_with(fake).grounded_research("tema")
    assert "gratuito" in str(info.value)
    assert "limit: 0" in info.value.detail
    assert not info.value.transient


def test_invalid_key_does_not_try_other_models():
    bad_key = errors.APIError(
        400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}}
    )
    fake = FakeModels(["gemini-2.5-flash", "gemini-3.5-flash"], {"gemini-2.5-flash": bad_key})
    with pytest.raises(ProviderError) as info:
        provider_with(fake).grounded_research("tema")
    assert "clave" in str(info.value)
    assert fake.calls == ["gemini-2.5-flash"]
