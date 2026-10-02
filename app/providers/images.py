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
STYLE_SUFFIX = (
    ", high quality, detailed, photographic scene, absolutely no text, no words, no letters,"
    " no numbers, no captions, no charts, no infographics, no signs, no watermark, no logo"
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


RATE_LIMIT_CODES = (402, 429)  # Pollinations usa 402 cuando se piden imágenes muy seguidas
RATE_LIMIT_WAITS = [30, 60, 90]


class PollinationsImages:
    """https://pollinations.ai — gratis (con o sin clave). Modelo FLUX (uso comercial
    permitido). Sin clave admite pocas peticiones por minuto, así que se va despacio y,
    si avisa de exceso, se espera y se reintenta."""

    name = "pollinations"
    label = "Pollinations (FLUX)"
    URL = "https://image.pollinations.ai/prompt/"

    def __init__(
        self, token: str | None = None, transport=None, pause_seconds: float | None = None
    ):
        headers = {"User-Agent": f"FacelessStudio/{VERSION}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            timeout=180, transport=transport, follow_redirects=True, headers=headers
        )
        self._pause = pause_seconds if pause_seconds is not None else (5 if token else 15)
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
        detail = ""
        for attempt in range(len(RATE_LIMIT_WAITS) + 1):
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
            if response.status_code in RATE_LIMIT_CODES:
                detail = f"{response.status_code}: {response.text[:200]}"
                if attempt < len(RATE_LIMIT_WAITS):
                    SLEEP(RATE_LIMIT_WAITS[attempt])
                    continue
                raise ProviderError(
                    "Pollinations está limitando las peticiones gratuitas. Espera un rato y "
                    "vuelve a intentarlo, o pon una clave gratuita de Pollinations en "
                    "Configuración.",
                    transient=True,
                    detail=detail,
                )
            if response.status_code >= 400:
                raise ProviderError(
                    f"Pollinations respondió con un error ({response.status_code}).",
                    transient=response.status_code >= 500,
                    detail=response.text[:200],
                )
            if not response.headers.get("content-type", "").startswith("image/"):
                raise ProviderError(
                    "Pollinations no devolvió una imagen.",
                    transient=True,
                    detail=response.text[:200],
                )
            ext = ".png" if "png" in response.headers["content-type"] else ".jpg"
            return response.content, ext
        raise ProviderError(
            "Pollinations está saturado. Prueba más tarde.", transient=True, detail=detail
        )


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
        if last:
            raise last
        reasons = "; ".join(self.notes) or "ninguno configurado"
        raise ProviderError(f"No hay ningún generador de imágenes disponible ({reasons}).")
