"""Buscadores de información. Hoy: Wikipedia (gratis y sin clave)."""

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import VERSION
from app.providers.ai import ProviderError


@dataclass
class Document:
    title: str
    url: str
    text: str


class SearchProvider(Protocol):
    name: str

    def search(self, queries: list[str], language: str) -> list[Document]: ...


LANGUAGE_CODES = {"Español": "es", "Inglés": "en"}


class WikipediaSearch:
    """Busca artículos en Wikipedia y descarga su texto.

    Usa la API pública de MediaWiki; Wikimedia pide identificarse con un User-Agent.
    """

    name = "wikipedia"

    def __init__(
        self,
        max_documents: int = 6,
        max_chars: int = 6000,
        transport: httpx.BaseTransport | None = None,
    ):
        self.max_documents = max_documents
        self.max_chars = max_chars
        self._client = httpx.Client(
            timeout=20,
            transport=transport,
            headers={"User-Agent": f"FacelessStudio/{VERSION} (uso personal)"},
        )

    def search(self, queries: list[str], language: str) -> list[Document]:
        code = LANGUAGE_CODES.get(language, "es")
        api = f"https://{code}.wikipedia.org/w/api.php"
        titles: list[str] = []
        for query in queries:
            for title in self._search_titles(api, query):
                if title not in titles:
                    titles.append(title)
            if len(titles) >= self.max_documents:
                break
        documents = [self._fetch(api, title) for title in titles[: self.max_documents]]
        return [d for d in documents if d and d.text.strip()]

    def _get(self, api: str, params: dict) -> dict:
        try:
            response = self._client.get(api, params={**params, "format": "json"})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "No se pudo consultar Wikipedia. Revisa tu conexión a internet.",
                transient=True,
                detail=str(exc)[:300],
            ) from exc

    def _search_titles(self, api: str, query: str) -> list[str]:
        data = self._get(
            api, {"action": "query", "list": "search", "srsearch": query, "srlimit": 2}
        )
        return [hit["title"] for hit in data.get("query", {}).get("search", [])]

    def _fetch(self, api: str, title: str) -> Document | None:
        data = self._get(
            api,
            {
                "action": "query",
                "prop": "extracts|info",
                "inprop": "url",
                "explaintext": 1,
                "exlimit": 1,
                "redirects": 1,
                "titles": title,
                "formatversion": 2,
            },
        )
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        page = pages[0]
        url = page.get("fullurl") or f"{api.removesuffix('/w/api.php')}/wiki/{title}"
        return Document(page["title"], url, (page.get("extract") or "")[: self.max_chars])
