"""Página JARVIS: hablar con el asistente desde el navegador, conectar Telegram y
manejar el piloto automático."""

import re
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import assistant, telegram
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
    replies = assistant.handle(db, msg, trusted=True)
    return {
        "replies": [
            {
                "html": r.text,
                "buttons": [[{"text": t, "data": d} for t, d in row] for row in r.buttons or []],
                "video": _video_url(r.video) if r.video else None,
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
