"""Bancos de imágenes y vídeos gratuitos: Pexels y Pixabay (ambos necesitan clave gratis).

Todo lo que se descarga queda registrado con su autor, licencia y página de origen.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import VERSION
from app.providers.ai import ProviderError


@dataclass
class StockItem:
    provider: str
    id: str
    kind: str  # "video" o "image"
    url: str  # archivo a descargar
    page_url: str
    author: str
    license: str
    width: int
    height: int
    duration: float = 0.0


class StockProvider(Protocol):
    name: str

    def search(self, query: str, kind: str, portrait: bool, limit: int = 8) -> list[StockItem]: ...


def _client(transport=None, headers=None) -> httpx.Client:
    return httpx.Client(
        timeout=30,
        transport=transport,
        follow_redirects=True,
        headers={"User-Agent": f"FacelessStudio/{VERSION}", **(headers or {})},
    )


def _get_json(client: httpx.Client, url: str, params: dict, provider: str) -> dict:
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"No se pudo conectar con {provider}.", transient=True, detail=str(exc)[:200]
        ) from exc
    if response.status_code in (401, 403):
        raise ProviderError(f"La clave de {provider} no es válida. Revísala en Configuración.")
    if response.status_code == 429:
        raise ProviderError(f"Se alcanzó el límite de {provider}.", transient=True)
    if response.status_code >= 400:
        raise ProviderError(f"{provider} respondió con un error ({response.status_code}).")
    return response.json()


def _best_video_file(files: list[dict], portrait: bool) -> dict | None:
    """El MP4 más cercano a 1920 px en el lado largo (sin pasarse mucho)."""
    mp4 = [f for f in files if (f.get("file_type") or "video/mp4") == "video/mp4" and f.get("link")]
    if not mp4:
        return None

    def score(f):
        long_side = max(f.get("width") or 0, f.get("height") or 0)
        return abs(long_side - 1920) + (5000 if long_side > 2600 else 0)

    return min(mp4, key=score)


class PexelsStock:
    name = "pexels"
    LICENSE = "Licencia de Pexels (uso gratuito, atribución no obligatoria)"

    def __init__(self, api_key: str, transport=None):
        self._client = _client(transport, {"Authorization": api_key})

    def search(self, query: str, kind: str, portrait: bool, limit: int = 8) -> list[StockItem]:
        orientation = "portrait" if portrait else "landscape"
        params = {"query": query, "orientation": orientation, "per_page": limit}
        if kind == "video":
            data = _get_json(self._client, "https://api.pexels.com/videos/search", params, "Pexels")
            items = []
            for v in data.get("videos", []):
                best = _best_video_file(v.get("video_files", []), portrait)
                if best:
                    items.append(
                        StockItem(
                            "pexels",
                            str(v["id"]),
                            "video",
                            best["link"],
                            v.get("url", ""),
                            (v.get("user") or {}).get("name", ""),
                            self.LICENSE,
                            best.get("width") or 0,
                            best.get("height") or 0,
                            float(v.get("duration") or 0),
                        )
                    )
            return items
        data = _get_json(self._client, "https://api.pexels.com/v1/search", params, "Pexels")
        return [
            StockItem(
                "pexels",
                str(p["id"]),
                "image",
                (p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("original", ""),
                p.get("url", ""),
                p.get("photographer", ""),
                self.LICENSE,
                p.get("width") or 0,
                p.get("height") or 0,
            )
            for p in data.get("photos", [])
            if (p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("original")
        ]


class PixabayStock:
    name = "pixabay"
    LICENSE = "Licencia de contenido de Pixabay (uso gratuito, atribución no obligatoria)"

    def __init__(self, api_key: str, transport=None):
        self._key = api_key
        self._client = _client(transport)

    def search(self, query: str, kind: str, portrait: bool, limit: int = 8) -> list[StockItem]:
        params = {"key": self._key, "q": query, "per_page": max(limit, 3), "safesearch": "true"}
        if kind == "video":
            data = _get_json(self._client, "https://pixabay.com/api/videos/", params, "Pixabay")
            items = []
            for h in data.get("hits", []):
                videos = h.get("videos") or {}
                best = next(
                    (
                        videos[q]
                        for q in ("large", "medium", "small")
                        if (videos.get(q) or {}).get("url")
                    ),
                    None,
                )
                if best:
                    items.append(
                        StockItem(
                            "pixabay",
                            str(h["id"]),
                            "video",
                            best["url"],
                            h.get("pageURL", ""),
                            h.get("user", ""),
                            self.LICENSE,
                            best.get("width") or 0,
                            best.get("height") or 0,
                            float(h.get("duration") or 0),
                        )
                    )
            return items
        params.update(image_type="photo", orientation="vertical" if portrait else "horizontal")
        data = _get_json(self._client, "https://pixabay.com/api/", params, "Pixabay")
        return [
            StockItem(
                "pixabay",
                str(h["id"]),
                "image",
                h.get("largeImageURL") or h.get("webformatURL", ""),
                h.get("pageURL", ""),
                h.get("user", ""),
                self.LICENSE,
                h.get("imageWidth") or 0,
                h.get("imageHeight") or 0,
            )
            for h in data.get("hits", [])
            if h.get("largeImageURL") or h.get("webformatURL")
        ]


def download(item: StockItem, target, transport=None) -> None:
    """Descarga a un «.part» y renombra al terminar."""
    from pathlib import Path

    target = Path(target)
    partial = target.with_name(target.name + ".part")
    try:
        with _client(transport) as client, client.stream("GET", item.url) as response:
            response.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        partial.replace(target)
    except (httpx.HTTPError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise ProviderError(
            f"No se pudo descargar un archivo de {item.provider}.",
            transient=True,
            detail=str(exc)[:200],
        ) from exc
