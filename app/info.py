"""Información del mundo para JARVIS (todo gratis):

- Tu canal de YouTube: suscriptores, visitas y últimos vídeos (con la clave gratuita de
  YouTube es exacto; sin clave se usa la página pública y su RSS).
- Noticias de negocios y un «radar del nicho» (noticias que sirven de ideas de vídeo
  para el nicho del canal; en marcas: empresas en crisis, cierres…). Google Noticias RSS.
- Dólar del día (open.er-api.com) y pronóstico de 3 días (Open-Meteo).
- Dato curioso del día sobre el nicho del canal (Gemini, uno al día).

Cada consulta se guarda unos minutos en memoria para no repetir peticiones.
"""

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy.orm import Session

from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

DEFAULT_CHANNEL = ""  # cada instalación pone su canal (perfil o JARVIS)
MONETIZATION_SUBS = 1000
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FacelessStudio"}
_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, seconds: int, fetch):
    """Devuelve lo guardado si es reciente; si la consulta falla, lo último que hubo."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    try:
        value = fetch()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ET.ParseError) as exc:
        log.warning("No se pudo consultar %s: %s", key, exc)
        return hit[1] if hit else None
    _cache[key] = (time.time(), value)
    return value


def _get(url: str, **params) -> httpx.Response:
    with httpx.Client(timeout=12, headers=HEADERS, follow_redirects=True) as client:
        r = client.get(url, params=params or None)
        r.raise_for_status()
        return r


# ---------------------------------------------------------------- YouTube


def channel_handle(db: Session) -> str:
    raw = (get_setting(db, "youtube_channel") or DEFAULT_CHANNEL).strip()
    if not raw:
        return ""
    match = re.search(r"(@[\w.\-]+)|(UC[\w-]{22})", raw)
    if match:
        return match.group(0)
    return "@" + raw.lstrip("@") if raw else DEFAULT_CHANNEL


def channel_url(db: Session) -> str:
    handle = channel_handle(db)
    if not handle:  # sin canal configurado, Studio abre el canal de la cuenta de Google
        return "https://studio.youtube.com"
    return f"https://www.youtube.com/{handle if handle.startswith('@') else 'channel/' + handle}"


def _count(text: str) -> int | None:
    """«1,2 mil» → 1200; «3.456» → 3456; «1.2K» → 1200."""
    text = text.lower().replace("\xa0", " ").strip()
    match = re.match(r"([\d.,]+)\s*(mil|k|m|mill|millones)?", text)
    if not match:
        return None
    number, unit = match.group(1), match.group(2)
    if unit:
        value = float(number.replace(",", "."))
        return int(value * (1_000_000 if unit.startswith("m") and unit != "mil" else 1000))
    return int(re.sub(r"[.,]", "", number))


def fetch_youtube_api(handle: str, key: str, limit: int = 5) -> dict:
    """Con la clave gratuita de YouTube Data API v3 (datos exactos)."""
    base = "https://www.googleapis.com/youtube/v3"
    ident = {"forHandle": handle} if handle.startswith("@") else {"id": handle}
    data = _get(
        f"{base}/channels", part="snippet,statistics,contentDetails", key=key, **ident
    ).json()
    item = data["items"][0]
    stats = item["statistics"]
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    playlist = _get(
        f"{base}/playlistItems",
        part="contentDetails",
        playlistId=uploads,
        maxResults=min(limit, 50),
        key=key,
    ).json()
    ids = [i["contentDetails"]["videoId"] for i in playlist.get("items", [])]
    videos = []
    if ids:
        found = _get(f"{base}/videos", part="snippet,statistics", id=",".join(ids), key=key)
        for v in found.json().get("items", []):
            videos.append(
                {
                    "id": v["id"],
                    "title": v["snippet"]["title"],
                    "views": int(v["statistics"].get("viewCount", 0)),
                    "likes": int(v["statistics"].get("likeCount", 0)),
                    "comments": int(v["statistics"].get("commentCount", 0)),
                    "published": v["snippet"]["publishedAt"][:16],
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                }
            )
    hidden = stats.get("hiddenSubscriberCount")
    return {
        "name": item["snippet"]["title"],
        "subscribers": None if hidden else int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
        "latest": videos,
        "exact": True,
    }


ATOM = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def parse_channel_page(page: str) -> dict:
    """De la página pública del canal: identificador, nombre y suscriptores (aprox.)."""
    # El enlace «canonical» y «externalId» son del propio canal; «channelId» puede ser
    # de otro (recomendados), así que va el último.
    channel_id = (
        re.search(
            r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page
        )
        or re.search(r'"externalId":"(UC[\w-]{22})"', page)
        or re.search(r'<meta itemprop="identifier" content="(UC[\w-]{22})"', page)
        or re.search(r'"channelId":"(UC[\w-]{22})"', page)
    )
    name = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    space = r"(?:\s|\\u00a0|&nbsp;|\xa0)*"
    subs = re.search(r'"subscriberCountText":\{[^}]*?"(?:simpleText|content)":"([^"]+)"', page)
    subs = subs or re.search(
        rf"([\d.,]+{space}(?:mil|k|K|M|mill\.?)?){space}(?:suscriptor(?:es)?|subscribers?)\b", page
    )
    count = None
    if subs:
        count = _count(re.sub(r"\\u00a0|&nbsp;", " ", subs.group(1)))
    elif re.search(r"(?:Sin suscriptores|No subscribers)", page):
        count = 0
    return {
        "id": channel_id.group(1) if channel_id else None,
        "name": html.unescape(name.group(1)) if name else "",
        "subscribers": count,
    }


def parse_channel_feed(xml_text: str, limit: int = 5) -> list[dict]:
    root = ET.fromstring(xml_text)
    videos = []
    for entry in root.findall("a:entry", ATOM)[:limit]:
        stats = entry.find("media:group/media:community/media:statistics", ATOM)
        rating = entry.find("media:group/media:community/media:starRating", ATOM)
        link = entry.find("a:link", ATOM)
        videos.append(
            {
                "id": entry.findtext("yt:videoId", "", ATOM),
                "title": entry.findtext("a:title", "", ATOM),
                "views": int(stats.get("views", 0)) if stats is not None else 0,
                "likes": int(rating.get("count", 0)) if rating is not None else None,
                "published": entry.findtext("a:published", "", ATOM)[:16],
                "url": link.get("href") if link is not None else "",
            }
        )
    return videos


def fetch_youtube_public(handle: str, limit: int = 5) -> dict:
    """Sin clave: la página pública del canal y su RSS (los suscriptores, aproximados)."""
    url = f"https://www.youtube.com/{handle if handle.startswith('@') else 'channel/' + handle}"
    page = parse_channel_page(_get(url, hl="es").text)
    channel_id = page["id"] or (handle if handle.startswith("UC") else None)
    if not channel_id:
        raise ValueError("No se encontró el canal")
    if not page["subscribers"] and not page["name"]:
        raise ValueError("La página del canal no tiene datos")
    try:  # el RSS de YouTube a veces falla: sin él seguimos con los suscriptores
        feed = _get("https://www.youtube.com/feeds/videos.xml", channel_id=channel_id).text
        latest = parse_channel_feed(feed, limit)
    except (httpx.HTTPError, ET.ParseError) as exc:
        log.warning("RSS del canal no disponible: %s", exc)
        latest = []
    return {
        "name": page["name"],
        "subscribers": page["subscribers"],
        "views": sum(v["views"] for v in latest) or None,  # solo de los últimos vídeos
        "videos": None,
        "latest": latest,
        "exact": False,
    }


def youtube(db: Session) -> dict | None:
    handle = channel_handle(db)
    if not handle:  # aún no ha dicho cuál es su canal
        return None
    key = get_api_key(db, "youtube")

    def fetch():
        data = fetch_youtube_api(handle, key) if key else fetch_youtube_public(handle)
        subs = data.get("subscribers")
        data["goal"] = MONETIZATION_SUBS
        data["goal_pct"] = min(100, round(subs / MONETIZATION_SUBS * 100)) if subs else None
        data["url"] = channel_url(db)
        return data

    return cached(f"youtube:{handle}:{bool(key)}", 900, fetch)


# ---------------------------------------------------------------- noticias


def news_region(db: Session) -> dict:
    from app import profile

    gl = profile.region(db)
    return {"hl": "es-419", "gl": gl, "ceid": f"{gl}:es-419"}


BRAND_RADAR = (
    '(quiebra OR "cierra tiendas" OR despidos OR crisis OR "en bancarrota" OR '
    '"deja de vender" OR "pierde mercado") empresa marca'
)


def parse_news(xml_text: str, limit: int = 8) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = html.unescape(item.findtext("title", "")).strip()
        source = item.findtext("source", "") or ""
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        published = item.findtext("pubDate", "")
        try:
            when = parsedate_to_datetime(published).strftime("%d/%m %H:%M")
        except (TypeError, ValueError):
            when = ""
        items.append(
            {"title": title, "source": source, "url": item.findtext("link", ""), "when": when}
        )
        if len(items) >= limit:
            break
    return items


def news(db: Session) -> list[dict]:
    def fetch():
        url = "https://news.google.com/rss/headlines/section/topic/BUSINESS"
        return parse_news(_get(url, **news_region(db)).text)

    return cached("news:business", 1800, fetch) or []


def brand_radar(db: Session, fetch: bool = True) -> list[dict]:
    """Titulares que sirven de ideas de vídeo en el nicho del canal (en marcas: empresas en
    problemas). El nombre se mantiene por compatibilidad."""
    from app import niche

    query = niche.main_kit(db).news_query.strip() or BRAND_RADAR

    key = f"news:radar:{query}"
    if not fetch:  # solo lo que ya hay en memoria
        hit = _cache.get(key)
        return hit[1] if hit and hit[1] else []

    def download():
        url = "https://news.google.com/rss/search"
        return parse_news(_get(url, q=query + " when:7d", **news_region(db)).text, limit=8)

    return cached(key, 3600, download) or []


# ---------------------------------------------------------------- dólar y clima


def currency(db: Session) -> str:
    return (get_setting(db, "jarvis_currency") or "COP").upper()


def dollar(db: Session) -> dict | None:
    code = currency(db)

    def fetch():
        data = _get("https://open.er-api.com/v6/latest/USD").json()
        if data.get("result") != "success" or code not in data["rates"]:
            raise ValueError("sin tipo de cambio")
        return {"currency": code, "rate": round(float(data["rates"][code]), 2)}

    return cached(f"usd:{code}", 3600, fetch)


def fetch_forecast(city: str) -> list[dict]:
    """Pronóstico de 3 días (Open-Meteo, gratis)."""
    from app.agenda import WEATHER_CODES, WEEKDAYS

    place = _get(
        "https://geocoding-api.open-meteo.com/v1/search", name=city, count=1, language="es"
    ).json()["results"][0]
    daily = _get(
        "https://api.open-meteo.com/v1/forecast",
        latitude=place["latitude"],
        longitude=place["longitude"],
        daily="weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        timezone="auto",
        forecast_days=3,
    ).json()["daily"]
    days = []
    for i, day in enumerate(daily["time"]):
        date = datetime.strptime(day, "%Y-%m-%d")
        days.append(
            {
                "day": ["Hoy", "Mañana"][i] if i < 2 else WEEKDAYS[date.weekday()].capitalize(),
                "sky": WEATHER_CODES.get(daily["weather_code"][i], ""),
                "max": round(daily["temperature_2m_max"][i]),
                "min": round(daily["temperature_2m_min"][i]),
                "rain": daily["precipitation_probability_max"][i] or 0,
            }
        )
    return days


def forecast(db: Session) -> list[dict]:
    city = (get_setting(db, "jarvis_city") or "").strip()
    if not city:
        return []
    return cached(f"forecast:{city}", 3600, lambda: fetch_forecast(city)) or []


# ---------------------------------------------------------------- dato curioso


def fact_of_day(db: Session, now: datetime | None = None, generate: bool = True) -> str:
    """Un dato curioso sobre el nicho del canal, uno al día (Gemini)."""
    from pydantic import BaseModel

    today = (now or datetime.now()).strftime("%Y-%m-%d")
    saved = get_setting(db, "jarvis_fact") or ""
    if saved.startswith(today + "|"):
        return saved.split("|", 1)[1]
    if not generate:
        return ""

    class Fact(BaseModel):
        fact: str

    from app import jobs
    from app.providers.ai import ProviderError

    try:
        from app import niche

        topic = niche.main_kit(db).fact_topic
        ai = jobs.get_ai_provider(db)
        fact = ai.generate_json(
            f"Cuenta UN dato curioso, real y verificable sobre {topic} (un origen, un error "
            "famoso, un giro inesperado). Máximo dos frases, en español, tono ameno. No "
            "inventes nada; si dudas de una cifra, no la pongas.",
            Fact,
        ).fact.strip()
        jobs.remember_working_model(db, ai)
    except ProviderError:
        return ""
    set_setting(db, "jarvis_fact", f"{today}|{fact}")
    return fact


_fact_attempt = 0.0


def fact_for_screen(db: Session) -> str:
    """El dato del día para la pantalla: si aún no hay, lo intenta como mucho una vez
    por hora (la pantalla lo pide cada pocos minutos)."""
    global _fact_attempt
    fact = fact_of_day(db, generate=False)
    if fact or time.time() - _fact_attempt < 3600:
        return fact
    _fact_attempt = time.time()
    return fact_of_day(db)


# ---------------------------------------------------------------- estadísticas del estudio


def studio_stats(db: Session, now: datetime | None = None) -> dict:
    from sqlalchemy import select

    from app.models import Job, Project

    now = now or datetime.now()
    edits = db.scalars(select(Job).where(Job.stage == "edit", Job.status == "done")).all()
    week = {j.project_id for j in edits if j.finished_at and (now - j.finished_at).days < 7}
    month = {j.project_id for j in edits if j.finished_at and (now - j.finished_at).days < 30}
    projects = db.scalars(select(Project)).all()
    return {
        "videos_week": len(week),
        "videos_month": len(month),
        "projects": len(projects),
        "published": sum(1 for p in projects if p.status == "Publicado"),
    }
