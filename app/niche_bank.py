"""BANCO DE HISTORIAS PARA CUALQUIER NICHO.

El banco de 80 historias (ideas_bank.py) es de marcas y empresas. Para los demás nichos
(misterios, finanzas, historia…) Gemini crea UNA vez un banco de 30 temas reales del nicho
del canal, con formatos distintos y un gancho, y se guarda. Después JARVIS lo ofrece sin
gastar IA, igual que el de marcas, y no vuelve a ofrecer los temas ya hechos.
"""

import json
import unicodedata

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

KEY = "niche_bank_{}"  # por canal
SIZE = 30
MIN_IDEAS = 10  # con menos, Gemini no hizo bien el banco: no se guarda


class BankIdea(BaseModel):
    topic: str = Field(description="Tema real y concreto del vídeo (con su protagonista)")
    format: str = Field(description="Formato: el nombre de una de las estructuras del nicho")
    hook: str = Field(description="El dato o la pregunta que engancha, en una frase")


class Bank(BaseModel):
    ideas: list[BankIdea]


def _key(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if ch.isalnum())


def prompt(kit, language: str) -> str:
    formats = ", ".join(s.name for s in kit.structures) or "variados"
    return f"""Eres guionista de un canal de YouTube sin rostro sobre: «{kit.niche}», en
{language}. Público: {kit.audience}.

Crea un BANCO DE {SIZE} TEMAS DE VÍDEO del nicho, todos REALES y comprobables con fuentes
(personas, casos, hechos y lugares que existen de verdad; nada inventado). Variados: de
distintas épocas y países (incluye España y Latinoamérica si encajan) y repartidos entre
estos formatos: {formats}. Para cada tema, un gancho de una frase con el dato o la
pregunta que hace que alguien quiera verlo. Sin repetir temas."""


def stored(db: Session, channel, niche: str) -> list[dict] | None:
    """El banco guardado del canal, si es del nicho actual (si cambia el nicho, no vale)."""
    if channel is None:
        return None
    try:
        data = json.loads(get_setting(db, KEY.format(channel.id)) or "null")
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("niche") != niche:
        return None
    ideas = [
        {
            "topic": str(i["topic"]),
            "format": str(i.get("format", "")),
            "hook": str(i.get("hook", "")),
        }
        for i in data.get("ideas") or []
        if isinstance(i, dict) and i.get("topic")
    ]
    return ideas or None


def generate(db: Session, channel, kit, ai) -> list[dict]:
    """Gemini crea el banco (una vez por nicho) y se guarda. Los errores de Gemini suben
    (ProviderError) para que JARVIS diga qué pasó."""
    language = getattr(channel, "language", "") or "Español"
    bank = ai.generate_json(prompt(kit, language), Bank)
    ideas, seen = [], set()
    for idea in bank.ideas:
        topic, hook = idea.topic.strip(), idea.hook.strip()
        if len(_key(topic)) < 4 or _key(topic) in seen:  # vacío, solo símbolos o repetido
            continue
        seen.add(_key(topic))
        ideas.append({"topic": topic, "format": idea.format.strip(), "hook": hook})
    ideas = ideas[:SIZE]
    if len(ideas) < MIN_IDEAS:
        return []
    payload = {"niche": kit.niche, "ideas": ideas}
    set_setting(db, KEY.format(channel.id), json.dumps(payload, ensure_ascii=False))
    return ideas


def _done(topic: str, done_keys: str) -> bool:
    key = _key(topic)[:40]
    return bool(key) and key in done_keys


def progress(ideas: list[dict], done_topics: list[str]) -> tuple[int, int]:
    """Cuántos temas del banco ya se hicieron, de cuántos."""
    done = " ".join(_key(t) for t in done_topics)
    return sum(1 for i in ideas if _done(i["topic"], done)), len(ideas)


def fresh(ideas: list[dict], done_topics: list[str], limit: int = 5) -> list[dict]:
    """Temas aún no hechos, sin repetir formato seguido si se puede."""
    done = " ".join(_key(t) for t in done_topics)
    pending = [i for i in ideas if not _done(i["topic"], done)]
    chosen: list[dict] = []
    while pending and len(chosen) < limit:
        formats = {i["format"] for i in chosen}
        pick = next((i for i in pending if i["format"] not in formats), pending[0])
        chosen.append(pick)
        pending.remove(pick)
    return chosen
