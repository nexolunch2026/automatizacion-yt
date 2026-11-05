"""Generación automática de imágenes con IA a partir de los prompts de cada escena.

Solo Gemini (Nano Banana) con la clave del usuario; la API de imágenes de Google es de pago.
La forma gratis es Google Flow, a mano (ver `app/flow.py`).
"""

import re
import time
from typing import Protocol

from app.providers.ai import GeminiProvider, ModelUnavailable, ProviderError

SLEEP = time.sleep  # se reemplaza en los tests
STYLE_SUFFIX = (
    ", clean 2D stickman illustration, absolutely no text, no words, no letters, no captions,"
    " no charts, no infographics, no signs, no watermark, no logo"
)
NO_FREE_IMAGES = (
    "Tu clave de Gemini no puede crear imágenes gratis. Hazlas gratis con Google Flow "
    "(pasos arriba, en esta misma página)."
)


class ImageProvider(Protocol):
    name: str
    label: str

    def generate(self, prompt: str, portrait: bool, seed: int) -> tuple[bytes, str]:
        """Devuelve (bytes de la imagen, extensión)."""


def pick_image_model(names: list[str]) -> list[str]:
    """Modelos de Gemini capaces de generar imágenes: primero los «flash», luego el resto."""
    names = [n.removeprefix("models/") for n in names]
    image_models = [n for n in names if re.fullmatch(r"gemini-[\d.]+-(flash|pro)-image[\w.-]*", n)]
    flash = sorted((n for n in image_models if "-flash-" in n), reverse=True)
    others = sorted((n for n in image_models if n not in flash), reverse=True)
    return flash + others or ["gemini-2.5-flash-image"]


class GeminiImages:
    name = "gemini"
    label = "Gemini"

    def __init__(self, api_key: str):
        self._gemini = GeminiProvider(api_key)
        self._models: list[str] | None = None

    def _candidates(self) -> list[str]:
        if self._models is None:
            client = self._gemini._client
            names = self._gemini._call(lambda: [m.name for m in client.models.list()])
            self._models = pick_image_model(names)
        return self._models

    def generate(self, prompt: str, portrait: bool, seed: int) -> tuple[bytes, str]:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="9:16" if portrait else "16:9"),
        )
        last: ProviderError | None = None
        for model in list(self._candidates()):
            try:
                response = self._gemini._call(
                    lambda m=model: self._gemini._client.models.generate_content(
                        model=m, contents=prompt + STYLE_SUFFIX, config=config
                    )
                )
            except ModelUnavailable as exc:
                last = exc.error
                self._models.remove(model)  # no volver a intentarlo en esta tarea
                continue
            for candidate in response.candidates or []:
                for part in (candidate.content.parts if candidate.content else None) or []:
                    blob = getattr(part, "inline_data", None)
                    if blob and blob.data:
                        ext = ".jpg" if "jpeg" in (blob.mime_type or "") else ".png"
                        return blob.data, ext
            raise ProviderError(
                "Gemini no devolvió imagen para esta escena (puede ser un filtro de contenido)."
            )
        raise last or ProviderError("Tu cuenta de Gemini no tiene modelos de imágenes.")


class ImageChain:
    """Prueba los proveedores en orden. Si uno falla por algo que no se arregla
    reintentando (cuota, permisos), se descarta para el resto de la tarea."""

    def __init__(self, providers: list[ImageProvider]):
        self.providers = providers
        self.notes: list[str] = []

    def generate(self, prompt: str, portrait: bool, seed: int) -> tuple[bytes, str, ImageProvider]:
        last: ProviderError | None = None
        for provider in list(self.providers):
            try:
                data, ext = provider.generate(prompt, portrait, seed)
                return data, ext, provider
            except ProviderError as exc:
                last = exc
                if not exc.transient and "filtro" not in str(exc):
                    self.providers.remove(provider)
                    self.notes.append(f"{provider.label}: {exc}")
        if last and last.transient:
            raise last
        reasons = "; ".join(self.notes) or (str(last) if last else "sin clave de Gemini")
        raise ProviderError(NO_FREE_IMAGES, detail=reasons[:300])
