"""COMPROBAR DATOS CON FUENTES FIABLES (gratis, con un botón en el Guion).

La búsqueda de Google dentro de Gemini ya no es gratis, y Wikipedia sola no basta. Así que:
1. Gemini saca del guion los datos que se pueden comprobar (cifras, fechas, nombres, récords).
2. Se abren los artículos de Wikipedia del tema (en inglés y en español) solo como MAPA: se
   leen sus notas al pie y se quedan las fuentes fiables (SEC, Justicia de EE. UU., Reuters,
   BBC, UEFA, RSSSF, Transfermarkt…). Se descargan; si un enlace está roto, se busca la copia
   guardada en Internet Archive.
3. Para cada dato se buscan los trozos de esas fuentes que hablan de él, y Gemini (sin
   búsqueda: gratis) dice si lo confirman o lo contradicen.
4. El programa decide: «confirmado» (2 webs fiables distintas, o un documento oficial),
   «una fuente», «corregir» (alguna fuente dice otra cosa) o «sin confirmar». Wikipedia sirve
   para encontrar, pero no cuenta para confirmar.
Nunca se inventan fuentes: solo cuentan las páginas que se descargaron de verdad.
"""

import re
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.config import VERSION
from app.providers.ai import ProviderError

STAGE = "factcheck"
MAX_CLAIMS = 15
MAX_SOURCES = 24
PER_DOMAIN = 3
VERIFY_BATCH = 5
PASSAGE = 700  # letras de cada trozo de fuente que ve Gemini
PASSAGES_PER_CLAIM = 8
MAX_PAGE = 3_000_000
USER_AGENT = (
    f"Mozilla/5.0 (compatible; FacelessStudio/{VERSION}; "
    "+https://github.com/nexolunch2026/automatizacion-yt)"
)

# Fuentes fiables. Primarias: documentos oficiales (lo más fiable que hay).
PRIMARY = {
    "sec.gov": "SEC (informes oficiales de empresas)",
    "justice.gov": "Departamento de Justicia de EE. UU.",
    "courtlistener.com": "Documentos judiciales",
    "ftc.gov": "Comisión Federal de Comercio de EE. UU.",
    "uscourts.gov": "Tribunales de EE. UU.",
    "europa.eu": "Unión Europea",
    "uefa.com": "UEFA",
    "fifa.com": "FIFA",
    "rsssf.org": "RSSSF (historia del fútbol)",
    "rsssf.com": "RSSSF (historia del fútbol)",
    "theplayerstribune.com": "The Players' Tribune (contado por los jugadores)",
}
# Prensa y bases de datos serias.
RELIABLE = {
    "reuters.com": "Reuters",
    "apnews.com": "Associated Press",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "theguardian.com": "The Guardian",
    "nytimes.com": "The New York Times",
    "wsj.com": "The Wall Street Journal",
    "ft.com": "Financial Times",
    "bloomberg.com": "Bloomberg",
    "cnbc.com": "CNBC",
    "cnn.com": "CNN",
    "forbes.com": "Forbes",
    "fortune.com": "Fortune",
    "economist.com": "The Economist",
    "washingtonpost.com": "The Washington Post",
    "latimes.com": "Los Angeles Times",
    "wired.com": "Wired",
    "theverge.com": "The Verge",
    "businessinsider.com": "Business Insider",
    "npr.org": "NPR",
    "time.com": "TIME",
    "britannica.com": "Enciclopedia Británica",
    "elpais.com": "El País",
    "expansion.com": "Expansión",
    "elmundo.es": "El Mundo",
    "lavanguardia.com": "La Vanguardia",
    "abc.es": "ABC",
    "transfermarkt.com": "Transfermarkt",
    "transfermarkt.es": "Transfermarkt",
    "transfermarkt.co.uk": "Transfermarkt",
    "fbref.com": "FBref (estadísticas)",
    "espn.com": "ESPN",
    "skysports.com": "Sky Sports",
    "marca.com": "Marca",
    "as.com": "AS",
    "mundodeportivo.com": "Mundo Deportivo",
    "sport.es": "Sport",
    "gazzetta.it": "La Gazzetta dello Sport",
    "lequipe.fr": "L'Équipe",
    "kicker.de": "Kicker",
    "realmadrid.com": "Real Madrid (web oficial)",
    "fcbarcelona.com": "FC Barcelona (web oficial)",
    "premierleague.com": "Premier League (web oficial)",
    "goal.com": "Goal",
}
STATUS_LABELS = {
    "confirmado": "Confirmado",
    "una_fuente": "Solo una fuente fiable",
    "solo_wikipedia": "Solo en Wikipedia",
    "corregir": "Revisar: una fuente dice otra cosa",
    "sin_confirmar": "Sin confirmar",
}


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.").removeprefix("m.")


def trust(url: str) -> tuple[int, str]:
    """(nivel, nombre): 1 = documento oficial, 2 = prensa o base de datos seria, 0 = otra."""
    host = domain_of(url)
    for table, level in ((PRIMARY, 1), (RELIABLE, 2)):
        for domain, name in table.items():
            if host == domain or host.endswith("." + domain):
                return level, name
    if host.endswith(".gov") or host.endswith(".gob.es"):
        return 1, host
    return 0, host


# ---------------------------------------------------------------- 1. datos del guion


class Claim(BaseModel):
    paragraph_id: str = Field(description="id del párrafo donde aparece")
    text: str = Field(description="El dato tal cual lo dice el guion, en una frase corta")
    keywords: list[str] = Field(
        description="3-6 palabras clave para encontrarlo en fuentes en inglés y en español: "
        "nombres propios, años, cifras (en varios formatos, ej. «10.000 millones», "
        "«10 billion»), palabras clave traducidas"
    )


class Claims(BaseModel):
    subject: str = Field(
        description="El tema principal tal como se llama su artículo de Wikipedia en inglés "
        "(ej. «Gareth Bale», «Theranos», «Blockbuster LLC»)"
    )
    claims: list[Claim]


def _claims_prompt(script: dict) -> str:
    lines = []
    for section in script.get("sections", []):
        for p in section.get("paragraphs", []):
            lines.append(f"[{p['id']}] {p['text']}")
    body = "\n".join(lines)
    return f"""Este es el guion de un documental de YouTube. Cada párrafo empieza con su id.

{body}

Saca los {MAX_CLAIMS} datos MÁS importantes que se pueden comprobar en fuentes: cifras de
dinero, fechas, récords, títulos ganados, nombres de personas y cargos, sucesos concretos.
Prioriza los que un espectador podría discutir si están mal. No incluyas opiniones ni frases
narrativas."""


# ---------------------------------------------------------------- 2. fuentes


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        elif not self.depth:
            self.parts.append(data)


def html_text(html: str) -> tuple[str, str]:
    """(título, texto limpio) de una página web."""
    parser = _Text()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — HTML roto: nos quedamos con lo leído
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return parser.title[:200], text[:80_000]


class Web:
    """Descargas de internet (se sustituye en las pruebas, que no usan internet)."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            timeout=15,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en,es;q=0.8"},
        )

    def json(self, url: str, params: dict) -> dict:
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def page(self, url: str) -> str:
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("enlace no válido")
        response = self.client.get(url)
        response.raise_for_status()
        if "html" not in response.headers.get("content-type", "html"):
            raise ValueError("no es una página web")
        return response.text[:MAX_PAGE]


def wikipedia_articles(web: Web, topic: str, titles: list[str], subject: str = "") -> list[dict]:
    """Los artículos de Wikipedia del tema (inglés y español): {lang, title, url, text,
    links}. En inglés se busca por el nombre del tema en inglés (tiene muchas más notas)."""
    found = []
    for lang, limit in (("en", 2), ("es", 2)):
        api = f"https://{lang}.wikipedia.org/w/api.php"
        names = ([subject] if lang == "en" and subject else []) + [
            t for t in titles if lang == "es"
        ][:limit]
        query = subject if lang == "en" and subject else topic
        try:
            hits = web.json(
                api,
                {"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                 "format": "json"},
            )  # fmt: skip
            names += [h["title"] for h in hits.get("query", {}).get("search", [])]
        except (httpx.HTTPError, ValueError):
            continue
        for name in list(dict.fromkeys(names))[:limit]:
            try:
                data = web.json(
                    api,
                    {"action": "query", "prop": "extracts|extlinks|info", "inprop": "url",
                     "explaintext": 1, "ellimit": 500, "redirects": 1, "titles": name,
                     "format": "json", "formatversion": 2},
                )  # fmt: skip
            except (httpx.HTTPError, ValueError):
                continue
            for page in data.get("query", {}).get("pages", []):
                if page.get("missing"):
                    continue
                found.append(
                    {
                        "lang": lang,
                        "title": page.get("title", name),
                        "url": page.get("fullurl", ""),
                        "text": (page.get("extract") or "")[:80_000],
                        "links": [x.get("url", "") for x in page.get("extlinks", [])],
                    }
                )
    return found


def pick_links(links: list[str]) -> list[str]:
    """Las fuentes fiables de las notas al pie: primero las oficiales, como mucho 2 por web."""
    ranked = []
    for url in dict.fromkeys(links):
        if url.startswith("//"):
            url = "https:" + url
        level, _ = trust(url)
        if level and urlparse(url).scheme in ("http", "https"):
            ranked.append((level, url))
    ranked.sort(key=lambda r: r[0])
    chosen, per_domain = [], {}
    for _, url in ranked:
        d = domain_of(url)
        if per_domain.get(d, 0) >= PER_DOMAIN:
            continue
        per_domain[d] = per_domain.get(d, 0) + 1
        chosen.append(url)
        if len(chosen) >= MAX_SOURCES:
            break
    return chosen


def fetch_source(web: Web, url: str) -> dict | None:
    """Descarga una fuente. Si el enlace está roto o es de pago, la copia de Internet Archive."""
    archived = False
    try:
        title, text = html_text(web.page(url))
    except (httpx.HTTPError, ValueError):
        title, text = "", ""
    if len(text) < 600:
        try:
            snap = web.json("https://archive.org/wayback/available", {"url": url})
            closest = (snap.get("archived_snapshots") or {}).get("closest") or {}
            if closest.get("available") and closest.get("url"):
                title, text = html_text(web.page(closest["url"]))
                archived = True
        except (httpx.HTTPError, ValueError):
            return None
    if len(text) < 600:
        return None
    level, name = trust(url)
    return {"url": url, "title": title or name, "site": name, "level": level,
            "archived": archived, "text": text}  # fmt: skip


# ---------------------------------------------------------------- 3. trozos que hablan de cada dato


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _terms(claim: dict) -> list[str]:
    words = set()
    for chunk in [*claim.get("keywords", []), claim.get("text", "")]:
        for w in re.findall(r"[\w.,]+", _plain(chunk)):
            w = w.strip(".,")
            if len(w) >= 4 or any(c.isdigit() for c in w):
                words.add(w)
    return sorted(words)


def passages(claim: dict, sources: list[dict]) -> list[tuple[int, str]]:
    """Los trozos de fuente que más se parecen al dato: [(número de fuente, texto)]."""
    terms = _terms(claim)
    scored = []
    for index, source in enumerate(sources):
        text = source["text"]
        plain = _plain(text)
        best = []
        for start in range(0, max(len(text) - 200, 1), PASSAGE // 2):
            window = plain[start : start + PASSAGE]
            score = sum((3 if any(c.isdigit() for c in t) else 1) for t in terms if t in window)
            if score:
                best.append((score, start))
        best.sort(reverse=True)
        for score, start in best[:2]:
            scored.append((score, index, text[start : start + PASSAGE]))
    scored.sort(key=lambda s: s[0], reverse=True)
    top = scored[0][0] if scored else 0
    chosen, used, wiki = [], {}, 0
    for score, index, text in scored:
        is_wiki = sources[index]["level"] == 3
        # Wikipedia es larguísima y ganaría casi todos los huecos: como mucho 2 trozos suyos,
        # y de cada fuente original 1 (para que entren muchas webs distintas).
        if used.get(index, 0) >= (2 if is_wiki else 1) or (is_wiki and wiki >= 2):
            continue
        if score < max(2, top // 3):  # trozos que apenas mencionan el dato: fuera
            continue
        used[index] = used.get(index, 0) + 1
        wiki += is_wiki
        chosen.append((index, " ".join(text.split())))
        if len(chosen) >= PASSAGES_PER_CLAIM:
            break
    return chosen


# ---------------------------------------------------------------- 4. veredicto


class Verdict(BaseModel):
    claim: int = Field(description="Número del dato")
    supports: list[str] = Field(description="Etiquetas [S..] de los trozos que lo confirman")
    contradicts: list[str] = Field(description="Etiquetas [S..] de los trozos que dicen otra cosa")
    correction: str = Field(description="Si alguna fuente dice otra cosa: el dato correcto, en "
                            "español y en una frase. Si no, vacío")  # fmt: skip


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def _verify_prompt(batch: list[tuple[int, dict, list[tuple[int, str]]]], sources) -> str:
    blocks = []
    for number, claim, found in batch:
        lines = [f"DATO {number}: {claim['text']}"]
        for index, text in found:
            lines.append(f"  [S{index + 1}] ({sources[index]['site']}): «{text}»")
        if not found:
            lines.append("  (no hay trozos de fuentes para este dato)")
        blocks.append("\n".join(lines))
    body = "\n\n".join(blocks)
    return f"""Comprueba datos de un documental con trozos de fuentes fiables.
Para cada DATO, mira SOLO sus trozos [S..] (no uses lo que sepas tú):
- «supports»: los trozos que dicen lo mismo (aunque sea con otras palabras u otro idioma).
- «contradicts»: SOLO los trozos que dan una cifra, fecha, nombre o hecho DISTINTO. Si el trozo
  dice lo mismo con más detalle (p. ej. «135 meses» frente a «11 años»), NO es contradicción:
  va en «supports».
- «correction»: si alguno lo contradice, cómo debería decirse según esa fuente.
Si un trozo no habla de ese dato, no lo pongas en ninguna lista.

{body}"""


def _labels_to_index(labels: list[str], allowed: set[int]) -> list[int]:
    out = []
    for label in labels:
        match = re.search(r"\d+", str(label))
        if match and int(match.group()) - 1 in allowed:
            out.append(int(match.group()) - 1)
    return list(dict.fromkeys(out))


def same_fact(a: str, b: str) -> bool:
    """¿La «corrección» dice en realidad lo mismo que el guion? (mismas cifras, casi igual)."""
    from difflib import SequenceMatcher

    pa, pb = _plain(a), _plain(b)
    numbers = lambda t: set(re.findall(r"\d+", t.replace(".", "").replace(",", "")))  # noqa: E731
    return numbers(pa) == numbers(pb) and SequenceMatcher(None, pa, pb).ratio() > 0.8


def decide(
    supports: list[int], contradicts: list[int], correction: str, sources, claim: str = ""
) -> str:
    """El veredicto lo pone el programa (no la IA), contando webs distintas."""
    if contradicts and correction.strip() and not same_fact(correction, claim):
        return "corregir"
    # Wikipedia ayuda a encontrar, pero no cuenta para confirmar: hacen falta 2 webs fiables
    # distintas, o un documento oficial (juicios, informes a la SEC, UEFA…).
    reliable = {sources[i]["site"] for i in supports if sources[i]["level"] in (1, 2)}
    official = any(sources[i]["level"] == 1 for i in supports)
    if len(reliable) >= 2 or official:
        return "confirmado"
    if reliable:
        return "una_fuente"
    return "solo_wikipedia" if supports else "sin_confirmar"


# ---------------------------------------------------------------- todo junto


def run_factcheck(
    script: dict,
    topic: str,
    research_titles: list[str],
    ai,
    progress: Callable[[int, str], None],
    web: Web | None = None,
) -> dict:
    web = web or Web()
    progress(5, "Buscando en el guion los datos que se pueden comprobar")
    found_claims = ai.generate_json(_claims_prompt(script), Claims)
    claims = [c.model_dump() for c in found_claims.claims]
    valid_ids = {p["id"] for s in script.get("sections", []) for p in s.get("paragraphs", [])}
    claims = [c for c in claims if c["text"].strip()][:MAX_CLAIMS]
    for claim in claims:
        if claim["paragraph_id"] not in valid_ids:
            claim["paragraph_id"] = ""

    progress(20, "Leyendo las notas al pie de Wikipedia para llegar a las fuentes originales")
    articles = wikipedia_articles(web, topic, research_titles, found_claims.subject.strip())
    links = pick_links([link for a in articles for link in a["links"]])
    progress(35, f"Descargando {len(links)} fuentes fiables (las rotas, de Internet Archive)")
    with ThreadPoolExecutor(max_workers=8) as pool:
        fetched = [s for s in pool.map(lambda u: fetch_source(web, u), links) if s]
    # Wikipedia también cuenta, pero como fuente secundaria (nivel 3).
    wiki = [
        {"url": a["url"], "title": f"Wikipedia ({a['lang']}): {a['title']}",
         "site": f"Wikipedia ({a['lang']})", "level": 3, "archived": False, "text": a["text"]}
        for a in articles if a["text"]
    ]  # fmt: skip
    sources = fetched + wiki
    if not sources:
        raise ProviderError(
            "No se pudo descargar ninguna fuente. Revisa la conexión a internet y prueba otra vez."
        )

    results = []
    for start in range(0, len(claims), VERIFY_BATCH):
        progress(
            50 + int(45 * start / max(len(claims), 1)),
            f"Comparando los datos {start + 1}–{min(start + VERIFY_BATCH, len(claims))} "
            "con las fuentes",
        )
        batch = [
            (start + i + 1, claim, passages(claim, sources))
            for i, claim in enumerate(claims[start : start + VERIFY_BATCH])
        ]
        try:
            answer = ai.generate_json(_verify_prompt(batch, sources), Verdicts).verdicts
        except ProviderError:
            answer = []
        by_number = {v.claim: v for v in answer}
        for number, claim, found in batch:
            allowed = {index for index, _ in found}
            verdict = by_number.get(number)
            supports = _labels_to_index(verdict.supports, allowed) if verdict else []
            contradicts = _labels_to_index(verdict.contradicts, allowed) if verdict else []
            correction = (verdict.correction if verdict else "").strip()
            status = decide(supports, contradicts, correction, sources, claim["text"])
            results.append(
                {
                    "paragraph_id": claim["paragraph_id"],
                    "text": claim["text"],
                    "status": status,
                    "correction": correction if status == "corregir" else "",
                    "supports": supports,
                    "contradicts": contradicts,
                }
            )

    used = sorted({i for r in results for i in r["supports"] + r["contradicts"]})
    summary = {key: sum(1 for r in results if r["status"] == key) for key in STATUS_LABELS}
    progress(100, "Comprobación terminada")
    return {
        "claims": results,
        "sources": [
            {k: v for k, v in s.items() if k != "text"} | {"used": i in used}
            for i, s in enumerate(sources)
        ],
        "summary": summary,
        "downloaded": len(fetched),
        "tried": len(links),
    }


def description_sources(data: dict | None, limit: int = 10) -> list[dict]:
    """Las fuentes para la descripción del vídeo: las originales que respaldan datos primero,
    Wikipedia al final. Formato de la investigación: [{"n", "title", "uri"}]."""
    sources = (data or {}).get("sources") or []
    ordered = sorted(
        (s for s in sources if s.get("used")), key=lambda s: (s.get("level", 3), s["site"])
    )
    out = []
    for s in ordered[:limit]:
        title = f"{s['site']}: {s['title']}" if s["title"] != s["site"] else s["site"]
        out.append({"n": len(out) + 1, "title": title[:120], "uri": s["url"]})
    return out
