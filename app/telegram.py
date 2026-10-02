"""Conexión con Telegram: recibe tus mensajes y envía las respuestas y avisos de JARVIS.

Usa «long polling»: el programa pregunta a Telegram si hay mensajes nuevos. No hace
falta abrir puertos ni tener una web pública; basta con que el ordenador esté encendido.
"""

import json
import logging
import threading

import httpx
from sqlalchemy.orm import Session

from app import assistant, jobs
from app.assistant import Incoming, Reply
from app.db import SessionLocal
from app.providers.ai import ProviderError
from app.settings_store import get_api_key, get_setting, set_setting

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
POLL_SECONDS = 10
MAX_VIDEO_BYTES = 49 * 1024 * 1024  # los bots pueden enviar hasta 50 MB


class TelegramAPI:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self._token = token
        self._client = client or httpx.Client(timeout=POLL_SECONDS + 30)

    def _call(self, method: str, files=None, **params):
        try:
            if files:
                data = {
                    k: json.dumps(v) if isinstance(v, dict | list) else str(v)
                    for k, v in params.items()
                    if v is not None
                }
                r = self._client.post(f"{API}/bot{self._token}/{method}", data=data, files=files)
            else:
                params = {k: v for k, v in params.items() if v is not None}
                r = self._client.post(f"{API}/bot{self._token}/{method}", json=params)
        except httpx.HTTPError as exc:
            raise ProviderError(
                "No hay conexión con Telegram.", transient=True, detail=str(exc)
            ) from exc
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code == 401 or r.status_code == 404:
            raise ProviderError(
                "El token del bot de Telegram no es válido. Revísalo en la página JARVIS.",
                detail=r.text[:300],
            )
        if not body.get("ok"):
            raise ProviderError(
                "Telegram rechazó el mensaje.",
                transient=r.status_code >= 500 or r.status_code == 429,
                detail=r.text[:300],
            )
        return body["result"]

    def get_me(self) -> dict:
        return self._call("getMe")

    def get_updates(self, offset: int | None, timeout: int = POLL_SECONDS) -> list[dict]:
        return self._call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=["message", "callback_query"],
        )

    def send(self, chat_id: int, reply: Reply) -> None:
        markup = None
        if reply.buttons:
            markup = {
                "inline_keyboard": [
                    [{"text": text, "callback_data": data[:64]} for text, data in row]
                    for row in reply.buttons
                ]
            }
        if reply.video and reply.video.exists() and reply.video.stat().st_size < MAX_VIDEO_BYTES:
            with reply.video.open("rb") as f:
                self._call(
                    "sendVideo",
                    files={"video": (reply.video.name, f, "video/mp4")},
                    chat_id=chat_id,
                    caption=reply.text[:1000],
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=markup,
                )
            return
        self._call(
            "sendMessage",
            chat_id=chat_id,
            text=reply.text or "…",
            parse_mode="HTML",
            reply_markup=markup,
            link_preview_options={"is_disabled": True},
        )

    def answer_button(self, callback_id: str) -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id)

    def typing(self, chat_id: int) -> None:
        self._call("sendChatAction", chat_id=chat_id, action="typing")

    def download(self, file_id: str) -> bytes:
        info = self._call("getFile", file_id=file_id)
        try:
            r = self._client.get(f"{API}/file/bot{self._token}/{info['file_path']}")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError("No se pudo descargar el audio.", detail=str(exc)) from exc
        return r.content


def check_token(token: str) -> str:
    """Comprueba el token y devuelve el nombre de usuario del bot. Se reemplaza en tests."""
    return TelegramAPI(token).get_me()["username"]


def transcribe(db: Session, audio: bytes, mime_type: str) -> str:
    ai = jobs.get_ai_provider(db)
    if not hasattr(ai, "transcribe"):
        raise ProviderError("La IA configurada no puede escuchar audios.")
    text = ai.transcribe(audio, mime_type)
    jobs.remember_working_model(db, ai)
    return text


def parse_update(update: dict, api: TelegramAPI) -> tuple[Incoming | None, str | None]:
    """Convierte lo que llega de Telegram en un mensaje para JARVIS."""
    if "callback_query" in update:
        query = update["callback_query"]
        chat = (query.get("message") or {}).get("chat") or {}
        sender = query.get("from") or {}
        if not chat:
            return None, query.get("id")
        msg = Incoming(chat_id=chat["id"], name=sender.get("first_name", ""))
        msg.button = query.get("data") or ""
        return msg, query.get("id")
    message = update.get("message")
    if not message or "chat" not in message:
        return None, None
    msg = Incoming(
        chat_id=message["chat"]["id"],
        name=(message.get("from") or {}).get("first_name", ""),
        text=message.get("text") or message.get("caption") or "",
    )
    voice = message.get("voice") or message.get("audio")
    if voice:
        msg.audio_type = voice.get("mime_type") or "audio/ogg"
        msg.extra["file_id"] = voice["file_id"]
    return msg, None


def process_update(db: Session, api: TelegramAPI, update: dict) -> None:
    msg, callback_id = parse_update(update, api)
    if callback_id:
        try:
            api.answer_button(callback_id)
        except ProviderError:
            pass
    if msg is None:
        return
    try:
        api.typing(msg.chat_id)
    except ProviderError:
        pass
    known = msg.chat_id in {c["id"] for c in assistant.linked_chats(db)}
    if known and msg.extra.get("file_id"):
        try:
            msg.audio = api.download(msg.extra["file_id"])
        except ProviderError as exc:
            api.send(msg.chat_id, Reply(f"⚠️ {exc}"))
            return
    for reply in assistant.handle(db, msg, transcribe=transcribe):
        api.send(reply.chat_id or msg.chat_id, reply)


def broadcast(db: Session, api: TelegramAPI, replies: list[Reply]) -> None:
    chats = [c["id"] for c in assistant.linked_chats(db)]
    for reply in replies:
        for chat_id in [reply.chat_id] if reply.chat_id else chats:
            try:
                api.send(chat_id, reply)
            except ProviderError as exc:
                log.warning("No se pudo enviar un aviso a %s: %s", chat_id, exc.detail or exc)


def poll_once(db: Session, api: TelegramAPI, timeout: int = POLL_SECONDS) -> None:
    """Una vuelta del bot: mensajes nuevos y luego avisos y piloto automático."""
    raw = get_setting(db, "telegram_offset")
    offset = int(raw) if raw and raw.isdigit() else None
    for update in api.get_updates(offset, timeout):
        # Se guarda antes de procesar: si un mensaje rompe algo, no se repite sin fin.
        set_setting(db, "telegram_offset", str(update["update_id"] + 1))
        try:
            process_update(db, api, update)
        except Exception:  # noqa: BLE001 — un mensaje raro no debe tumbar el bot
            log.exception("Error atendiendo un mensaje de Telegram")
            db.rollback()
    broadcast(db, api, assistant.tick(db))


class TelegramBot(threading.Thread):
    def __init__(self):
        super().__init__(name="faceless-jarvis", daemon=True)
        self._stop_event = threading.Event()

    def run(self) -> None:
        api, token, failures = None, None, 0
        while not self._stop_event.is_set():
            with SessionLocal() as db:
                current = get_api_key(db, "telegram")
                if not current:
                    api = None
                    self._stop_event.wait(5)
                    continue
                if current != token:
                    api, token = TelegramAPI(current), current
                try:
                    poll_once(db, api)
                    failures = 0
                except ProviderError as exc:
                    failures += 1
                    log.warning("Telegram: %s %s", exc, exc.detail)
                    self._stop_event.wait(min(60, 5 * failures))
                except Exception:  # noqa: BLE001 — el bot nunca debe morir
                    failures += 1
                    log.exception("Error en el bot de Telegram")
                    self._stop_event.wait(min(60, 5 * failures))

    def stop(self) -> None:
        self._stop_event.set()
