"""DEMANDA: ¿la gente busca esto en YouTube?

Usa las sugerencias del buscador de YouTube (lo que aparece al escribir), que son
públicas y gratis: si un tema tiene muchas sugerencias, hay gente buscándolo. No es una
cifra exacta de búsquedas, pero sirve para ordenar ideas: primero las que tienen demanda.
"""

import json
import logging
import re
import time
import unicodedata

import httpx

log = logging.getLogger(__name__)

URL = "https://suggestqueries.google.com/complete/search"
CACHE_SECONDS = 24 * 3600
_cache: dict[str, tuple[float, list[str]]] = {}
LEVELS = [(8, "alta", "🔥"), (4, "media", "📈"), (1, "baja", "🌱")]


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _download(term: str, language: str) -> str:
    with httpx.Client(timeout=6, follow_redirects=True) as client:
        r = client.get(URL, params={"client": "firefox", "ds": "yt", "hl": language, "q": term})
        r.raise_for_status()
        return r.text


def fetch(term: str, language: str = "es") -> list[str]:
    """Lo que sugiere YouTube al escribir `term` (lista vacía si no hay red)."""
    term = " ".join(term.split())[:80]
    if not term:
        return []
    key = f"{language}:{_plain(term)}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        data = json.loads(_download(term, language))
        found = [s for s in data[1] if isinstance(s, str)][:10]
    except (httpx.HTTPError, ValueError, IndexError, TypeError) as exc:
        log.info("Sin sugerencias de YouTube para %r: %s", term, exc)
        return []
    _cache[key] = (time.time(), found)
    return found


def score(term: str, suggestions: list[str]) -> dict:
    """Nivel de demanda según cuántas sugerencias hay que de verdad hablan del tema."""
    words = [w for w in re.findall(r"\w+", _plain(term)) if len(w) > 2]
    related = [s for s in suggestions if words and any(w in _plain(s) for w in words)]
    for minimum, label, icon in LEVELS:
        if len(related) >= minimum:
            return {"level": label, "icon": icon, "count": len(related), "searches": related[:3]}
    return {"level": "sin datos", "icon": "", "count": 0, "searches": []}


def check(term: str, language: str = "es") -> dict:
    return score(term, fetch(term, language))


ORDER = {"alta": 0, "media": 1, "baja": 2, "sin datos": 3}


def rank(items: list[dict]) -> list[dict]:
    """Ordena ideas (con su «demand») de más a menos demanda, sin perder el orden original
    entre las del mismo nivel."""
    return sorted(items, key=lambda x: ORDER.get(x["demand"]["level"], 3))
