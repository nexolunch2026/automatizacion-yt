"""Habilidades extra de JARVIS: recordatorios, temporizadores, noticias, tu canal,
el dólar, el clima, abrir páginas, datos curiosos y estadísticas.

`quick()` reconoce las frases habituales sin gastar IA; `act()` ejecuta la acción.
"""

import re
from datetime import datetime
from html import escape
from urllib.parse import quote_plus

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agenda, info

SKILL_ACTIONS = (
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
)

# Páginas que JARVIS sabe abrir (clave sin tildes y en minúsculas).
SITES = {
    "youtube studio": "https://studio.youtube.com",
    "studio": "https://studio.youtube.com",
    "youtube": "https://www.youtube.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "gemini": "https://gemini.google.com",
    "claude": "https://claude.ai",
    "elevenlabs": "https://elevenlabs.io/app",
    "eleven labs": "https://elevenlabs.io/app",
    "gmail": "https://mail.google.com",
    "correo": "https://mail.google.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "telegram": "https://web.telegram.org",
    "canva": "https://www.canva.com",
    "pixabay": "https://pixabay.com",
    "pexels": "https://www.pexels.com",
    "tiktok": "https://www.tiktok.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "spotify": "https://open.spotify.com",
    "google": "https://www.google.com",
    "calendario": "https://calendar.google.com",
    "google trends": "https://trends.google.com/trends/?geo=CO",
    "tendencias": "https://trends.google.com/trends/?geo=CO",
}

NEWS_WORDS = (
    "noticias",
    "noticias de hoy",
    "titulares",
    "que hay de nuevo",
    "noticias de negocios",
    "ultimas noticias",
    "que paso hoy",
)
RADAR_WORDS = (
    "radar",
    "radar de marcas",
    "marcas en crisis",
    "noticias de marcas",
    "que marcas estan en problemas",
    "empresas en crisis",
    "ideas de noticias",
)
CHANNEL_WORDS = (
    "canal",
    "mi canal",
    "el canal",
    "como va el canal",
    "como va mi canal",
    "como va youtube",
    "estadisticas del canal",
    "suscriptores",
    "cuantos suscriptores tengo",
    "cuantos suscriptores llevo",
    "visitas",
    "cuantas visitas tengo",
)
DOLLAR_WORDS = (
    "dolar",
    "el dolar",
    "dolar hoy",
    "precio del dolar",
    "a como esta el dolar",
    "como esta el dolar",
)
FORECAST_WORDS = (
    "clima",
    "el clima",
    "como esta el clima",
    "clima de manana",
    "va a llover",
    "va a llover hoy",
    "pronostico",
    "el tiempo",
    "que tiempo hace",
)
FACT_WORDS = ("dato curioso", "dame un dato curioso", "dato del dia", "curiosidad", "un dato")
STATS_WORDS = (
    "estadisticas",
    "cuantos videos llevo",
    "cuantos videos he hecho",
    "informe semanal",
    "resumen de la semana",
)
REMINDER_LIST_WORDS = ("recordatorios", "mis recordatorios", "que recordatorios tengo", "alarmas")

REMINDER = re.compile(
    r"^(?:recuerdame|recordarme|avisame|hazme acordar de|pon(?:me)? (?:una alarma|un "
    r"recordatorio)|alarma|recordatorio)\b\s*(?:que |de |:)?\s*"
)
TIMER = re.compile(
    r"(?:temporizador|cronometro|timer|alarma|cuenta regresiva)\s+(?:de|por|en|a)\s+"
    rf"(?P<n>{agenda._NUM})\s*(?P<unit>minutos?|min|horas?|segundos?|seg)\b"
)
OPEN = re.compile(r"^(?:abre(?:me)?|abrir|muestrame|ve a|entra a|entra en|llevame a)\s+(.+)")
SEARCH = re.compile(r"^(?:busca(?:me)?|buscar|googlea|busca en google)\s+(.+)")
PLAY = re.compile(
    r"^(?:pon(?:me)?|reproduce|reproducir)\s+(?:musica|una cancion|la cancion)?\s*(.+)"
)


def quick(text: str, norm: str):
    """Devuelve un Intent si la frase es de una de estas habilidades."""
    from app.assistant import Intent

    bare = norm.strip(" .!?¡¿")
    for words, action in (
        (NEWS_WORDS, "news"),
        (RADAR_WORDS, "radar"),
        (CHANNEL_WORDS, "channel"),
        (DOLLAR_WORDS, "dollar"),
        (FORECAST_WORDS, "forecast"),
        (FACT_WORDS, "fact"),
        (STATS_WORDS, "stats"),
        (REMINDER_LIST_WORDS, "reminder_list"),
    ):
        if bare in words:
            return Intent(action=action)
    match = TIMER.search(norm)
    if match:
        return Intent(action="timer", when=f"en {match.group('n')} {match.group('unit')}")
    match = REMINDER.match(norm)
    rest = text[match.end() :].strip(" .,:;") if match else ""
    if rest and agenda.parse_when(rest, datetime.now())[0] is not None:
        return Intent(action="reminder", task=rest)  # sin hora es una tarea, no un recordatorio
    match = OPEN.match(norm)
    if match:
        return Intent(action="open", target=text[match.start(1) :].strip(" .,:;"))
    match = SEARCH.match(norm)
    if match:
        return Intent(action="open", target="google:" + text[match.start(1) :].strip(" .,:;"))
    match = PLAY.match(norm)
    if match and not re.match(r"(?:una alarma|un recordatorio|un temporizador)", match.group(1)):
        return Intent(action="open", target="youtube:" + text[match.start(1) :].strip(" .,:;"))
    return None


# ---------------------------------------------------------------- acciones


def act(db: Session, intent) -> list:
    handler = {
        "reminder": _reminder,
        "timer": _timer,
        "reminder_list": _reminder_list,
        "news": _news,
        "radar": _radar,
        "channel": _channel,
        "dollar": _dollar,
        "forecast": _forecast,
        "fact": _fact,
        "open": _open,
        "stats": _stats,
    }[intent.action]
    return handler(db, intent)


def _r(text: str, **kwargs):
    from app.assistant import Reply

    return Reply(text, **kwargs)


def money(value: float) -> str:
    """4123.5 → «4.123,50»."""
    whole, _, decimals = f"{value:,.2f}".partition(".")
    return whole.replace(",", ".") + "," + decimals


def number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _reminder(db: Session, intent) -> list:
    now = datetime.now()
    when, rest = agenda.parse_when(intent.task or "", now)
    if when is None and intent.when:
        when, _ = agenda.parse_when(intent.when, now)
    if when is None:
        return [
            _r(
                "¿Para cuándo? Dímelo con la hora, por ejemplo: «recuérdame a las 5 llamar a "
                "Juan» o «recuérdame en 20 minutos sacar el pollo»."
            )
        ]
    text = re.sub(r"^(?:que|de)\s+", "", rest, flags=re.I) or "lo que me pediste"
    item = agenda.add_reminder(db, text, when)
    return [
        _r(
            f"⏰ Hecho. Le recordaré «{escape(item['text'])}» {agenda.spoken_when(when, now)}.",
            buttons=[[("❌ Cancelar", f"unremind:{item['id']}")]],
        )
    ]


def _timer(db: Session, intent) -> list:
    now = datetime.now()
    when, _ = agenda.parse_when(intent.when or intent.task, now)
    if when is None:
        return [_r("¿De cuánto tiempo? Por ejemplo: «temporizador de 10 minutos».")]
    minutes = round((when - now).total_seconds() / 60)
    length = (
        f"{minutes} minuto{'s' if minutes != 1 else ''}"
        if minutes < 120
        else (f"{minutes // 60} horas")
    )
    item = agenda.add_reminder(db, f"Temporizador de {length}", when, kind="timer")
    return [
        _r(
            f"⏱️ Temporizador de {length} en marcha. Le aviso a las {agenda.spoken_time(when)}.",
            buttons=[[("❌ Cancelar", f"unremind:{item['id']}")]],
        )
    ]


def _reminder_list(db: Session, intent) -> list:
    now = datetime.now()
    pending = [i for i in agenda.reminders(db, now) if not i["fired"]]
    if not pending:
        return [_r("⏰ No tienes recordatorios. Dime por ejemplo: «recuérdame a las 6 grabar».")]
    lines = [
        f"⏰ {agenda.spoken_when(datetime.fromisoformat(i['at']), now)}: {escape(i['text'])}"
        for i in pending
    ]
    return [_r("<b>Recordatorios</b>\n" + "\n".join(lines))]


def _headlines(items: list[dict], title: str, store: str | None, db: Session) -> list:
    if not items:
        return [_r("📰 No pude traer noticias ahora mismo (¿hay internet?). Prueba en un rato.")]
    lines = [
        f"{n}. {escape(i['title'])}" + (f" <i>({escape(i['source'])})</i>" if i["source"] else "")
        for n, i in enumerate(items[:5], 1)
    ]
    buttons = None
    if store:
        import json

        from app.settings_store import set_setting

        set_setting(db, store, json.dumps([i["title"] for i in items[:5]], ensure_ascii=False))
        buttons = [[(f"🎬 {n}", f"radar:{n - 1}") for n in range(1, min(5, len(items)) + 1)]]
    return [_r(f"{title}\n\n" + "\n".join(lines), buttons=buttons)]


def _news(db: Session, intent) -> list:
    return _headlines(info.news(db), "📰 <b>Noticias de negocios</b>", None, db)


def _radar(db: Session, intent) -> list:
    replies = _headlines(
        info.brand_radar(db),
        "📡 <b>Radar de marcas</b> (empresas en apuros esta semana)",
        "jarvis_radar",
        db,
    )
    if replies[0].buttons:
        replies[0].text += "\n\nPulsa un número y lo convierto en vídeo."
    return replies


def channel_summary(db: Session) -> str:
    data = info.youtube(db)
    if not data:
        return ""
    parts = []
    if data.get("subscribers") is not None:
        parts.append(f"{number(data['subscribers'])} suscriptores")
    if data.get("videos"):
        parts.append(f"{data['videos']} vídeos")
    if data.get("views") and data.get("exact"):
        parts.append(f"{number(data['views'])} visitas en total")
    return ", ".join(parts)


def _channel(db: Session, intent) -> list:
    data = info.youtube(db)
    if not data:
        return [
            _r(
                "📺 No pude leer tu canal. Revisa en la página JARVIS que el canal esté bien "
                "escrito (por ejemplo @AnatomiaDeUnaMarca) y que haya internet."
            )
        ]
    lines = [f"📺 <b>{escape(data.get('name') or 'Tu canal')}</b>"]
    if data.get("subscribers") is not None:
        lines.append(
            f"👥 {number(data['subscribers'])} suscriptores — {data['goal_pct']} % de los "
            f"{number(data['goal'])} para monetizar"
        )
    if data.get("videos"):
        lines.append(f"🎞️ {data['videos']} vídeos publicados")
    if data.get("views") and data.get("exact"):
        lines.append(f"👁️ {number(data['views'])} visitas en total")
    for video in data.get("latest", [])[:3]:
        lines.append(f"▶️ «{escape(video['title'])}» — {number(video['views'])} visitas")
    if not data.get("exact"):
        lines.append(
            "\n<i>Datos aproximados. Para tenerlos exactos, pon la clave gratuita de "
            "YouTube en la página JARVIS.</i>"
        )
    return [_r("\n".join(lines))]


def _dollar(db: Session, intent) -> list:
    data = info.dollar(db)
    if not data:
        return [_r("💵 No pude consultar el dólar ahora mismo (¿hay internet?).")]
    names = {"COP": "pesos colombianos", "MXN": "pesos mexicanos", "EUR": "euros"}
    name = names.get(data["currency"], data["currency"])
    return [_r(f"💵 El dólar está a {money(data['rate'])} {name}.")]


def _forecast(db: Session, intent) -> list:
    days = info.forecast(db)
    if not days:
        return [
            _r("🌦️ Dime tu ciudad en la página JARVIS (⚙ Cómo te habla JARVIS) y te doy el clima.")
        ]
    lines = [
        f"{d['day']}: {d['sky']}, entre {d['min']}° y {d['max']}°"
        + (f", lluvia {d['rain']} %" if d["rain"] >= 30 else "")
        for d in days
    ]
    return [_r("🌦️ <b>Pronóstico</b>\n" + "\n".join(lines))]


def _fact(db: Session, intent) -> list:
    fact = info.fact_of_day(db)
    if not fact:
        return [_r("🧠 Ahora no se me ocurre ninguno (Gemini no responde). Prueba en un rato.")]
    return [_r(f"🧠 <b>Dato curioso:</b> {escape(fact)}")]


def resolve_target(db: Session, target: str) -> tuple[str, str]:
    """(nombre, dirección) de lo que hay que abrir."""
    from app.assistant import normalize
    from app.models import Project

    if target.startswith("google:"):
        query = target.removeprefix("google:")
        return f"la búsqueda «{query}»", f"https://www.google.com/search?q={quote_plus(query)}"
    if target.startswith("youtube:"):
        query = target.removeprefix("youtube:")
        return f"«{query}» en YouTube", (
            f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        )
    norm = normalize(target).strip(" .")
    norm = re.sub(r"^(?:el|la|los|las|mi|un|una)\s+", "", norm)
    if norm in ("canal", "mi canal", "canal de youtube"):
        return "tu canal", info.channel_url(db)
    if norm in ("programa", "estudio", "proyectos", "faceless studio"):
        return "el estudio", "/"
    match = re.match(r"(?:proyecto|video)\s+(?:de |del |sobre )?(.+)", norm)
    if match:
        words = match.group(1).split()
        for project in db.scalars(select(Project).order_by(Project.id.desc())):
            if all(w in normalize(project.title + " " + project.topic) for w in words):
                return f"el proyecto «{project.title}»", f"/proyectos/{project.id}"
    for name in sorted(SITES, key=len, reverse=True):
        if norm == name or norm.startswith(name + " "):
            return name.title(), SITES[name]
    return f"la búsqueda «{target}»", f"https://www.google.com/search?q={quote_plus(target)}"


def _open(db: Session, intent) -> list:
    name, url = resolve_target(db, intent.target.strip())
    link = url if url.startswith("http") else f"http://127.0.0.1:8000{url}"
    return [
        _r(
            f'🖥️ Abriendo {escape(name)}: <a href="{escape(link)}">{escape(link)}</a>',
            action=f"open:{url}",
        )
    ]


def _stats(db: Session, intent) -> list:
    stats = info.studio_stats(db)
    lines = [
        "📊 <b>Estadísticas del estudio</b>",
        f"🎞️ Vídeos montados esta semana: {stats['videos_week']}",
        f"📅 En los últimos 30 días: {stats['videos_month']}",
        f"✅ Publicados en YouTube: {stats['published']} de {stats['projects']} proyectos",
    ]
    summary = channel_summary(db)
    if summary:
        lines.append(f"📺 Canal: {summary}")
    return [_r("\n".join(lines))]
