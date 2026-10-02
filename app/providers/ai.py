"""Interfaz de IA y su implementación con Gemini.

El resto de la app solo conoce `AIProvider`; cambiar de proveedor (Claude, OpenAI…)
consiste en añadir otra clase que cumpla la misma interfaz.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """Error de un proveedor externo con un mensaje entendible para el usuario.

    `transient=True` significa que tiene sentido reintentar (límite de uso, servicio caído…).
    """

    def __init__(self, message: str, *, transient: bool = False, detail: str = ""):
        super().__init__(message)
        self.transient = transient
        self.detail = detail  # mensaje original del proveedor, para diagnosticar


@dataclass
class Source:
    title: str
    uri: str


@dataclass
class GroundedText:
    """Texto respaldado por búsquedas web. Las citas aparecen como [n] (n empieza en 1)."""

    text: str
    sources: list[Source] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    name: str

    def grounded_research(self, prompt: str) -> GroundedText: ...

    def generate_json(self, prompt: str, schema: type[T]) -> T: ...


# ---------------------------------------------------------------- Gemini

FALLBACK_MODEL = "gemini-flash-latest"
# Alias que Google mantiene apuntando a su Flash actual; suelen tener nivel gratuito.
ALIASES = ["gemini-flash-latest", "gemini-flash-lite-latest"]
_EXCLUDED = ("exp", "tts", "image", "live", "audio", "embedding", "thinking", "computer")
_FLASH = re.compile(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?(-preview(?:-[\w-]+)?)?")


def candidate_models(model_names: list[str], preferred: str | None = None) -> list[str]:
    """Ordena los modelos Flash disponibles para probarlos uno tras otro:
    el que ya funcionó antes, los alias «latest», los estables (del más nuevo al más
    antiguo, «lite» después) y por último las versiones «preview»."""
    names = [n.removeprefix("models/") for n in model_names]
    ranked = []
    for name in names:
        if any(word in name for word in _EXCLUDED):
            continue
        if name in ALIASES:
            ranked.append(((0, -ALIASES.index(name)), name))
            continue
        match = _FLASH.fullmatch(name)
        if match:
            is_preview = match.group(3) is not None
            is_full = match.group(2) is None
            ranked.append(((-1 if is_preview else -0.5, float(match.group(1)), is_full), name))
    ordered = [name for _, name in sorted(ranked, reverse=True)]
    if preferred and preferred in names:
        ordered = [preferred] + [n for n in ordered if n != preferred]
    return ordered or [FALLBACK_MODEL]


def pick_flash_model(model_names: list[str]) -> str:
    return candidate_models(model_names)[0]


def insert_citations(text: str, supports) -> str:
    """Inserta marcas [n] en el texto según los fragmentos respaldados por cada fuente.

    Gemini indica dónde termina cada fragmento en bytes UTF-8, así que se trabaja en bytes.
    """
    raw = text.encode("utf-8")
    inserts: dict[int, set[int]] = {}
    for support in supports or []:
        segment = getattr(support, "segment", None)
        indices = getattr(support, "grounding_chunk_indices", None) or []
        if segment is None or segment.end_index is None or not indices:
            continue
        end = min(segment.end_index, len(raw))
        inserts.setdefault(end, set()).update(i + 1 for i in indices)
    for end in sorted(inserts, reverse=True):
        marks = "".join(f"[{n}]" for n in sorted(inserts[end]))
        raw = raw[:end] + marks.encode() + raw[end:]
    return raw.decode("utf-8", errors="ignore")


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None, preferred: str | None = None):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._models = [model] if model else None
        self._preferred = preferred  # el modelo que funcionó la última vez
        self.last_model: str | None = None  # modelo que respondió la última vez

    @property
    def models(self) -> list[str]:
        if self._models is None:
            names = self._call(lambda: [m.name for m in self._client.models.list()])
            self._models = candidate_models(names, self._preferred)
        return self._models

    def check(self) -> str:
        """Comprueba que la clave funciona. Devuelve el primer modelo que se probará."""
        return self.models[0]

    def _generate(self, contents: str, config):
        """Prueba los modelos en orden. Si uno no tiene cuota gratuita o no existe, pasa al
        siguiente y recuerda el que funcionó para las próximas llamadas."""
        last_error: ProviderError | None = None
        for model in list(self.models):
            try:
                response = self._call(
                    lambda m=model: self._client.models.generate_content(
                        model=m, contents=contents, config=config
                    )
                )
            except ModelUnavailable as exc:
                last_error = exc.error
                continue
            if self._models[0] != model:  # pone delante el que funciona
                self._models.remove(model)
                self._models.insert(0, model)
            self.last_model = model
            return response
        raise last_error or ProviderError("No hay ningún modelo de Gemini disponible.")

    def diagnose(self, max_models: int = 8) -> list[dict]:
        """Busca el primer modelo que funcione para texto y prueba con él la búsqueda de
        Google. Deja ese modelo en `last_model` para poder recordarlo."""
        from google.genai import types

        def attempt(model, config=None) -> ProviderError | None:
            try:
                self._call(
                    lambda: self._client.models.generate_content(
                        model=model, contents="Responde solo: OK", config=config
                    )
                )
                return None
            except ModelUnavailable as exc:
                return exc.error
            except ProviderError as exc:
                return exc

        def failed(name, error):
            return {"name": name, "ok": False, "message": str(error), "detail": error.detail}

        try:
            models = self.models
        except ProviderError as exc:
            return [failed("Clave de Gemini", exc)]
        results = [{"name": "Clave de Gemini", "ok": True, "message": "Válida"}]

        working = None
        for model in models[:max_models]:
            error = attempt(model)
            if error is None:
                working = model
                results.append({"name": f"{model} — texto", "ok": True, "message": "Funciona"})
                break
            results.append(failed(f"{model} — texto", error))
            if "clave" in str(error):
                return results
        if working is None:
            return results

        self.last_model = working
        search = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        error = attempt(working, search)
        name = f"{working} — búsqueda de Google"
        results.append(
            {"name": name, "ok": True, "message": "Funciona"}
            if error is None
            else failed(name, error)
        )
        return results

    def grounded_research(self, prompt: str) -> GroundedText:
        from google.genai import types

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        )
        response = self._generate(prompt, config)
        if not response.candidates:
            raise ProviderError("Gemini no devolvió respuesta. Prueba de nuevo.", transient=True)

        metadata = response.candidates[0].grounding_metadata
        chunks = (metadata.grounding_chunks if metadata else None) or []
        sources = [
            Source(title=(c.web.title or c.web.domain or c.web.uri), uri=c.web.uri)
            for c in chunks
            if c.web and c.web.uri
        ]
        text = response.text or ""
        supports = metadata.grounding_supports if metadata else None
        return GroundedText(
            text=insert_citations(text, supports) if sources else text,
            sources=sources,
            queries=list((metadata.web_search_queries if metadata else None) or []),
        )

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.3,
        )
        response = self._generate(prompt, config)
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise ProviderError(
                "La IA devolvió un formato inesperado. Se volverá a intentar.", transient=True
            ) from exc

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        """Pasa a texto una nota de voz (por ejemplo, las que llegan por Telegram)."""
        from google.genai import types

        contents = [
            types.Part.from_bytes(data=audio, mime_type=mime_type),
            "Transcribe exactamente lo que dice este audio, en su idioma. "
            "Responde solo con la transcripción.",
        ]
        response = self._generate(contents, types.GenerateContentConfig(temperature=0))
        return (response.text or "").strip()

    @staticmethod
    def _call(fn):
        from google.genai import errors

        try:
            return fn()
        except errors.APIError as exc:
            quotas = quota_violations(exc.details)
            detail = f"{exc.code} {exc.status}: {exc.message}"
            if quotas:
                detail += " | Cuotas: " + "; ".join(
                    f"{q['id']} (límite {q['value']})" if q["value"] else q["id"] for q in quotas
                )
            error = _friendly_error(exc.code, str(exc), detail[:600], quotas)
            # Sin cuota (429), inexistente (404) o saturado (500/503): probar otro modelo.
            if exc.code in (404, 429, 500, 503):
                raise ModelUnavailable(error) from exc
            raise error from exc
        except OSError as exc:  # sin conexión, DNS, timeout…
            raise ProviderError(
                "No hay conexión con Google. Revisa tu internet.", transient=True, detail=str(exc)
            ) from exc


class ModelUnavailable(Exception):
    """Uso interno: este modelo no se puede usar ahora; hay que probar el siguiente."""

    def __init__(self, error: ProviderError):
        super().__init__(str(error))
        self.error = error


def quota_violations(details) -> list[dict]:
    """Extrae qué cuota se agotó (por día, por minuto…) de la respuesta de error de Google."""
    found = []
    error = details.get("error", {}) if isinstance(details, dict) else {}
    for item in error.get("details") or []:
        for violation in (item or {}).get("violations") or []:
            quota_id = violation.get("quotaId") or violation.get("quotaMetric")
            if quota_id:
                found.append({"id": quota_id, "value": str(violation.get("quotaValue") or "")})
    return found


def _friendly_error(
    code: int | None, raw: str, detail: str = "", quotas: list[dict] | None = None
) -> ProviderError:
    detail = detail or raw[:400]
    quotas = quotas or []
    if code in (400, 401, 403) and ("API key" in raw or "API_KEY" in raw or code != 400):
        return ProviderError(
            "La clave de Gemini no es válida. Revísala en Configuración.", detail=detail
        )
    if code == 429:
        ids = " ".join(q["id"] for q in quotas)
        if re.search(r"limit: 0\b", raw) or any(q["value"] == "0" for q in quotas):
            return ProviderError(
                "Tu cuenta de Gemini no tiene uso gratuito para esta función.", detail=detail
            )
        if "PerDay" in ids or "PerDay" in raw or "per day" in raw.lower():
            return ProviderError(
                "Se agotó el uso gratuito de Gemini de hoy. Vuelve a intentarlo mañana.",
                detail=detail,
            )
        if "PerMinute" in ids or "per minute" in raw.lower():
            return ProviderError(
                "Se alcanzó el límite por minuto de Gemini. Se reintentará en un momento.",
                transient=True,
                detail=detail,
            )
        return ProviderError(
            "Google no permite más peticiones gratuitas con tu cuenta ahora mismo.", detail=detail
        )
    if code == 404:
        return ProviderError("Ese modelo de Gemini no está disponible.", detail=detail)
    if code is not None and code >= 500:
        return ProviderError(
            "Google está saturado en este momento. Se volverá a intentar en unos minutos.",
            transient=True,
            detail=detail,
        )
    return ProviderError(f"Error de Gemini ({code}).", detail=detail)
