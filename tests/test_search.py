import httpx
import pytest

from app.providers.ai import ProviderError
from app.providers.search import WikipediaSearch


def wiki_transport(requests):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        assert request.headers["User-Agent"].startswith("FacelessStudio/")
        if params.get("list") == "search":
            hits = {
                "Enron": [{"title": "Enron"}, {"title": "Escándalo Enron"}],
                "quiebra": [{"title": "Enron"}, {"title": "Quiebra"}],
            }[params["srsearch"]]
            return httpx.Response(200, json={"query": {"search": hits}})
        title = params["titles"]
        if title == "Quiebra":
            return httpx.Response(
                200, json={"query": {"pages": [{"title": title, "missing": True}]}}
            )
        page = {
            "title": title,
            "fullurl": f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}",
            "extract": f"Texto de {title}. " * 10,
        }
        return httpx.Response(200, json={"query": {"pages": [page]}})

    return httpx.MockTransport(handler)


def test_search_dedupes_and_fetches_articles():
    requests = []
    search = WikipediaSearch(max_chars=50, transport=wiki_transport(requests))
    docs = search.search(["Enron", "quiebra"], "Español")

    assert [d.title for d in docs] == ["Enron", "Escándalo Enron"]  # «Quiebra» no existe
    assert docs[0].url == "https://es.wikipedia.org/wiki/Enron"
    assert len(docs[0].text) == 50
    assert requests[0].url.host == "es.wikipedia.org"


def test_english_uses_english_wikipedia():
    requests = []
    WikipediaSearch(transport=wiki_transport(requests)).search(["Enron"], "Inglés")
    assert requests[0].url.host == "en.wikipedia.org"


def test_network_error_is_friendly_and_retryable():
    def fail(request):
        raise httpx.ConnectError("sin red")

    search = WikipediaSearch(transport=httpx.MockTransport(fail))
    with pytest.raises(ProviderError) as info:
        search.search(["Enron"], "Español")
    assert info.value.transient
    assert "Wikipedia" in str(info.value)
