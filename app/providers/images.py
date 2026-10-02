"""Generación de imágenes con IA a partir de los prompts de cada escena.

1. Gemini (con la clave del usuario), si su cuenta tiene un modelo de imágenes disponible.
2. Pollinations (gratis, sin clave, modelo FLUX), como alternativa.
"""

import re
import time
import urllib.parse
from typing import Protocol

import httpx

from app.config import VERSION
from app.providers.ai import GeminiProvider, ModelUnavailable, ProviderError

SLEEP = time.sleep  # se reemplaza en los tests
STYLE_SUFFIX = ", high quality, detailed, no text, no letters, no watermark, no logo"


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


class PollinationsImages:
    """https://pollinations.ai — gratis y sin clave. Modelo FLUX (uso comercial permitido)."""

    name = "pollinations"
    label = "Pollinations (FLUX)"
    URL = "https://image.pollinations.ai/prompt/"

    def __init__(self, transport=None, pause_seconds: float = 6):
        self._client = httpx.Client(
            timeout=180,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": f"FacelessStudio/{VERSION}"},
        )
        self._pause = pause_seconds
        self._last = 0.0

    def generate(self, prompt: str, portrait: bool, seed: int) -> tuple[bytes, str]:
        width, height = (768, 1344) if portrait else (1344, 768)
        url = self.URL + urllib.parse.quote(prompt + STYLE_SUFFIX, safe="")
        params = {
            "width": width,
            "height": height,
            "model": "flux",
            "seed": seed,
            "nologo": "true",
            "private": "true",
        }
        for attempt in range(3):
            wait = self._pause - (time.monotonic() - self._last)
            if wait > 0:  # el servicio gratuito pide no hacer peticiones seguidas
                SLEEP(wait)
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise ProviderError(
                    "No se pudo conectar con Pollinations.", transient=True, detail=str(exc)[:200]
                ) from exc
            finally:
                self._last = time.monotonic()
            if response.status_code == 429 and attempt < 2:
                SLEEP(20 * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    f"Pollinations respondió con un error ({response.status_code}).",
                    transient=response.status_code in (429, 500, 502, 503, 504),
                    detail=response.text[:200],
                )
            if not response.headers.get("content-type", "").startswith("image/"):
                raise ProviderError("Pollinations no devolvió una imagen.", transient=True)
            ext = ".png" if "png" in response.headers["content-type"] else ".jpg"
            return response.content, ext
        raise ProviderError("Pollinations está saturado. Prueba más tarde.", transient=True)


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
        raise last or ProviderError("No hay ningún generador de imágenes disponible.")
