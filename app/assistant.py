"""JARVIS: el asistente que maneja el estudio por mensajes (Telegram).

Aquí está el «cerebro»: entiende lo que le escribes, crea proyectos, te avisa cuando
termina cada paso y lleva el piloto automático. No sabe nada de Telegram: devuelve
respuestas (`Reply`) y `app/telegram.py` se encarga de enviarlas.
"""

import json
import logging
import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agenda, coach, ideas_bank, jobs, learning, skills
from app.media import project_dir
from app.models import DURATIONS, STAGES, Channel, Job, Project, User
from app.pipeline.monetization import project_review, summary_text
from app.pipeline.render import run_ffmpeg
from app.providers.ai import GroundedText, ProviderError
from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

MAX_CHATS = 4
TELEGRAM_TEXT_LIMIT = 4000
TEASER_SECONDS = 60

Buttons = list[list[tuple[str, str]]]  # filas de botones (texto, dato)


@dataclass
class Reply:
    text: str = ""
    buttons: Buttons | None = None
    video: Path | None = None
    photos: list[Path] = field(default_factory=list)  # p. ej. las 3 miniaturas
    chat_id: int | None = None  # None: a todos los chats vinculados
    action: str = ""  # para la pantalla JARVIS: «sleep» = volver a dormir


@dataclass
class Incoming:
    chat_id: int
    name: str = ""
    text: str = ""
    button: str = ""  # dato del botón pulsado
    audio: bytes | None = None
    audio_type: str = "audio/ogg"
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- utilidades


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, letra a letra (mantiene las posiciones del texto)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text.lower())


def _json_setting(db: Session, key: str, default):
    raw = get_setting(db, key)
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def _save_json(db: Session, key: str, value) -> None:
    set_setting(db, key, json.dumps(value, ensure_ascii=False))


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Corta un texto largo en trozos que quepan en un mensaje, por párrafos."""
    parts, current = [], ""
    for block in text.split("\n"):
        while len(block) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(block[:limit])
            block = block[limit:]
        candidate = f"{current}\n{block}" if current else block
        if len(candidate) > limit:
            parts.append(current)
            current = block
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts or [""]


def _minutes(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02}"


# ---------------------------------------------------------------- vincular chats


def linked_chats(db: Session) -> list[dict]:
    return _json_setting(db, "telegram_chats", [])


def link_code(db: Session) -> str:
    """Código de 6 cifras que hay que enviar al bot para vincular el chat."""
    code = get_setting(db, "telegram_code")
    if not code:
        code = f"{random.SystemRandom().randint(0, 999999):06}"
        set_setting(db, "telegram_code", code)
    return code


def unlink_chat(db: Session, chat_id: int) -> None:
    _save_json(db, "telegram_chats", [c for c in linked_chats(db) if c["id"] != chat_id])


def _try_link(db: Session, msg: Incoming) -> list[Reply]:
    digits = re.sub(r"\D", "", msg.text)
    if digits and digits == link_code(db):
        chats = linked_chats(db)
        if len(chats) >= MAX_CHATS:
            return [Reply("Ya hay demasiados chats vinculados. Quita uno en la página JARVIS.")]
        chats.append({"id": msg.chat_id, "name": msg.name})
        _save_json(db, "telegram_chats", chats)
        set_setting(db, "telegram_code", "")  # el código no se puede reutilizar
        _mark_old_jobs_notified(db)
        return [
            Reply(
                f"🤖 <b>Sistemas en línea.</b> Hola, {escape(msg.name or 'jefe')}. "
                "Desde ahora te aviso de todo lo que pase en el estudio."
            ),
            *help_replies(),
        ]
    return [
        Reply(
            "🔒 Hola. Todavía no te conozco. Escríbeme el <b>código de 6 cifras</b> que "
            "aparece en el programa, en la página <b>JARVIS</b>."
        )
    ]


def _mark_old_jobs_notified(db: Session) -> None:
    """Al vincular, lo que ya terminó antes no se avisa (solo lo nuevo)."""
    for job in db.scalars(
        select(Job).where(Job.status.in_(("done", "failed")), Job.notified.is_(None))
    ):
        job.notified = True
    db.commit()


# ---------------------------------------------------------------- entender mensajes


class Intent(BaseModel):
    action: Literal[
        "new_video",
        "status",
        "ideas",
        "queue_add",
        "queue_show",
        "autopilot",
        "task_add",
        "task_list",
        "task_done",
        "briefing",
        "time",
        "sleep",
        "help",
        "chat",
        "reminder",
        "timer",
        "reminder_list",
        "news",
        "radar",
        "channel",
        "dollar",
        "forecast",
        "fact",
        "open",
        "stats",
        "performance",
        "analyze",
        "next_step",
        "monetize",
        "review",
        "idea_bank",
        "week_plan",
        "publish_day",
        "learn_video",
        "question",
        "remember",
        "memory",
    ]
    topic: str = Field(default="", description="Tema del vídeo, si pide uno")
    topics: list[str] = Field(default_factory=list, description="Temas para la cola")
    duration: str = Field(default="", description="Duración pedida, p. ej. «10 minutos»")
    on: bool | None = Field(default=None, description="Encender/apagar el piloto automático")
    task: str = Field(default="", description="Texto de la tarea o del recordatorio")
    when: str = Field(default="", description="Cuándo, tal cual lo dijo: «a las 5», «en 10 min»")
    target: str = Field(default="", description="Qué abrir o qué buscar")
    reply: str = Field(default="", description="Respuesta corta si es una conversación")


VIDEO_REQUEST = re.compile(
    r"(?:^|\b)(?:/video|/nuevo|haz(?:me)?(?: un)?|crea(?:me)?(?: un)?|quiero(?: un)?|"
    r"prepara(?:me)?(?: un)?|nuevo|otro)\s+(?:video|documental|short)s?\b"
    r"(?:\s+(?:corto|largo))?(?:\s+de\s+\d+\s*min\w*)?\s*(?:sobre|de|acerca de|del|:)?\s*"
)
SLASH_VIDEO = re.compile(r"^/(?:video|nuevo)\s+")


def parse_duration(text: str) -> str:
    norm = normalize(text)
    if re.search(r"\b(short|corto|vertical)\b", norm):
        return "Short"
    match = re.search(r"(\d+)\s*min", norm)
    if not match:
        return ""
    minutes = int(match.group(1))
    if minutes <= 1:
        return "Short"
    if minutes <= 5:
        return "3–5 min"
    if minutes <= 10:
        return "5–10 min"
    if minutes <= 15:
        return "10–15 min"
    return "15–30 min"


def _clean_topic(topic: str) -> str:
    topic = re.sub(r"\s+de\s+\d+\s*min\w*\s*$", "", topic.strip(), flags=re.I)
    return topic.strip(" .,:;¡!¿?\"'«»").strip()


WAKE_WORD = re.compile(r"^\W*(?:oye\s+|hola\s+|ok\s+)?(?:jarvis|yarvis|harvey|jarbis)\b[\s,.:!]*")
TASK_ADD = re.compile(
    r"^(?:anota(?:me)?|apunta(?:me)?|recuerdame|agrega (?:la )?tarea|anade (?:la )?tarea|"
    r"nueva tarea|tarea nueva|crea (?:una )?tarea)\s*:?\s+(?:que\s+)?"
)
TASK_DONE = re.compile(
    r"^(?:ya (?:hice|termine|complete)|termine|complete|completa(?:r)?|marca(?:r)? como hecha|"
    r"tache|tacha|borra (?:la )?tarea|quita (?:la )?tarea|lista la tarea|hecha la tarea)"
    r"\s*:?\s*(?:la tarea\s+|la\s+)?"
)


# Preguntas claras de cualquier tema (lo demás lo clasifica la IA). Van al final de
# quick_intent: las órdenes del estudio («¿cómo va el canal?», «¿qué hago ahora?») ganan.
QUESTION = re.compile(
    r"^[¿\s]*(?:y\s+)?(?:que|cual|cuales|donde|cuando|como|quien|quienes|cuanto|cuanta|cuantos|"
    r"cuantas|por que|para que|recomiendame|recomienda|sabes|hay|dime|explicame|"
    r"busca(?:me)?|en que|a que hora|de que)\b"
)
# Pedidos de datos en cualquier parte de la frase («Exactamente, necesito que me digas…»).
INFO_REQUEST = re.compile(
    r"\b(?:dime|digas|decirme|quiero saber|necesito saber|averigua|averiguame|investiga|"
    r"recomiendame|recomiendas|recomendarme|recomiendeme|cartelera|horarios?|"
    r"cuanto cuesta|cuanto vale|precio de|que peliculas|que pelicula)\b"
)
# Temas que ya tienen su propia habilidad (más rápida que buscar en Google): esas
# preguntas las clasifica la IA.
STUDIO_WORDS = re.compile(
    r"\b(?:clima|tiempo|llueve|lluvia|temperatura|dolar|noticias?|radar|canal|videos?|"
    r"shorts?|tareas?|recordatorios?|temporizador|proyectos?|suscriptores|visitas|estado|"
    r"monetiz\w*|plan|ideas?|cola|piloto|guion|miniaturas?)\b"
)
# Respuestas de charla que en realidad dicen «no puedo saberlo»: entonces se busca.
REFUSAL = re.compile(
    r"no (?:puedo|tengo acceso|dispongo)|mis sistemas|en tiempo real|le sugiero consultar|"
    r"revise (?:la|su)|consultar directamente|no tengo (?:informacion|datos)"
)
REMEMBER = re.compile(r"^(?:recuerda|acuerdate de|no olvides|ten en cuenta)\s+que\s+")
MEMORY_WORDS = ("que sabes de mi", "que recuerdas", "que recuerdas de mi", "tu memoria")
MEMORY_KEY = "jarvis_memory"
MAX_MEMORY = 40
WEEK_PLAN_WORDS = (
    "plan de la semana",
    "plan semanal",
    "calendario",
    "que publico",
    "que publico esta semana",
    "que subo esta semana",
    "/semana",
)
DAY_NAMES = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
PUBLISH_DAY = re.compile(
    r"^(?:publico|publicare|quiero publicar|publicar|dia de publicacion:?)\s+"
    r"(?:los |el |cada )?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)s?"
    r"(?:\s+a las\s+(\d{1,2}))?"
)
IDEA_BANK_WORDS = {  # frase → región ("" = todas)
    "banco de ideas": "",
    "ideas clasicas": "",
    "ideas del banco": "",
    "/banco": "",
    "ideas de espana": "España",
    "ideas espana": "España",
    "ideas de latinoamerica": "Latinoamérica",
    "ideas latinoamerica": "Latinoamérica",
    "ideas latinas": "Latinoamérica",
}
NEXT_STEP_WORDS = (
    "que hago",
    "que hago ahora",
    "que sigue",
    "que me toca",
    "y ahora que",
    "siguiente paso",
    "proximo paso",
    "que falta",
    "/siguiente",
)
MONETIZE_WORDS = (
    "cuanto falta para monetizar",
    "cuanto me falta para monetizar",
    "cuanto me falta",
    "cuando monetizo",
    "cuando voy a monetizar",
    "como voy para monetizar",
    "como va la monetizacion",
    "monetizacion",
    "meta de monetizacion",
    "camino a monetizar",
    "/monetizar",
)
REVIEW_WORDS = (
    "se puede monetizar",
    "se podra monetizar",
    "es monetizable",
    "revisa el video",
    "revisalo",
    "control de calidad",
    "esta listo para subir",
    "puedo subirlo",
    "/revisar",
)
REVIEW_PROJECT = re.compile(
    r"^(?:(?:revisa|revisar|/revisar)(?: el| del)? video|control de calidad)"
    r"(?: de la| de| del| sobre)?\s+(.+)"
)


def quick_intent(text: str) -> Intent | None:
    """Órdenes habituales sin gastar IA."""
    wake = WAKE_WORD.match(normalize(text))
    if wake:  # «Jarvis, …»: se quita el nombre
        text = text[wake.end() :]
        if not text.strip():
            return Intent(action="briefing")
    norm = normalize(text).strip()
    bare = norm.strip(" .!?¡¿")
    link = learning.find_link(text)
    if link:
        return Intent(action="learn_video", target=link)
    skill = skills.quick(text, norm)
    if skill:
        return skill
    if bare in (
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "resumen",
        "resumen del dia",
        "informe del dia",
        "que hay para hoy",
        "despierta",
        "/resumen",
    ):
        return Intent(action="briefing")
    if bare in (
        "tareas",
        "/tareas",
        "mis tareas",
        "que tengo hoy",
        "que tengo que hacer",
        "pendientes",
        "agenda",
        "que hay pendiente",
        "lista de tareas",
    ):
        return Intent(action="task_list")
    if bare in ("que hora es", "hora", "que dia es", "que dia es hoy", "fecha"):
        return Intent(action="time")
    if bare in (
        "descansa",
        "duerme",
        "a dormir",
        "apagate",
        "gracias",
        "gracias jarvis",
        "eso es todo",
        "hasta luego",
        "adios",
        "chao",
    ):
        return Intent(action="sleep")
    match = TASK_ADD.match(norm)
    if match and text[match.end() :].strip():
        return Intent(action="task_add", task=text[match.end() :].strip(" .,:;"))
    match = TASK_DONE.match(norm)
    if match and text[match.end() :].strip():
        return Intent(action="task_done", task=text[match.end() :].strip(" .,:;"))
    if bare in ("/start", "start", "ayuda", "/ayuda", "/help", "help", "menu", "/menu", "hola"):
        return Intent(action="help")
    if bare in ("estado", "/estado", "como va", "como vamos", "que haces", "reporte", "informe"):
        return Intent(action="status")
    if bare in ("ideas", "/ideas", "dame ideas", "sugerencias"):
        return Intent(action="ideas")
    match = REMEMBER.match(norm)
    if match and text[match.end() :].strip():
        return Intent(action="remember", task=text[match.end() :].strip(" .,:;"))
    if bare in MEMORY_WORDS:
        return Intent(action="memory")
    if bare in WEEK_PLAN_WORDS:
        return Intent(action="week_plan")
    match = PUBLISH_DAY.match(bare)
    if match:
        return Intent(action="publish_day", when=match.group(1), task=match.group(2) or "")
    if bare in IDEA_BANK_WORDS:
        return Intent(action="idea_bank", topic=IDEA_BANK_WORDS[bare])
    if bare in NEXT_STEP_WORDS:
        return Intent(action="next_step")
    if bare in MONETIZE_WORDS:
        return Intent(action="monetize")
    if bare in REVIEW_WORDS:
        return Intent(action="review")
    match = REVIEW_PROJECT.match(bare)
    if match:
        return Intent(action="review", topic=match.group(1))
    if bare in ("cola", "/cola", "ver cola", "la cola"):
        return Intent(action="queue_show")
    if bare.startswith(("/piloto", "piloto")):
        on = None
        if re.search(r"\b(on|si|enciende|encender|activa|activar)\b", bare):
            on = True
        if re.search(r"\b(off|no|apaga|apagar|desactiva|desactivar|para)\b", bare):
            on = False
        return Intent(action="autopilot", on=on)
    match = re.match(r"^(?:/cola|cola|agrega a la cola|anade a la cola)\s*:?\s+", norm)
    if match:
        topics = [t.strip() for t in re.split(r"[;,\n]", text[match.end() :]) if t.strip()]
        return Intent(action="queue_add", topics=topics)
    match = SLASH_VIDEO.match(norm) or VIDEO_REQUEST.search(norm)
    if match:
        topic = _clean_topic(text[match.end() :])
        if topic:
            return Intent(action="new_video", topic=topic, duration=text[: match.end()])
    asks = QUESTION.match(norm) or INFO_REQUEST.search(norm)
    if asks and len(bare.split()) >= 3 and not STUDIO_WORDS.search(norm):
        return Intent(action="question")  # se contesta buscando en Google, sin más pasos
    return None


# Lo último que se habló en cada chat, para que JARVIS siga el hilo de la conversación.
MEMORY_TURNS = 6
_memory: dict[int, list[tuple[str, str]]] = {}


def remember(chat_id: int, said: str, replies: list[Reply]) -> None:
    from app.jarvis_voice import spoken_text

    answer = " ".join(spoken_text(r.text) for r in replies)[:500]
    turns = _memory.setdefault(chat_id, [])
    turns.append((said[:300], answer))
    del turns[:-MEMORY_TURNS]


def _context(db: Session, chat_id: int) -> str:
    now = datetime.now()
    lines = [f"Fecha y hora: {agenda.spoken_date(now)} de {now.year}, {agenda.spoken_time(now)}."]
    channel = cached_channel_summary(db)
    if channel:
        lines.append(f"Canal de YouTube: {channel}.")
    headlines = [n["title"] for n in (info_cache_news(db))[:5]]
    if headlines:
        lines.append("Titulares de negocios de hoy: " + " | ".join(headlines))
    facts = _json_setting(db, MEMORY_KEY, [])
    if facts:
        lines.append("Lo que sabes del creador: " + " | ".join(facts))
    talk = "\n".join(f"Creador: {a}\nJARVIS: {b}" for a, b in _memory.get(chat_id, []))
    if talk:
        lines.append("CONVERSACIÓN RECIENTE:\n" + talk)
    return "\n".join(lines)


def cached_channel_summary(db: Session) -> str:
    """Resumen del canal solo si ya está descargado (para no hacer esperar a JARVIS)."""
    from app import info

    if any(key.startswith("youtube:") and hit[1] for key, hit in info._cache.items()):
        return skills.channel_summary(db)  # se sirve de la caché, sin ir a internet
    return ""


def info_cache_news(db: Session) -> list[dict]:
    """Solo las noticias ya descargadas (para no hacer esperar a la IA)."""
    from app import info

    hit = info._cache.get("news:business")
    return hit[1] if hit and hit[1] else []


def _ai_intent(db: Session, text: str, chat_id: int = 0) -> Intent:
    ai = jobs.get_ai_provider(db)
    prompt = f"""Eres JARVIS, el asistente del estudio de YouTube «Faceless Studio» (canal de
documentales sin rostro sobre marcas: «Anatomía De Una Marca»). Clasifica el mensaje:
- new_video: quiere un vídeo nuevo (topic = el tema, duration si la dice).
- status: pregunta cómo va la producción.
- ideas: pide ideas o temas para vídeos.
- queue_add: quiere dejar varios temas en la cola del piloto automático (topics).
- queue_show: quiere ver la cola.
- autopilot: encender o apagar el piloto automático (on).
- task_add: quiere anotar una tarea o recordatorio (task = el texto).
- task_list: pregunta qué tareas o pendientes tiene.
- task_done: dice que ya hizo una tarea o quiere quitarla (task = cuál).
- briefing: pide el resumen del día o te saluda para empezar.
- time: pregunta la hora o la fecha.
- sleep: se despide o te manda a descansar.
- reminder: quiere que le recuerdes algo a una hora (task = qué, when = cuándo).
- timer: quiere un temporizador (when = «en 10 minutos»).
- reminder_list: pregunta qué recordatorios tiene.
- news: pide noticias. radar: pregunta por marcas o empresas en crisis/noticias de marcas.
- channel: pregunta por su canal de YouTube (suscriptores, visitas, vídeos).
- dollar: pregunta el precio del dólar. forecast: pregunta el clima o el pronóstico.
- fact: pide un dato curioso. stats: pide estadísticas de lo producido.
- performance: pregunta cómo van sus vídeos publicados (visitas, resultados).
- analyze: pide que analices el canal o qué aprendiste de los resultados.
- idea_bank: pide ideas del banco de historias, o de España o Latinoamérica
  (topic = «España», «Latinoamérica» o vacío).
- week_plan: pregunta qué publicar esta semana o por el plan o calendario.
- publish_day: dice qué día (y hora) quiere publicar (when = el día en minúsculas sin
  tilde, p. ej. «jueves»; task = la hora en número si la dice).
- next_step: pregunta qué hacer ahora, qué falta o cuál es el siguiente paso.
- monetize: pregunta cuánto le falta para monetizar o para el Programa de Socios.
- review: pregunta si un vídeo se puede monetizar o pide revisarlo antes de subirlo
  (topic = de qué vídeo, si lo dice).
- open: quiere abrir una página, app o proyecto, buscar algo o poner música
  (target = qué; «google:…» para buscar, «youtube:…» para música o vídeos).
- help: pregunta qué puedes hacer.
- question: CUALQUIER pregunta que necesite datos o saber algo, de cualquier tema
  (cultura, actualidad, deportes, precios, salud, cocina, cómo se hace algo, marcas,
  YouTube…). No respondas tú: la contestará JARVIS buscando en Google.
- remember: quiere que recuerdes algo de él para siempre (task = el dato).
- chat: solo charla, saludos, opiniones o ánimo que no necesitan datos. NUNCA digas
  que no puedes acceder a información: si pide datos de lo que sea, es «question». Responde en
  «reply» en 1–4 frases, en español, con el tono de JARVIS: educado, preciso, con un toque
  de humor británico; trátalo de «usted» y de vez en cuando llámalo «señor».

ESTADO ACTUAL DEL ESTUDIO:
{status_text(db, html=False)}
{_context(db, chat_id)}

MENSAJE: {text}"""
    # Modo rápido (sin «pensar») si el proveedor lo tiene: entender una orden no necesita más.
    intent = getattr(ai, "quick_json", ai.generate_json)(prompt, Intent)
    jobs.remember_working_model(db, ai)
    return intent


# ---------------------------------------------------------------- respuestas


def help_replies() -> list[Reply]:
    return [
        Reply(
            "Esto es lo que puedo hacer:\n\n"
            "🎬 <b>«Hazme un vídeo sobre Kodak»</b> — investigo, te propongo 3 enfoques y, "
            "cuando elijas, hago todo: guion, voz, imágenes, montaje y textos.\n"
            "💡 <b>«ideas»</b> — te propongo temas para el canal.\n"
            "📚 <b>«banco de ideas»</b>, <b>«ideas de España»</b>, <b>«ideas de "
            "Latinoamérica»</b> — historias reales ya elegidas, con formatos variados.\n"
            "📊 <b>«estado»</b> — cómo va todo.\n"
            "👉 <b>«¿qué hago ahora?»</b> — el siguiente paso de cada vídeo, con un botón.\n"
            "🗓️ <b>«plan de la semana»</b> — qué vídeo y qué Shorts publicar cada día; "
            "<b>«publico los jueves a las 18»</b> para elegir tu día.\n"
            "💰 <b>«¿cuánto me falta para monetizar?»</b> — suscriptores, horas y consejos.\n"
            "🔎 <b>«¿se puede monetizar?»</b> o <b>«revisa el vídeo de Nokia»</b> — la nota "
            "del control de calidad.\n"
            "🛫 <b>«cola: Nokia, Blockbuster, Kodak»</b> — los dejo en fila y el piloto "
            "automático hace uno al día.\n"
            "📝 <b>«anota: comprar micrófono»</b>, <b>«tareas»</b>, <b>«ya hice lo del "
            "micrófono»</b> — tu lista del día.\n"
            "☀️ <b>«resumen»</b> — el informe del día (tiempo, tareas y producción).\n"
            "⏰ <b>«recuérdame a las 5 llamar a Juan»</b>, <b>«temporizador de 10 minutos»</b>.\n"
            "📺 <b>«¿cómo va el canal?»</b> — suscriptores, visitas y últimos vídeos.\n"
            "📡 <b>«radar»</b> — marcas en apuros esta semana (ideas de vídeo); "
            "<b>«noticias»</b>, <b>«dólar»</b>, <b>«clima»</b>, <b>«dato curioso»</b>.\n"
            "🖥️ <b>«abre YouTube Studio»</b>, <b>«busca…»</b>, <b>«pon música lofi»</b>.\n"
            "🎓 <b>Mándame un enlace de YouTube</b> y lo veo: te digo lo bueno y cómo "
            "aplicarlo a tu canal.\n"
            "❓ <b>Pregúntame lo que sea</b> (cultura, noticias, deportes, cómo hacer algo…): "
            "lo busco en Google.\n"
            "🧠 <b>«recuerda que…»</b> y lo tendré siempre en cuenta; <b>«¿qué sabes de "
            "mí?»</b>.\n"
            "💬 Recuerdo la conversación.\n"
            "🎙️ También puedes <b>mandarme notas de voz</b>.",
            buttons=[
                [("📊 Estado", "status"), ("💡 Ideas", "ideas")],
                [("👉 ¿Qué hago ahora?", "next"), ("💰 Monetización", "money")],
                [("🛫 Piloto automático", "autopilot")],
            ],
        )
    ]


def _active_projects(db: Session) -> list[Project]:
    rows = db.scalars(select(Job).where(Job.status.in_(("queued", "running")))).all()
    ids = sorted({j.project_id for j in rows})
    return [p for p in (db.get(Project, i) for i in ids) if p]


def status_text(db: Session, html: bool = True) -> str:
    def b(text: str) -> str:
        return f"<b>{escape(text)}</b>" if html else text

    lines = []
    for project in _active_projects(db):
        for stage, job in jobs.latest_jobs(db, project.id).items():
            if job.active:
                state = f"{job.progress}% · {job.message}" if job.status == "running" else "en cola"
                lines.append(f"🎬 {b(project.title)} — {STAGES[stage]}: {escape(state)}")
    waiting = _waiting_choice(db)
    for project in waiting:
        lines.append(f"🧭 {b(project.title)} — esperando que elijas un enfoque")
    pilot = autopilot_state(db)
    if pilot["queue"]:
        lines.append(
            f"🛫 Cola del piloto automático: {len(pilot['queue'])} tema(s), "
            f"{'encendido' if pilot['on'] else 'apagado'}"
        )
    if not lines:
        return "😌 Todo tranquilo: no hay nada en producción. ¿Hacemos un vídeo?"
    return "\n".join(lines)


def _waiting_choice(db: Session) -> list[Project]:
    waiting = []
    for project in db.scalars(select(Project).order_by(Project.id.desc()).limit(10)):
        strategy = jobs.get_result(db, project.id, "strategy")
        if strategy and not strategy.get("selected") and strategy.get("concepts"):
            if not jobs.get_result(db, project.id, "script"):
                waiting.append(project)
    return waiting


def _defaults(db: Session) -> dict:
    """Las opciones del último vídeo (canal, duración, idioma, tipo)."""
    last = db.scalar(select(Project).order_by(Project.id.desc()).limit(1))
    if last:
        return {
            "channel_id": last.channel_id,
            "duration": last.duration,
            "language": last.language,
            "video_type": last.video_type,
        }
    channel = db.scalar(select(Channel).order_by(Channel.id).limit(1))
    return {
        "channel_id": channel.id if channel else None,
        "duration": "10–15 min",
        "language": channel.language if channel else "Español",
        "video_type": "Documental",
    }


def start_video(db: Session, topic: str, duration: str = "", mode: str = "asistido") -> Project:
    """Crea el proyecto y empieza a investigar. «asistido»: se para a que elijas enfoque."""
    defaults = _defaults(db)
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None or defaults["channel_id"] is None:
        raise ProviderError("Primero abre el programa en el ordenador, crea tu cuenta y un canal.")
    project = Project(
        channel_id=defaults["channel_id"],
        title=topic[:200],
        topic=topic,
        duration=duration if duration in DURATIONS else defaults["duration"],
        language=defaults["language"],
        video_type=defaults["video_type"],
        automation_mode=mode,
        created_by=user.id,
    )
    db.add(project)
    db.commit()
    jobs.enqueue(db, project.id, "research")
    return project


def _new_video(db: Session, topic: str, duration_hint: str) -> list[Reply]:
    project = start_video(db, topic, parse_duration(duration_hint))
    return [
        Reply(
            f"🫡 Entendido. Empiezo a investigar <b>{escape(project.title)}</b> "
            f"({escape(project.video_type)}, {escape(project.duration)}).\n"
            "Te escribo cuando tenga los enfoques para que elijas."
        )
    ]


# ---------------------------------------------------------------- entrenador del canal

GO_LABELS = {
    "choose": "🧭 Ver enfoques",
    "pick_thumb": "🎨 Ver miniaturas",
    "review": "🔎 Ver qué falta",
    "upload": "🔎 Revisión final",
}


def _step_button(project: Project, step: dict, n: int) -> tuple[str, str] | None:
    stage = step["stage"]
    if stage is None:
        return None
    if stage in GO_LABELS:
        data = {"choose": "concepts", "pick_thumb": "thumbs"}.get(stage, "qc")
        return (f"{n}. {GO_LABELS[stage]}", f"{data}:{project.id}")
    return (f"{n}. ▶️ {coach.STEP_LABELS[stage]}", f"go:{project.id}:{stage}")


def next_step_replies(db: Session) -> list[Reply]:
    steps = coach.next_steps(db)
    if not steps:
        return [
            Reply(
                "😌 No tienes vídeos a medias. ¿Empezamos uno? Di «ideas» o "
                "«hazme un vídeo sobre…».",
                buttons=[[("💡 Ideas", "ideas")]],
            )
        ]
    lines, buttons = ["👉 <b>Qué hacer ahora</b>"], []
    for n, (project, step) in enumerate(steps, 1):
        lines.append(f"{n}. <b>{escape(project.title)}</b> — {escape(step['text'])}")
        button = _step_button(project, step, n)
        if button:
            buttons.append([button])
    return [Reply("\n".join(lines), buttons=buttons or None)]


def learn_video_replies(db: Session, url: str) -> list[Reply]:
    ai = jobs.get_ai_provider(db)
    item = learning.learn(db, url, ai)
    jobs.remember_working_model(db, ai)
    return [
        Reply(
            "🎓 " + escape(learning.lesson_text(item)),
            buttons=[[("📌 Aplicar en mis guiones", f"lesson:{item['id']}")]],
        )
    ]


def week_plan_reply(db: Session) -> Reply:
    plan = coach.weekly_plan(db)
    lines = ["🗓️ <b>Plan de la semana</b>", f"🎬 {escape(plan['long'])}"]
    if plan["shorts"]:
        shorts = ", ".join(f"{day}: «{escape(title)}»" for day, title in plan["shorts"])
        lines.append(f"📱 Shorts — {shorts}.")
    else:
        lines.append("📱 No hay Shorts preparados: sácalos de tu último vídeo (pestaña Shorts).")
    lines.append(f"📚 Hoy, 30 minutos para aprender: {escape(plan['learning'])}.")
    day = agenda.WEEKDAYS[plan["publish_day"]]
    lines.append(
        f"<i>Publicas los {day} a las {plan['publish_hour']}:00. Para cambiarlo di, por "
        "ejemplo: «publico los martes a las 19».</i>"
    )
    return Reply("\n".join(lines), buttons=[[("👉 ¿Qué hago ahora?", "next")]])


def monetization_text(path: dict) -> str:
    from app.skills import number

    if path["done"]:
        return (
            "🏆 <b>¡Ya cumples los requisitos!</b> Solicita el Programa de Socios en YouTube "
            "Studio → Ganar dinero."
        )
    lines = ["💰 <b>Camino a la monetización</b>"]
    if path["subs"] is not None:
        line = f"👥 {number(path['subs'])} de 1.000 suscriptores ({path['subs_pct']} %)"
        if path["growth"]:
            line += f", +{path['growth']:g} al día".replace(".", ",")
        if path["eta"]:
            line += f". A este ritmo llegas hacia el {agenda.spoken_date(path['eta'])}"
        lines.append(line + ".")
    else:
        lines.append("👥 No pude leer los suscriptores del canal ahora mismo.")
    hours = path["hours"]
    lines.append(
        f"⏱️ Unas {number(round(hours['hours']))} de 4.000 horas vistas en el último año "
        f"({hours['pct']} %), estimadas con {hours['videos']} vídeo(s)."
    )
    lines.append("📱 Otra vía: 10 millones de visitas en Shorts en 90 días.")
    lines += [f"💡 {escape(tip)}" for tip in path["tips"]]
    return "\n".join(lines)


def monetization_reply(db: Session) -> Reply:
    return Reply(
        monetization_text(coach.monetization_path(db)),
        buttons=[[("👉 ¿Qué hago ahora?", "next"), ("📈 Rendimiento", "perf")]],
    )


def _review(db: Session, topic: str = "") -> list[Reply]:
    project = coach.find_project(db, topic)
    if project is None:
        return [
            Reply(
                f"No encontré ningún vídeo sobre «{escape(topic)}»."
                if topic
                else "Todavía no hay ningún vídeo con guion para revisar."
            )
        ]
    return [Reply("🔎 " + escape(coach.review_project(db, project)))]


def bank_replies(db: Session, region: str = "") -> list[Reply]:
    """Historias reales del banco de ideas que aún no se han hecho, con formatos variados."""
    done = [p.topic for p in db.scalars(select(Project))]
    ideas = ideas_bank.fresh_ideas(done, region)
    if not ideas:
        return [Reply("📚 Ya hiciste todas las ideas del banco. Di «ideas» y pienso nuevas.")]
    _save_json(db, "telegram_ideas", [i["topic"] for i in ideas])
    lines = [
        f"{n}. <b>{escape(i['topic'])}</b> <i>({ideas_bank.FORMAT_LABELS[i['format']]}, "
        f"{escape(i['region'])})</i>\n   🪝 {escape(i['hook'])}"
        for n, i in enumerate(ideas, 1)
    ]
    buttons = [[(f"🎬 {n}", f"idea:{n - 1}") for n in range(1, len(ideas) + 1)]]
    buttons.append([("🛫 Todas a la cola", "idea:all"), ("💡 Ideas nuevas", "ideas")])
    title = f"📚 <b>Banco de historias{f' — {escape(region)}' if region else ''}</b>"
    return [Reply(title + "\n\n" + "\n\n".join(lines), buttons=buttons)]


class Idea(BaseModel):
    topic: str = Field(description="Tema concreto del vídeo (marca o empresa y el ángulo)")
    hook: str = Field(description="Por qué engancha, en una frase")
    format: str = Field(default="", description="Formato del vídeo, distinto en cada idea")


class IdeaList(BaseModel):
    ideas: list[Idea]


def _performance_hint(db: Session) -> str:
    from app import analytics

    try:
        return analytics.performance_hint(db)
    except Exception:  # noqa: BLE001 — las ideas no deben fallar por esto
        return ""


def _ideas(db: Session) -> list[Reply]:
    channel = db.get(Channel, _defaults(db)["channel_id"] or 0)
    done = [p.topic for p in db.scalars(select(Project).order_by(Project.id.desc()).limit(40))]
    ai = jobs.get_ai_provider(db)
    name = channel.name if channel else ""
    niche = channel.niche if channel and channel.niche else "historias de marcas y empresas"
    language = channel.language if channel else "Español"
    prompt = f"""Propón 5 ideas de vídeo para el canal de YouTube «{name}»
(temática: {niche}), en {language}.
Busca historias con conflicto real y verificable: auges, caídas, errores, rivalidades,
resurgimientos. Mezcla marcas muy conocidas con alguna sorpresa. Nada de temas inventados.
Usa un FORMATO distinto en cada idea (por ejemplo: ascenso y caída, «los 5 errores»,
rivalidad entre dos marcas, el juicio o escándalo, «qué habría pasado si», la resurrección)
para que el canal no parezca hecho en serie: YouTube no monetiza el contenido repetitivo.
{_performance_hint(db)}
No repitas estos temas ya hechos: {"; ".join(done) or "ninguno"}"""
    try:
        ideas = ai.generate_json(prompt, IdeaList).ideas[:5]
    except ProviderError:
        log.info("Gemini no respondió; uso el banco de ideas", exc_info=True)
        return bank_replies(db)
    jobs.remember_working_model(db, ai)
    if not ideas:
        return [Reply("No se me ocurrió nada bueno ahora. Prueba otra vez en un rato.")]
    _save_json(db, "telegram_ideas", [i.topic for i in ideas])
    lines = [
        f"{n}. <b>{escape(i.topic)}</b>"
        + (f" <i>({escape(i.format)})</i>" if i.format.strip() else "")
        + f"\n   {escape(i.hook)}"
        for n, i in enumerate(ideas, 1)
    ]
    buttons = [[(f"🎬 {n}", f"idea:{n - 1}") for n in range(1, len(ideas) + 1)]]
    buttons.append([("🛫 Todas a la cola", "idea:all")])
    return [Reply("💡 <b>Ideas para el canal</b>\n\n" + "\n\n".join(lines), buttons=buttons)]


# ---------------------------------------------------------------- piloto automático


def autopilot_state(db: Session) -> dict:
    state = {"on": False, "hour": 9, "queue": [], "last_day": ""}
    state.update(_json_setting(db, "autopilot", {}))
    return state


def save_autopilot(db: Session, state: dict) -> None:
    _save_json(db, "autopilot", state)


def _queue_text(state: dict) -> str:
    if not state["queue"]:
        return "🛫 La cola está vacía. Escribe por ejemplo: «cola: Nokia, Kodak, Blockbuster»."
    items = "\n".join(f"{n}. {escape(t)}" for n, t in enumerate(state["queue"], 1))
    power = "🟢 encendido" if state["on"] else "⚪ apagado"
    return (
        f"🛫 <b>Piloto automático</b> ({power}, un vídeo al día desde las "
        f"{state['hour']}:00)\n\n{items}"
    )


def _autopilot_buttons(state: dict) -> Buttons:
    toggle = ("⚪ Apagar", "pilot:off") if state["on"] else ("🟢 Encender", "pilot:on")
    rows = [[toggle]]
    if state["queue"]:
        rows.append([("▶️ Empezar el siguiente ya", "pilot:now"), ("🗑️ Vaciar", "pilot:clear")])
    return rows


def _queue_add(db: Session, topics: list[str]) -> list[Reply]:
    state = autopilot_state(db)
    state["queue"].extend(t[:200] for t in topics if t.strip())
    save_autopilot(db, state)
    return [Reply(_queue_text(state), buttons=_autopilot_buttons(state))]


def autopilot_tick(db: Session, now: datetime | None = None) -> list[Reply]:
    """Una vez al día, a partir de la hora elegida, empieza el siguiente tema de la cola
    (si no hay nada más en marcha). En automático: elige él el enfoque."""
    now = now or datetime.now()
    state = autopilot_state(db)
    today = now.strftime("%Y-%m-%d")
    if not state["on"] or not state["queue"] or state["last_day"] == today:
        return []
    if now.hour < state["hour"] or _active_projects(db):
        return []
    return _start_next_in_queue(db, state, today)


def _start_next_in_queue(db: Session, state: dict, today: str) -> list[Reply]:
    topic = state["queue"].pop(0)
    state["last_day"] = today
    save_autopilot(db, state)
    try:
        project = start_video(db, topic, mode="automatico")
    except ProviderError as exc:
        return [Reply(f"⚠️ Piloto automático: {escape(str(exc))}")]
    left = len(state["queue"])
    return [
        Reply(
            f"🛫 <b>Piloto automático:</b> empiezo «{escape(project.title)}». Elegiré yo el "
            f"mejor enfoque y te aviso cuando el vídeo esté listo para revisar. "
            f"Quedan {left} en la cola."
        )
    ]


# ---------------------------------------------------------------- mensajes y botones


def handle(db: Session, msg: Incoming, transcribe=None, trusted: bool = False) -> list[Reply]:
    """Punto de entrada: un mensaje o un botón de un chat. `trusted`: viene de la web
    (ya has iniciado sesión), no hace falta vincular."""
    if not trusted and msg.chat_id not in {c["id"] for c in linked_chats(db)}:
        return _try_link(db, msg)
    try:
        if msg.button:
            return _button(db, msg.button)
        if msg.audio is not None:
            if transcribe is None:
                return [Reply("No puedo escuchar audios ahora mismo. Escríbemelo, porfa.")]
            text = transcribe(db, msg.audio, msg.audio_type)
            if not text:
                return [Reply("🎧 No entendí el audio. ¿Me lo repites?")]
            return [Reply(f"🎧 Entendí: «{escape(text)}»"), *_text(db, text, msg.chat_id)]
        return _text(db, msg.text, msg.chat_id)
    except ProviderError as exc:
        log.warning("JARVIS: %s | %s", exc, exc.detail)
        return [error_reply("Algo falló", exc)]


def _text(db: Session, text: str, chat_id: int = 0) -> list[Reply]:
    text = text.strip()
    if not text:
        return help_replies()
    intent = quick_intent(text)
    if intent is None:
        try:
            intent = _ai_intent(db, text, chat_id)
        except ProviderError as exc:
            log.warning("JARVIS no pudo entender «%s»: %s | %s", text[:80], exc, exc.detail)
            return [error_reply("No pude pensar la respuesta", exc)]
    replies = _act(db, intent, text, chat_id)
    remember(chat_id, text, replies)
    return replies


def _act(db: Session, intent: Intent, text: str, chat_id: int = 0) -> list[Reply]:
    if intent.action == "new_video" and intent.topic.strip():
        return _new_video(db, _clean_topic(intent.topic), intent.duration or text)
    if intent.action == "status":
        return [Reply(status_text(db), buttons=[[("🔄 Actualizar", "status")]])]
    if intent.action == "ideas":
        return _ideas(db)
    if intent.action == "queue_add" and intent.topics:
        return _queue_add(db, intent.topics)
    if intent.action in ("queue_show", "autopilot"):
        state = autopilot_state(db)
        if intent.on is not None:
            state["on"] = intent.on
            save_autopilot(db, state)
        return [Reply(_queue_text(state), buttons=_autopilot_buttons(state))]
    if intent.action == "idea_bank":
        region = intent.topic if intent.topic in ("España", "Latinoamérica") else ""
        return bank_replies(db, region)
    if intent.action == "learn_video" and learning.find_link(intent.target):
        return learn_video_replies(db, learning.find_link(intent.target))
    if intent.action == "week_plan":
        return [week_plan_reply(db)]
    if intent.action == "publish_day":
        day = normalize(intent.when).strip()
        day = day if day in DAY_NAMES else day[:-1]  # «sábados» → «sabado»
        if day in DAY_NAMES:
            hour = int(intent.task) if intent.task.strip().isdigit() else None
            coach.set_publish_slot(db, DAY_NAMES.index(day), hour)
            return [week_plan_reply(db)]
        return [Reply("¿Qué día quieres publicar? Por ejemplo: «publico los jueves a las 18».")]
    if intent.action == "next_step":
        return next_step_replies(db)
    if intent.action == "monetize":
        return [monetization_reply(db)]
    if intent.action == "review":
        return _review(db, intent.topic)
    if intent.action in skills.SKILL_ACTIONS:
        return skills.act(db, intent)
    if intent.action.startswith("task_") or intent.action in ("briefing", "time", "sleep"):
        return _agenda_act(db, intent)
    if intent.action == "remember" and intent.task.strip():
        return [remember_fact(db, intent.task.strip())]
    if intent.action == "memory":
        return [memory_reply(db)]
    if (
        intent.action == "chat"
        and intent.reply.strip()
        and not REFUSAL.search(normalize(intent.reply))
    ):
        return [Reply(escape(intent.reply.strip()))]
    if intent.action in ("question", "chat") and text.strip():
        return answer_question(db, text, chat_id)  # cualquier pregunta: busca en Google
    return help_replies()


# ---------------------------------------------------------------- saber de todo


def error_reply(what: str, exc: ProviderError) -> Reply:
    """Un error explicado, con el detalle técnico para poder arreglarlo."""
    text = f"⚠️ {what}: {escape(str(exc))}"
    if exc.transient:
        text += " Pregúntamelo otra vez en un momento."
    if exc.detail:
        text += f"\n<i>Detalle técnico (cópialo si pides ayuda): {escape(exc.detail[:300])}</i>"
    return Reply(text)


class PlainAnswer(BaseModel):
    text: str = Field(description="La respuesta, en español")


def memory(db: Session) -> list[str]:
    return _json_setting(db, MEMORY_KEY, [])


def remember_fact(db: Session, fact: str) -> Reply:
    facts = [f for f in memory(db) if normalize(f) != normalize(fact)]
    facts.append(fact[:200])
    _save_json(db, MEMORY_KEY, facts[-MAX_MEMORY:])
    return Reply(f"🧠 Anotado para siempre: «{escape(fact)}».")


def memory_reply(db: Session) -> Reply:
    facts = memory(db)
    if not facts:
        return Reply(
            "🧠 Aún no me has pedido que recuerde nada. Dime, por ejemplo: «recuerda que "
            "trabajo de 12 a 10 de la noche»."
        )
    return Reply("🧠 <b>Lo que sé de usted</b>\n" + "\n".join(f"• {escape(f)}" for f in facts))


def answer_question(db: Session, question: str, chat_id: int = 0) -> list[Reply]:
    """Contesta cualquier pregunta buscando en Google (datos actuales y comprobables)."""
    ai = jobs.get_ai_provider(db)
    facts = "\n".join(f"- {f}" for f in memory(db)) or "(nada todavía)"
    city = (get_setting(db, "jarvis_city") or "").strip()
    where = f"Simón vive en {city} (Colombia salvo que diga otra cosa)." if city else ""
    prompt = f"""Eres JARVIS, el asistente personal de Simón (como el de Iron Man): sabes de
todo. Responde a su pregunta en español sencillo y útil: 2–6 frases, o pasos numerados si
pregunta cómo hacer algo. Busca en Google lo que necesites para dar datos actuales y
correctos; si no estás seguro, dilo. Tono: educado y preciso, con un toque de humor
británico; trátalo de «usted». {where}
Si pregunta por planes (cine, restaurantes, eventos, sitios), sé CONCRETO: busca en su
ciudad opciones reales de hoy, con nombres, horarios, precios y dónde, y recomienda una
diciendo por qué. Nada de «revise la cartelera»: búscala tú (por ejemplo «cartelera
Procinal Rionegro hoy», «Cinépolis San Nicolás Rionegro horarios», «estrenos cine Colombia
esta semana»). Nunca digas que no puedes acceder: busca. Si no aparecen los horarios de
hoy, da al menos las películas en cartelera esta semana, recomienda una y di en qué web
ver la hora exacta.

LO QUE SABES DE SIMÓN:
{facts}

{_context(db, chat_id)}

PREGUNTA: {question}"""
    try:
        result = getattr(ai, "quick_research", ai.grounded_research)(prompt)
    except ProviderError as exc:
        if exc.transient:
            raise
        # Sin búsqueda de Google (p. ej. no disponible para esta cuenta): responde con lo
        # que ya sabe Gemini y lo avisa.
        log.warning("Búsqueda de Google no disponible: %s | %s", exc, exc.detail)
        plain = getattr(ai, "quick_json", ai.generate_json)(prompt, PlainAnswer)
        result = GroundedText(text=plain.text + " (Sin buscar en Google: puede no estar al día.)")
    jobs.remember_working_model(db, ai)
    answer = re.sub(r"\s*\[\d+\]", "", result.text or "").strip()
    if not answer:
        return [Reply("No encontré una respuesta clara. ¿Me lo preguntas de otra forma?")]
    replies = [Reply(escape(answer))]
    names = []
    for source in result.sources:
        if source.title and source.title not in names:
            names.append(source.title)
    if names:
        replies[0].text += "\n<i>🔎 Buscado en: " + escape(", ".join(names[:2])) + "</i>"
    return replies


def tasks_text(db: Session) -> str:
    studio = agenda.studio_tasks(db)
    mine = [t for t in agenda.personal_tasks(db) if not t.get("done")]
    if not studio and not mine:
        return "✅ No tienes nada pendiente. Día libre… o día de hacer un vídeo nuevo. 😉"
    lines = ["📝 <b>Tareas de hoy</b>"]
    lines += [f"🎬 {escape(t['text'])}" for t in studio]
    lines += [f"{n}. {escape(t['text'])}" for n, t in enumerate(mine, 1)]
    return "\n".join(lines)


def _agenda_act(db: Session, intent: Intent) -> list[Reply]:
    now = datetime.now()
    if intent.action == "task_add" and intent.task.strip():
        task = agenda.add_task(db, intent.task.strip())
        return [Reply(f"📝 Anotado: «{escape(task['text'])}».")]
    if intent.action == "task_done" and intent.task.strip():
        task = agenda.find_task(db, intent.task)
        if task is None:
            return [Reply("No encontré esa tarea. Di «tareas» para ver la lista.")]
        agenda.complete_task(db, task["id"])
        left = len([t for t in agenda.personal_tasks(db) if not t.get("done")])
        return [Reply(f"✅ Hecho: «{escape(task['text'])}». Te quedan {left}.")]
    if intent.action == "briefing":
        return [Reply(escape(agenda.briefing_text(db, now)))]
    if intent.action == "time":
        return [Reply(f"🕒 Son las {agenda.spoken_time(now)} del {agenda.spoken_date(now)}.")]
    if intent.action == "sleep":
        return [Reply("A sus órdenes. Aplaude dos veces si me necesitas. 👋", action="sleep")]
    return [Reply(tasks_text(db))]


def _project_or_none(db: Session, raw: str) -> Project | None:
    return db.get(Project, int(raw)) if raw.isdigit() else None


def _button(db: Session, data: str) -> list[Reply]:
    kind, _, rest = data.partition(":")
    if kind == "status":
        return _act(db, Intent(action="status"), "")
    if kind == "ideas":
        return _ideas(db)
    if kind == "autopilot":
        return _act(db, Intent(action="queue_show"), "")
    if kind == "tasks":
        return [Reply(tasks_text(db))]
    if kind == "analyze":
        return skills.act(db, Intent(action="analyze"))
    if kind == "next":
        return next_step_replies(db)
    if kind == "lesson":
        on = learning.toggle_apply(db, rest)
        if on is None:
            return [Reply("Esa lección ya no existe.")]
        return [
            Reply(
                "📌 Hecho: los guiones nuevos tendrán en cuenta esa lección."
                if on
                else "Quitada: los guiones ya no la usarán."
            )
        ]
    if kind == "money":
        return [monetization_reply(db)]
    if kind == "perf":
        return skills.act(db, Intent(action="performance"))
    if kind == "radar":
        headlines = _json_setting(db, "jarvis_radar", [])
        if rest.isdigit() and int(rest) < len(headlines):
            return _new_video(db, headlines[int(rest)], "")
        return [Reply("Esa noticia ya caducó. Di «radar» para ver las nuevas.")]
    if kind == "unremind" and rest.isdigit():
        agenda.cancel_reminder(db, int(rest))
        return [Reply("❌ Cancelado.")]
    if kind == "idea":
        ideas = _json_setting(db, "telegram_ideas", [])
        if rest == "all":
            return _queue_add(db, ideas) if ideas else [Reply("Esas ideas ya caducaron.")]
        if rest.isdigit() and int(rest) < len(ideas):
            return _new_video(db, ideas[int(rest)], "")
        return [Reply("Esa idea ya caducó. Escribe «ideas» para ver nuevas.")]
    if kind == "pilot":
        return _pilot_button(db, rest)
    pid, _, arg = rest.partition(":")
    project = _project_or_none(db, pid)
    if project is None:
        return [Reply("Ese proyecto ya no existe.")]
    if kind == "pick":
        return _pick(db, project, arg)
    if kind == "thumb" and arg.isdigit():
        jobs.select_thumbnail(db, project.id, int(arg))
        return [Reply(f"✅ Miniatura {int(arg) + 1} elegida para «{escape(project.title)}».")]
    if kind == "rethumb":
        jobs.enqueue(db, project.id, "thumbnail")
        return [Reply("🎨 Preparo otras 3 miniaturas. Te las mando enseguida.")]
    if kind == "final":
        jobs.enqueue(db, project.id, "edit", {"quality": "final"})
        return [Reply(f"🎬 Monto la versión final de «{escape(project.title)}» en alta calidad.")]
    if kind == "texts":
        seo = jobs.get_result(db, project.id, "publish")
        if not seo:
            jobs.enqueue(db, project.id, "publish")
            return [Reply("📝 Preparo los textos para YouTube. Te los mando enseguida.")]
        return publish_replies(project, seo)
    if kind == "qc":
        return [Reply("🔎 " + escape(coach.review_project(db, project)))]
    if kind == "go" and arg in jobs.RUNNERS:
        jobs.enqueue(db, project.id, arg)
        return [
            Reply(
                f"🫡 En marcha: {coach.STEP_LABELS[arg].lower()} de «{escape(project.title)}». "
                "Te aviso al terminar."
            )
        ]
    if kind == "concepts":
        strategy = jobs.get_result(db, project.id, "strategy") or {}
        if strategy.get("concepts"):
            return [_concepts_reply(project, strategy)]
        return [Reply("Todavía no hay enfoques para ese proyecto.")]
    if kind == "thumbs":
        replies = thumbnail_replies(project, jobs.get_result(db, project.id, "thumbnail") or {})
        return replies or [Reply("Todavía no hay miniaturas para ese proyecto.")]
    if kind == "retry" and arg in jobs.RUNNERS:
        last = jobs.latest_jobs(db, project.id).get(arg)
        jobs.enqueue(db, project.id, arg, last.params if last else None)
        return [Reply(f"🔁 Lo intento otra vez: {STAGES[arg]} de «{escape(project.title)}».")]
    return [Reply("Ese botón ya no sirve. Escribe «ayuda».")]


def _pilot_button(db: Session, action: str) -> list[Reply]:
    state = autopilot_state(db)
    if action in ("on", "off"):
        state["on"] = action == "on"
        save_autopilot(db, state)
    elif action == "clear":
        state["queue"] = []
        save_autopilot(db, state)
    elif action == "now" and state["queue"]:
        return _start_next_in_queue(db, state, state["last_day"])
    return [Reply(_queue_text(state), buttons=_autopilot_buttons(state))]


def _pick(db: Session, project: Project, arg: str) -> list[Reply]:
    strategy = jobs.get_result(db, project.id, "strategy")
    if not strategy or not strategy.get("concepts"):
        return [Reply("Todavía no hay enfoques para ese proyecto.")]
    concepts = strategy["concepts"]
    index = random.randrange(len(concepts)) if arg == "auto" else int(arg or 0)
    if not 0 <= index < len(concepts):
        return [Reply("Ese enfoque no existe.")]
    jobs.select_concept(db, project.id, index)
    # Elegido el enfoque, el resto lo hace solo hasta el vídeo y los textos.
    project.automation_mode = "automatico"
    db.commit()
    jobs.enqueue(db, project.id, "script")
    title = concepts[index]["titles"][0]["title"] if concepts[index]["titles"] else ""
    return [
        Reply(
            f"✅ Enfoque <b>{escape(concepts[index]['angle'])}</b>"
            + (f" — «{escape(title)}»" if title else "")
            + ".\nAhora hago todo solo: guion, escenas, voz, imágenes, montaje y textos. "
            "Te aviso en cada paso. 🍳 Tú sigue con lo tuyo."
        )
    ]


# ---------------------------------------------------------------- avisos


def publish_replies(project: Project, seo: dict) -> list[Reply]:
    titles = "\n".join(f"{n}. {escape(t)}" for n, t in enumerate(seo.get("titles", []), 1))
    replies = [Reply(f"📝 <b>Textos para YouTube — {escape(project.title)}</b>\n\n{titles}")]
    for part in split_text(seo.get("description", "")):
        replies.append(Reply(f"<b>Descripción</b> (cópiala tal cual):\n\n{escape(part)}"))
    extra = []
    if seo.get("tags"):
        extra.append("<b>Etiquetas:</b>\n" + escape(", ".join(seo["tags"])))
    if seo.get("pinned_comment"):
        extra.append("<b>Comentario fijado:</b>\n" + escape(seo["pinned_comment"]))
    if extra:
        replies.append(Reply("\n\n".join(extra)))
    replies[-1].buttons = [[("🔎 ¿Se puede monetizar?", f"qc:{project.id}")]]
    return replies


def thumbnail_replies(project: Project, data: dict) -> list[Reply]:
    folder = project_dir(project.id) / "miniaturas"
    photos = [folder / v["file"] for v in data.get("variants", []) if (folder / v["file"]).exists()]
    if not photos:
        return []
    texts = "\n".join(f"{n}. «{escape(v['text'])}»" for n, v in enumerate(data["variants"], 1))
    return [
        Reply(
            f"🎨 <b>{escape(project.title)}</b>: tengo 3 miniaturas. ¿Cuál usamos?\n{texts}",
            photos=photos,
            buttons=[
                [(f"✅ {n}", f"thumb:{project.id}:{n - 1}") for n in range(1, len(photos) + 1)],
                [("🔄 Hacer otras 3", f"rethumb:{project.id}")],
            ],
        )
    ]


def shorts_replies(project: Project, data: dict) -> list[Reply]:
    shorts = data.get("shorts", [])
    if not shorts:
        return []
    folder = project_dir(project.id)
    titles = "\n".join(f"{n}. {escape(s['title'])}" for n, s in enumerate(shorts, 1))
    return [
        Reply(
            f"📱 <b>{escape(project.title)}</b>: {len(shorts)} Shorts listos. Aquí va el primero; "
            f"todos están en la pestaña Shorts del proyecto.\n{titles}",
            video=folder / shorts[0]["file"],
        ),
        *(
            [Reply("🖼️ Y sus portadas, por si las quieres usar:", photos=covers)]
            if (covers := [folder / s["cover"] for s in shorts if s.get("cover")])
            else []
        ),
    ]


def make_teaser(video: Path, out: Path, seconds: int = TEASER_SECONDS) -> Path:
    """Un trozo pequeño (≈1 min, 480p) del vídeo para verlo en el móvil."""
    run_ffmpeg(
        [
            "-y",
            "-ss",
            "0",
            "-t",
            str(seconds),
            "-i",
            str(video),
            "-vf",
            "scale='if(gt(iw,ih),-2,480)':'if(gt(iw,ih),480,-2)'",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def _concepts_reply(project: Project, strategy: dict) -> Reply:
    blocks = []
    for n, c in enumerate(strategy["concepts"], 1):
        titles = "\n".join(f"   • {escape(t['title'])}" for t in c.get("titles", [])[:3])
        blocks.append(
            f"<b>{n}. {escape(c['angle'])}</b>\n{escape(c['summary'])}\n"
            f"🪝 «{escape(c['hook'])}»\n{titles}"
        )
    buttons = [
        [(f"{n}️⃣", f"pick:{project.id}:{n - 1}") for n in range(1, len(blocks) + 1)],
        [("🎲 Elige tú", f"pick:{project.id}:auto")],
    ]
    return Reply(
        f"🧭 <b>{escape(project.title)}</b>: tengo 3 enfoques. ¿Cuál hacemos?\n\n"
        + "\n\n".join(blocks),
        buttons=buttons,
    )


def _next_up(db: Session, project: Project) -> str:
    active = [s for s, j in jobs.latest_jobs(db, project.id).items() if j.active]
    return f" Sigo con: {STAGES[active[0]].lower()}." if active else ""


def _done_replies(db: Session, job: Job, project: Project) -> list[Reply]:
    data = jobs.get_result(db, project.id, job.stage) or {}
    name = f"<b>{escape(project.title)}</b>"
    if job.stage == "strategy":
        if data.get("selected"):
            concept = data["concepts"][data["selected"]["concept"]]
            angle = escape(concept["angle"])
            return [Reply(f"🧭 {name}: elegí el enfoque «{angle}».{_next_up(db, project)}")]
        return [_concepts_reply(project, data)] if data.get("concepts") else []
    if job.stage == "edit":
        return _video_replies(db, project, data)
    if job.stage == "publish":
        return publish_replies(project, data)
    if job.stage == "thumbnail":
        return thumbnail_replies(project, data)
    if job.stage == "shorts":
        return shorts_replies(project, data)
    detail = {
        "research": lambda: (
            f"🔎 {name}: investigación lista ({len(data.get('sources', []))} fuentes)."
        ),
        "script": lambda: (
            f"✍️ {name}: guion listo ({data.get('words', '?')} palabras, "
            f"unos {data.get('minutes', '?')} min)."
        ),
        "storyboard": lambda: f"🎞️ {name}: {len(data.get('scenes', []))} escenas listas.",
        "voice": lambda: f"🎙️ {name}: voz grabada ({_minutes(data.get('seconds', 0))}).",
        "visuals": lambda: f"🖼️ {name}: imágenes listas ({len(data.get('items', {}))}).",
    }.get(job.stage)
    if detail is None:
        return []
    return [Reply(detail() + _next_up(db, project))]


def _video_replies(db: Session, project: Project, data: dict) -> list[Reply]:
    quality = data.get("last", "preview")
    render = data.get("renders", {}).get(quality)
    if not render:
        return []
    folder = project_dir(project.id)
    name = escape(project.title)
    if quality == "final":
        return [
            Reply(
                f"🏁 <b>{name}</b>: ¡versión final lista! Está en tu ordenador, en la página "
                f"Vídeo del proyecto (y en la carpeta datos/proyectos/{project.id}/video)."
            ),
            Reply(
                "🔎 Antes de subirlo:\n" + escape(summary_text(project_review(db, project))),
                buttons=[[("👉 ¿Qué hago ahora?", "next")]],
            ),
        ]
    buttons = [[("🎬 Hacer versión final", f"final:{project.id}")]]
    caption = (
        f"🎥 <b>{name}</b> — borrador listo ({_minutes(render.get('seconds', 0))}). "
        f"Aquí tienes el primer minuto. Si te gusta, pide la versión final."
    )
    try:
        teaser = make_teaser(folder / render["file"], folder / "video" / "avance_telegram.mp4")
    except (RuntimeError, OSError) as exc:
        log.warning("No se pudo preparar el avance: %s", exc)
        return [Reply(caption.replace("Aquí tienes el primer minuto. ", ""), buttons=buttons)]
    return [Reply(caption, buttons=buttons, video=teaser)]


def _failed_reply(job: Job, project: Project) -> Reply:
    reason = (job.error or "Error desconocido").split("\n\n")[0]
    return Reply(
        f"⚠️ <b>{escape(project.title)}</b>: falló {STAGES[job.stage].lower()}.\n{escape(reason)}",
        buttons=[[("🔁 Reintentar", f"retry:{project.id}:{job.stage}")]],
    )


def notifications(db: Session) -> list[Reply]:
    """Avisos de las tareas que terminaron (o fallaron) desde la última vez."""
    if not linked_chats(db):
        return []
    replies: list[Reply] = []
    pending = db.scalars(
        select(Job)
        .where(Job.status.in_(("done", "failed")), Job.notified.is_(None))
        .order_by(Job.id)
    ).all()
    for job in pending:
        job.notified = True
        db.commit()
        project = db.get(Project, job.project_id)
        if project is None:
            continue
        try:
            if job.status == "failed":
                replies.append(_failed_reply(job, project))
            else:
                replies.extend(_done_replies(db, job, project))
        except Exception:  # noqa: BLE001 — un aviso roto no debe parar los demás
            log.exception("No se pudo preparar el aviso de la tarea %s", job.id)
    return replies


def briefing(db: Session, now: datetime | None = None) -> list[Reply]:
    """Un «buenos días» al día, a la hora del piloto automático, con el resumen."""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    if not linked_chats(db) or now.hour < autopilot_state(db)["hour"]:
        return []
    if get_setting(db, "briefing_day") == today:
        return []
    set_setting(db, "briefing_day", today)
    week = sum(
        1
        for job in db.scalars(select(Job).where(Job.stage == "edit", Job.status == "done"))
        if job.finished_at and (now - job.finished_at).days < 7
    )
    step = "\n".join(x for x in (coach.today_text(db, now), coach.first_step_text(db)) if x)
    return [
        Reply(
            "☀️ <b>Buenos días.</b> Resumen del estudio:\n\n"
            f"{status_text(db)}\n\n{tasks_text(db)}\n\n"
            f"🎞️ Vídeos montados en los últimos 7 días: {week}"
            + (f"\n{escape(step)}" if step else ""),
            buttons=[
                [("👉 ¿Qué hago ahora?", "next"), ("💡 Ideas para hoy", "ideas")],
                [("💰 Monetización", "money"), ("🛫 Piloto", "autopilot")],
            ],
        )
    ]


def reminder_alerts(db: Session, now: datetime | None = None) -> list[Reply]:
    if not linked_chats(db):
        agenda.unsent_alerts(db, now)  # sin Telegram: solo los anuncia la pantalla
        return []
    return [
        Reply(
            f"⏱️ <b>¡Tiempo!</b> {escape(item['text'])} terminado."
            if item["kind"] == "timer"
            else f"🎉 <b>¡Logro!</b> {escape(item['text'])}"
            if item["kind"] == "milestone"
            else f"⏰ <b>Recordatorio:</b> {escape(item['text'])}"
        )
        for item in agenda.unsent_alerts(db, now)
    ]


def tick(db: Session, now: datetime | None = None) -> list[Reply]:
    """Lo que JARVIS hace por su cuenta cada pocos segundos."""
    return [
        *notifications(db),
        *reminder_alerts(db, now),
        *briefing(db, now),
        *autopilot_tick(db, now),
    ]
