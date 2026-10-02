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

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


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

FALLBACK_MODEL = "gemini-2.5-flash"
_EXCLUDED = ("preview", "exp", "lite", "tts", "image", "live", "audio", "embedding", "thinking")


def pick_flash_model(model_names: list[str]) -> str:
    """Elige el modelo Flash estable más reciente de los disponibles para la clave."""
    candidates = []
    for name in model_names:
        name = name.removeprefix("models/")
        match = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", name)
        if match and not any(word in name for word in _EXCLUDED):
            candidates.append((float(match.group(1)), name))
    return max(candidates)[1] if candidates else FALLBACK_MODEL


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

    def __init__(self, api_key: str, model: str | None = None):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        if self._model is None:
            names = self._call(lambda: [m.name for m in self._client.models.list()])
            self._model = pick_flash_model(names)
        return self._model

    def check(self) -> str:
        """Comprueba que la clave funciona. Devuelve el modelo que se usará."""
        return self.model

    def grounded_research(self, prompt: str) -> GroundedText:
        from google.genai import types

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        )
        response = self._call(
            lambda: self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        )
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
        response = self._call(
            lambda: self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise ProviderError(
                "La IA devolvió un formato inesperado. Se volverá a intentar.", transient=True
            ) from exc

    @staticmethod
    def _call(fn):
        from google.genai import errors

        try:
            return fn()
        except errors.APIError as exc:
            raise _friendly_error(exc.code, str(exc)) from exc
        except OSError as exc:  # sin conexión, DNS, timeout…
            raise ProviderError(
                "No hay conexión con Google. Revisa tu internet.", transient=True
            ) from exc


def _friendly_error(code: int | None, detail: str) -> ProviderError:
    if code in (400, 401, 403) and ("API key" in detail or "API_KEY" in detail or code != 400):
        return ProviderError(
            "La clave de Gemini no es válida. Revísala en Configuración.", transient=False
        )
    if code == 429:
        return ProviderError(
            "Se alcanzó el límite gratuito de Gemini por ahora. Se reintentará en un momento.",
            transient=True,
        )
    if code is not None and code >= 500:
        return ProviderError("El servicio de Gemini falló temporalmente.", transient=True)
    return ProviderError(f"Error de Gemini ({code}): {detail[:200]}", transient=False)
