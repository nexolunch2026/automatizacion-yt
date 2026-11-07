import json
import subprocess
from types import SimpleNamespace

import pytest

from app import assistant, claude_code
from app.assistant import Incoming
from app.db import SessionLocal
from app.providers.ai import ProviderError
from app.settings_store import get_setting


def output(result="Hola", session="s-1", is_error=False):
    return json.dumps({"result": result, "session_id": session, "is_error": is_error})


class FakeRun:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(stdout=self.answers.pop(0), stderr="")


@pytest.fixture
def with_claude(monkeypatch):
    monkeypatch.setattr(claude_code, "find_claude", lambda: "claude.cmd")


def test_question_goes_by_stdin_with_read_only_tools(with_claude):
    run = FakeRun(output("Todo bien", "abc"))
    answer, session = claude_code.ask('zzborrazz" & del C:\\ ', "old", runner=run)
    assert (answer, session) == ("Todo bien", "abc")
    args, kwargs = run.calls[0]
    assert kwargs["input"].startswith("zzborrazz")
    assert not any("zzborrazz" in a for a in args)  # el texto nunca va en la línea de órdenes
    assert args[args.index("--resume") + 1] == "old"
    denied = args[args.index("--disallowedTools") + 1 :]
    assert {"Edit", "Write", "Read(./datos/**)"} <= set(denied)
    allowed = args[args.index("--allowedTools") + 1 : args.index("--disallowedTools")]
    assert "Bash" not in allowed  # Bash solo con los scripts de solo lectura
    assert all(not a.startswith("Bash(") or "agentes/" in a for a in allowed)


def test_errors_are_explained():
    with pytest.raises(claude_code.ClaudeUnavailable) as exc:
        claude_code.parse(output("Failed to authenticate: OAuth expired", "", True))
    assert "/login" in exc.value.detail
    with pytest.raises(ProviderError):
        claude_code.parse("no es json", "algo raro")
    with pytest.raises(ProviderError):
        claude_code.parse(output("Overloaded", "", True))


def test_timeout_and_missing_claude(monkeypatch):
    monkeypatch.setattr(claude_code, "find_claude", lambda: None)
    with pytest.raises(claude_code.ClaudeUnavailable):
        claude_code.ask("hola")
    monkeypatch.setattr(claude_code, "find_claude", lambda: "claude.cmd")

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("claude", 1)

    with pytest.raises(ProviderError) as exc:
        claude_code.ask("hola", runner=slow)
    assert exc.value.transient


def test_markdown_becomes_safe_html():
    html = claude_code.to_html("## Hoy\n**Bale** listo <script> y `SUBIR_BALE`")
    assert "<b>Hoy</b>" in html and "<b>Bale</b>" in html
    assert "&lt;script&gt;" in html and "<code>SUBIR_BALE</code>" in html


def test_assistant_uses_claude_and_keeps_the_conversation(client, with_claude, monkeypatch):
    seen = []

    def fake_ask(text, session):
        seen.append((text, session))
        return f"Respuesta a {text}", "sesion-7"

    monkeypatch.setattr(claude_code, "ask", fake_ask)
    with SessionLocal() as db:
        first_q, second_q = "Opina sobre la miniatura de Bale, por favor", "¿y la versión de Kodak?"
        first = assistant.handle(db, Incoming(chat_id=-1, text=first_q), trusted=True)
        assistant.handle(db, Incoming(chat_id=-1, text=second_q), trusted=True)
        assert f"Respuesta a {first_q}" in first[0].text
        assert seen == [(first_q, None), (second_q, "sesion-7")]
        reset = assistant.handle(db, Incoming(chat_id=-1, text="Nueva conversación"), trusted=True)
        assert "conversación nueva" in reset[0].text
        assert not get_setting(db, "claude_session:-1")


def test_stale_conversation_is_retried_fresh(client, with_claude, monkeypatch):
    from app.settings_store import set_setting

    seen = []

    def fake_ask(text, session):
        seen.append(session)
        if session:
            raise ProviderError("No conversation found")
        return "Hola de nuevo", "nueva"

    monkeypatch.setattr(claude_code, "ask", fake_ask)
    with SessionLocal() as db:
        set_setting(db, "claude_session:5", "vieja")
        replies = assistant._claude(db, "hola", 5)
        assert seen == ["vieja", None] and "Hola de nuevo" in replies[0].text
        assert get_setting(db, "claude_session:5") == "nueva"


def test_claude_not_logged_in_falls_back_to_gemini(client, with_claude, monkeypatch):
    def fail(text, session):
        raise claude_code.ClaudeUnavailable("Claude no tiene la sesión iniciada.", detail="/login")

    monkeypatch.setattr(claude_code, "ask", fail)
    monkeypatch.setattr(
        assistant, "_ai_intent", lambda db, text, chat_id=0: assistant.Intent(action="status")
    )
    with SessionLocal() as db:
        replies = assistant._text(db, "Opina sobre la miniatura de Bale", -1)
    assert "sesión iniciada" in replies[0].text and "/login" in replies[0].text
    assert "Gemini" in replies[0].text and len(replies) == 2  # y aun así contesta


def test_jarvis_page_is_now_claude(logged_in):
    page = logged_in.get("/jarvis").text
    assert "Claude" in page and "no está instalado" in page  # en los tests no hay Claude
