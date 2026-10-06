"""PERFIL: de quién es este programa (nombre, canal, nicho y país).

Cada ordenador tiene su propia base de datos, así que cada persona que instala Faceless
Studio tiene su perfil. Lo usan los textos para la IA (guiones, JARVIS, aprender…) en vez
de llevar un nombre o un canal escritos a fuego. La primera vez se rellena en
/bienvenida; las instalaciones de antes (que ya tenían proyectos) heredan el perfil del
canal original para que no cambie nada.
"""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

KEY = "profile"
DEFAULT_NICHE = "documentales sobre marcas y empresas que suben y caen"
# País → región de Google Noticias (gl). El idioma es siempre español.
COUNTRIES = {
    "Colombia": "CO",
    "México": "MX",
    "España": "ES",
    "Argentina": "AR",
    "Chile": "CL",
    "Perú": "PE",
    "Venezuela": "VE",
    "Ecuador": "EC",
    "Estados Unidos": "US",
    "Otro": "US",
}
EMPTY = {"owner": "", "channel": "", "niche": DEFAULT_NICHE, "country": "Colombia"}
# La instalación original, de antes de que existiera el perfil.
ORIGINAL = {
    "owner": "Simón",
    "channel": "Anatomía De Una Marca",
    "niche": DEFAULT_NICHE,
    "country": "Colombia",
    "handle": "@AnatomiaDeUnaMarca",
}


def get(db: Session) -> dict:
    try:
        saved = json.loads(get_setting(db, KEY) or "{}")
    except ValueError:
        saved = {}
    return {**EMPTY, **{k: v for k, v in saved.items() if k in EMPTY and v}}


def is_set(db: Session) -> bool:
    return bool(get_setting(db, KEY))


def save(db: Session, owner: str, channel: str, niche: str, country: str, handle: str = "") -> dict:
    data = {
        "owner": " ".join(owner.split())[:40],
        "channel": " ".join(channel.split())[:80],
        "niche": " ".join(niche.split())[:160] or DEFAULT_NICHE,
        "country": country if country in COUNTRIES else "Otro",
    }
    set_setting(db, KEY, json.dumps(data, ensure_ascii=False))
    if handle.strip():
        set_setting(db, "youtube_channel", handle.strip()[:120])
    return get(db)


def migrate(db: Session) -> None:
    """Instalaciones de antes del perfil: si ya había proyectos, es el canal original."""
    from app.models import Project

    if is_set(db) or not db.scalar(select(func.count()).select_from(Project)):
        return
    handle = "" if get_setting(db, "youtube_channel") else ORIGINAL["handle"]
    save(db, **{k: ORIGINAL[k] for k in ("owner", "channel", "niche", "country")}, handle=handle)


def owner(db: Session) -> str:
    """El nombre de quien usa el programa ("" si aún no lo dijo)."""
    return get(db)["owner"]


def region(db: Session) -> str:
    return COUNTRIES.get(get(db)["country"], "US")


def about(db: Session) -> str:
    """Una frase para los textos de la IA: de qué es el canal y quién lo lleva."""
    p = get(db)
    channel = f"«{p['channel']}», un canal" if p["channel"] else "un canal"
    who = f" Lo lleva {p['owner']}" if p["owner"] else " Lo lleva su creador"
    where = f", desde {p['country']}" if p["country"] != "Otro" else ""
    return f"{channel} de YouTube en español sin rostro (faceless) de {p['niche']}.{who}{where}."
