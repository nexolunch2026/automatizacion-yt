"""Página JARVIS: hablar con el asistente desde el navegador, conectar Telegram y
manejar el piloto automático."""

import logging
import re
import time
from html import escape
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import agenda, assistant, telegram
from app.assistant import Incoming
from app.auth import DB, CurrentUser
from app.media import PROJECTS_DIR
from app.providers.ai import ProviderError
from app.settings_store import (
    api_key_hint,
    delete_api_key,
    get_api_key,
    get_setting,
    save_api_key,
    set_setting,
)
from app.templating import render

log = logging.getLogger(__name__)

router = APIRouter(prefix="/jarvis")

WEB_CHAT = -1  # «chat» de la web (no es de Telegram)
TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{20,80}$")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _page(request: Request, db: DB, status_code: int = 200, **ctx):
    return render(
        request,
        "jarvis.html",
        status_code=status_code,
        telegram_hint=api_key_hint(db, "telegram"),
        bot_name=get_setting(db, "telegram_bot") or "",
        chats=assistant.linked_chats(db),
        code=assistant.link_code(db),
        pilot=assistant.autopilot_state(db),
        status=assistant.status_text(db),
        city=get_setting(db, "jarvis_city") or "",
        call_me=get_setting(db, "jarvis_name") or "",
        youtube_channel=get_setting(db, "youtube_channel") or "",
        youtube_hint=api_key_hint(db, "youtube"),
        currency=get_setting(db, "jarvis_currency") or "COP",
        **ctx,
    )


@router.get("")
def jarvis_page(request: Request, db: DB, user: CurrentUser):
    return _page(request, db, saved=request.query_params.get("guardado"))


def _video_url(path) -> str | None:
    try:
        relative = path.resolve().relative_to(PROJECTS_DIR.resolve())
    except ValueError:
        return None
    project_id, *rest = relative.parts
    return f"/proyectos/{project_id}/archivos/{'/'.join(rest)}"


@router.post("/orden")
def order(
    db: DB,
    user: CurrentUser,
    text: Annotated[str, Form()] = "",
    button: Annotated[str, Form()] = "",
) -> dict:
    """Una orden escrita o dicha en la web. Devuelve las respuestas para el chat."""
    msg = Incoming(chat_id=WEB_CHAT, name=user.username, text=text[:2000], button=button[:64])
    started = time.perf_counter()
    try:
        replies = assistant.handle(db, msg, trusted=True)
    except Exception as exc:  # noqa: BLE001 — mejor explicar el fallo que «no conecta»
        log.exception("JARVIS falló con «%s»", (text or button)[:80])
        replies = [
            assistant.Reply(
                "⚠️ Algo falló dentro de JARVIS. Mándale a Claude este detalle técnico:\n"
                f"<i>{escape(type(exc).__name__)}: {escape(str(exc)[:300])}</i>"
            )
        ]
    seconds = round(time.perf_counter() - started, 1)
    log.info("JARVIS respondió en %.1f s: %s", seconds, (text or button)[:60])
    return {
        "seconds": seconds,
        "replies": [
            {
                "html": r.text,
                "buttons": [[{"text": t, "data": d} for t, d in row] for row in r.buttons or []],
                "video": _video_url(r.video) if r.video else None,
                "photos": [_video_url(p) for p in r.photos],
                "action": r.action,
            }
            for r in replies
        ],
        "status": assistant.status_text(db),
    }


@router.get("/estado")
def status(db: DB, user: CurrentUser) -> dict:
    return {"status": assistant.status_text(db)}


@router.post("/telegram")
def save_telegram(request: Request, db: DB, user: CurrentUser, token: Annotated[str, Form()]):
    token = token.strip()
    if not TOKEN.match(token):
        return _page(
            request,
            db,
            400,
            telegram_error="Eso no parece un token de bot. Es como 1234567890:AAH… "
            "(números, dos puntos y letras). Cópialo completo de BotFather.",
        )
    try:
        name = telegram.check_token(token)
    except ProviderError as exc:
        return _page(request, db, 400, telegram_error=str(exc))
    save_api_key(db, "telegram", token)
    set_setting(db, "telegram_bot", name)
    set_setting(db, "telegram_offset", "")
    return _redirect("/jarvis?guardado=1#telegram")


@router.post("/telegram/borrar")
def delete_telegram(db: DB, user: CurrentUser):
    delete_api_key(db, "telegram")
    set_setting(db, "telegram_bot", "")
    return _redirect("/jarvis#telegram")


@router.post("/telegram/desvincular")
def unlink(db: DB, user: CurrentUser, chat_id: Annotated[int, Form()]):
    assistant.unlink_chat(db, chat_id)
    return _redirect("/jarvis#telegram")


@router.post("/telegram/prueba")
def test_message(request: Request, db: DB, user: CurrentUser):
    token = get_api_key(db, "telegram")
    if not token or not assistant.linked_chats(db):
        return _page(request, db, 400, telegram_error="Primero conecta el bot y vincula tu chat.")
    try:
        api = telegram.TelegramAPI(token)
        for chat in assistant.linked_chats(db):
            api.send(chat["id"], assistant.Reply("🤖 Prueba de JARVIS: todo funciona. 👌"))
    except ProviderError as exc:
        return _page(request, db, 400, telegram_error=f"{exc} {exc.detail}")
    return _page(request, db, test_ok=True)


@router.post("/piloto")
def save_pilot(
    db: DB,
    user: CurrentUser,
    queue: Annotated[str, Form()] = "",
    hour: Annotated[int, Form()] = 9,
    on: Annotated[str | None, Form()] = None,
):
    state = assistant.autopilot_state(db)
    state["queue"] = [line.strip()[:200] for line in queue.splitlines() if line.strip()]
    state["hour"] = min(max(hour, 0), 23)
    state["on"] = on == "1"
    assistant.save_autopilot(db, state)
    return _redirect("/jarvis?guardado=piloto#piloto")


# ---------------------------------------------------------------- pantalla completa (HUD)


@router.get("/hud")
def hud(request: Request, db: DB, user: CurrentUser):
    from app import profile

    return render(
        request,
        "jarvis_hud.html",
        call_me=get_setting(db, "jarvis_name") or "",
        channel_name=profile.get(db)["channel"],
    )


@router.get("/hud/datos")
def hud_data(db: DB, user: CurrentUser) -> dict:
    """Todo lo que muestra la pantalla; se pide cada pocos segundos."""
    pilot = assistant.autopilot_state(db)
    return {
        "production": agenda.production(db),
        "studio_tasks": agenda.studio_tasks(db),
        "tasks": agenda.personal_tasks(db),
        "pilot": {"on": pilot["on"], "hour": pilot["hour"], "queue": pilot["queue"][:6]},
        "system": agenda.system(),
        "reminders": [r for r in agenda.reminders(db) if not r["fired"]],
        "alerts": agenda.fire_due(db),  # la pantalla anuncia los que aún no anunció
        "telegram": bool(api_key_hint(db, "telegram")) and bool(assistant.linked_chats(db)),
    }


@router.get("/hud/mundo")
def hud_world(db: DB, user: CurrentUser) -> dict:
    """Lo que viene de internet (canal, noticias, dólar, clima…); se pide cada 2 minutos."""
    from app import info

    return {
        "weather": agenda.weather(db),
        "forecast": info.forecast(db),
        "youtube": info.youtube(db),
        "news": info.news(db)[:8],
        "radar": info.brand_radar(db)[:6],
        "dollar": info.dollar(db),
        "fact": info.fact_for_screen(db),
        "stats": info.studio_stats(db),
        "plan": hud_plan(db),
        "references": hud_references(db),
    }


def hud_references(db) -> list[dict]:
    """Los vídeos que destacan en los canales de referencia, para la cinta de la pantalla."""
    from app import references

    try:
        top = references.top_outliers(references.overview(db), limit=4)
    except Exception:  # noqa: BLE001 — la pantalla nunca debe romperse por esto
        log.exception("No se pudieron leer los canales de referencia")
        return []
    return [
        {
            "title": f"🔥 {v['title']} (×{v['ratio']})",
            "url": v.get("url", ""),
            "source": v["channel"],
        }
        for v in top
    ]


def hud_plan(db) -> dict | None:
    """Plan de la semana y camino a la monetización, en corto para la pantalla."""
    from app import coach

    try:
        week = coach.weekly_plan(db)
        money = coach.monetization_path(db)
    except Exception:  # noqa: BLE001 — la pantalla nunca debe romperse por esto
        log.exception("No se pudo preparar el plan para la pantalla")
        return None
    return {
        "long": week["long"],
        "shorts": [{"day": day, "title": title} for day, title in week["shorts"][:3]],
        "today_publish": week["today_publish"],
        "today_short": week["today_short"],
        "subs": money["subs"],
        "subs_pct": money["subs_pct"],
        "hours": money["hours"]["hours"],
        "hours_pct": money["hours"]["pct"],
        "eta": money["eta"].strftime("%d/%m/%Y") if money["eta"] else None,
        "done": money["done"],
        "tip": money["tips"][0] if money["tips"] else "",
    }


@router.post("/recordatorios/{reminder_id}/borrar")
def remove_reminder(db: DB, user: CurrentUser, reminder_id: int) -> dict:
    agenda.cancel_reminder(db, reminder_id)
    return {"reminders": [r for r in agenda.reminders(db) if not r["fired"]]}


@router.get("/hud/saludo")
def hud_greeting(db: DB, user: CurrentUser) -> dict:
    name = get_setting(db, "jarvis_name") or ""
    return {"text": agenda.briefing_text(db, name=name)}


@router.post("/tareas")
def add_task(db: DB, user: CurrentUser, text: Annotated[str, Form()]) -> dict:
    if text.strip():
        agenda.add_task(db, text.strip())
    return {"tasks": agenda.personal_tasks(db)}


@router.post("/tareas/{task_id}/hecha")
def done_task(db: DB, user: CurrentUser, task_id: int) -> dict:
    agenda.complete_task(db, task_id)
    return {"tasks": agenda.personal_tasks(db)}


@router.post("/tareas/{task_id}/borrar")
def remove_task(db: DB, user: CurrentUser, task_id: int) -> dict:
    agenda.delete_task(db, task_id)
    return {"tasks": agenda.personal_tasks(db)}


@router.post("/preferencias")
def save_preferences(
    db: DB,
    user: CurrentUser,
    city: Annotated[str, Form()] = "",
    call_me: Annotated[str, Form()] = "",
    youtube_channel: Annotated[str, Form()] = "",
    youtube_key: Annotated[str, Form()] = "",
    currency: Annotated[str, Form()] = "COP",
):
    from app import info

    set_setting(db, "jarvis_city", city.strip()[:80])
    set_setting(db, "jarvis_name", call_me.strip()[:40])
    set_setting(db, "youtube_channel", youtube_channel.strip()[:120])
    if re.fullmatch(r"[A-Z]{3}", currency.strip().upper()):
        set_setting(db, "jarvis_currency", currency.strip().upper())
    if youtube_key.strip():
        save_api_key(db, "youtube", youtube_key.strip())
    info._cache.clear()  # que se vean ya los datos nuevos
    return _redirect("/jarvis?guardado=preferencias#preferencias")


@router.post("/youtube/borrar")
def delete_youtube_key(db: DB, user: CurrentUser):
    from app import info

    delete_api_key(db, "youtube")
    info._cache.clear()
    return _redirect("/jarvis#preferencias")


# ---------------------------------------------------------------- voz de JARVIS


@router.post("/voz")
def jarvis_speech(db: DB, user: CurrentUser, text: Annotated[str, Form()]):
    """MP3 con la frase dicha por JARVIS. Si falla, la pantalla usa la voz del navegador."""
    from fastapi.responses import FileResponse, JSONResponse

    from app import jarvis_voice

    try:
        path = jarvis_voice.voice_for(db, text)
    except ProviderError as exc:
        return JSONResponse({"error": str(exc), "detail": exc.detail}, status_code=503)
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/voz/opciones")
def voice_options(db: DB, user: CurrentUser) -> dict:
    from app import jarvis_voice, jobs

    eleven, eleven_error = jobs.eleven_voices(db)
    return {
        "prefs": jarvis_voice.preferences(db),
        "microsoft": [{"id": k, "label": v} for k, v in jarvis_voice.MICROSOFT_VOICES.items()],
        "eleven": eleven,
        "eleven_error": eleven_error,
    }


@router.post("/voz/preferencias")
def save_voice(
    db: DB,
    user: CurrentUser,
    engine: Annotated[str, Form()] = "microsoft",
    voice: Annotated[str, Form()] = "",
    effect: Annotated[str, Form()] = "jarvis",
    telegram_voice: Annotated[str, Form()] = "1",
) -> dict:
    from app import jarvis_voice

    prefs = jarvis_voice.preferences(db)
    if engine in ("microsoft", "eleven", "browser"):
        prefs["engine"] = engine
    if engine == "microsoft":
        prefs["voice"] = (
            voice if voice in jarvis_voice.MICROSOFT_VOICES else jarvis_voice.DEFAULT_VOICE
        )
    elif engine == "eleven" and voice.startswith("eleven:"):
        prefs["voice"] = voice
    prefs["effect"] = effect if effect in jarvis_voice.EFFECTS else "jarvis"
    prefs["telegram"] = telegram_voice == "1"
    jarvis_voice.save_preferences(db, prefs)
    return prefs
