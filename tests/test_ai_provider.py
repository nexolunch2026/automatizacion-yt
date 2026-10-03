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
    quota_violations,
)


def test_model_order():
    names = [
        "models/gemini-2.5-flash",
        "models/gemini-3.5-flash",
        "models/gemini-3.5-flash-lite",
        "models/gemini-2.5-flash-lite",
        "models/gemini-4-flash-preview",
        "models/gemini-flash-latest",
        "models/gemini-flash-lite-latest",
        "models/gemini-3.1-pro",
        "models/gemini-2.5-flash-preview-tts",
        "models/gemini-2.5-flash-image",
    ]
    assert candidate_models(names) == [
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-4-flash-preview",
    ]
    # El que funcionó la última vez va primero (si sigue existiendo).
    assert candidate_models(names, preferred="gemini-3.5-flash-lite")[0] == "gemini-3.5-flash-lite"
    assert candidate_models(names, preferred="gemini-1-flash")[0] == "gemini-flash-latest"
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

    # Sin información de qué cuota es: no se reintenta en bucle.
    generic = _friendly_error(429, "You exceeded your current quota, please check your plan")
    assert not generic.transient


def test_quota_details_are_extracted_and_classified():
    details = {
        "error": {
            "code": 429,
            "details": [
                {"@type": "type.googleapis.com/google.rpc.Help"},
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                            "quotaValue": "10",
                        }
                    ],
                },
            ],
        }
    }
    quotas = quota_violations(details)
    assert quotas == [{"id": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "value": "10"}]
    assert _friendly_error(429, "quota", quotas=quotas).transient
    assert quota_violations(None) == []


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
        {"gemini-3.5-flash": quota_error("gemini-3.5-flash")},
    )
    provider = provider_with(fake)
    result = provider.grounded_research("tema")
    assert result.text == '{"x": 1}'
    assert provider.last_model == "gemini-2.5-flash"
    # La siguiente llamada va directamente al modelo que funcionó.
    provider.grounded_research("tema")
    assert fake.calls == ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash"]


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
    fake = FakeModels(["gemini-2.5-flash", "gemini-3.5-flash"], {"gemini-3.5-flash": bad_key})
    with pytest.raises(ProviderError) as info:
        provider_with(fake).grounded_research("tema")
    assert "clave" in str(info.value)
    assert fake.calls == ["gemini-3.5-flash"]


def not_found(model):
    return errors.APIError(
        404, {"error": {"code": 404, "message": f"{model} is not found", "status": "NOT_FOUND"}}
    )


def test_diagnose_finds_first_working_model():
    class SearchBlocked(FakeModels):
        def generate_content(self, model, contents, config):
            if config is not None:  # la búsqueda de Google no tiene cuota
                raise quota_error(model)
            return super().generate_content(model, contents, config)

    old_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    fake = SearchBlocked(
        ["gemini-3.5-flash", *old_models], {"gemini-3.5-flash": not_found("gemini-3.5-flash")}
    )
    provider = provider_with(fake)
    results = provider.diagnose()
    assert [(r["name"], r["ok"]) for r in results] == [
        ("Clave de Gemini", True),
        ("gemini-3.5-flash — texto", False),
        ("gemini-2.5-flash — texto", True),
        ("gemini-2.5-flash — búsqueda de Google", False),
    ]
    assert provider.last_model == "gemini-2.5-flash"
    assert "limit: 0" in results[3]["detail"]


def test_diagnose_when_no_model_works():
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    provider = provider_with(FakeModels(models, {m: not_found(m) for m in models}))
    results = provider.diagnose()
    assert [r["ok"] for r in results] == [True, False, False]
    assert provider.last_model is None


def test_overloaded_model_tries_the_next_one():
    overloaded = errors.APIError(
        503,
        {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}},
    )
    fake = FakeModels(
        ["gemini-2.5-flash", "gemini-2.5-flash-lite"], {"gemini-2.5-flash": overloaded}
    )
    provider = provider_with(fake)
    provider.grounded_research("tema")
    assert provider.last_model == "gemini-2.5-flash-lite"


def test_all_models_overloaded_is_retryable():
    overloaded = errors.APIError(
        503,
        {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}},
    )
    fake = FakeModels(["gemini-2.5-flash"], {"gemini-2.5-flash": overloaded})
    with pytest.raises(ProviderError) as info:
        provider_with(fake).grounded_research("tema")
    assert info.value.transient
    assert "saturado" in str(info.value)


def test_model_list_is_asked_once_per_key(monkeypatch):
    from app.providers import ai as ai_module

    calls = []

    class Models:
        def list(self):
            calls.append(1)
            return [N(name="models/gemini-flash-latest")]

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    monkeypatch.setattr("google.genai.Client", Client)
    for _ in range(3):
        assert ai_module.GeminiProvider("clave-1").models[0] == "gemini-flash-latest"
    assert ai_module.GeminiProvider("clave-2").models
    assert len(calls) == 2  # una vez por clave, no en cada mensaje


def test_quick_json_turns_thinking_off_and_falls_back(monkeypatch):
    from pydantic import BaseModel

    from app.providers import ai as ai_module

    class Answer(BaseModel):
        ok: bool

    seen = []

    def generate(self, contents, config):
        budget = config.thinking_config.thinking_budget if config.thinking_config else None
        seen.append(budget)
        if budget == 0 and len(seen) == 1:
            raise ai_module.ProviderError("Error de Gemini (400).", detail="thinking not supported")
        return N(parsed=Answer(ok=True), text='{"ok": true}')

    monkeypatch.setattr(ai_module.GeminiProvider, "_generate", generate)
    provider = ai_module.GeminiProvider.__new__(ai_module.GeminiProvider)
    assert provider.quick_json("hola", Answer).ok
    assert seen == [0, None]  # primero sin pensar; si el modelo no lo admite, normal
