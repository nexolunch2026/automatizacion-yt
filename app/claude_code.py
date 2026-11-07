"""CLAUDE COMO ASISTENTE (sustituye al «cerebro» de Gemini de JARVIS desde la v0.76).

Usa Claude Code instalado en el PC (`claude -p`), con la suscripción de Claude de Simón: no
hace falta clave de API de pago. Trabaja en la carpeta FacelessStudio, donde están los agentes
(`.claude/agents/`) y sus reglas (`agentes/REGLAS_COMUNES.md`).

Seguridad (lo pueden usar Simón y Esteban desde la web o Telegram):
- Solo puede LEER: archivos (salvo la carpeta `datos`, con la base de datos y las claves),
  buscar en internet y ejecutar los dos scripts de solo lectura de `agentes/`.
- No puede escribir, borrar, ni ejecutar otros comandos: lo que no está permitido se rechaza
  solo (en `-p` no hay nadie para aprobarlo).
- El texto del usuario va por la entrada estándar, nunca en la línea de órdenes.
"""

import json
import logging
import re
import shutil
import subprocess
from html import escape
from pathlib import Path

from app.providers.ai import ProviderError

log = logging.getLogger(__name__)

TIMEOUT = 240  # segundos: buscar en internet o lanzar un agente puede tardar
SESSION_KEY = "claude_session:{chat_id}"  # la conversación sigue donde se quedó
NEW_CHAT = {"nueva conversacion", "nueva conversación", "olvida", "empezar de nuevo", "/nueva"}

PYTHON = "programa/.venv/Scripts/python.exe"
ALLOWED = [
    "Read(./**)",  # solo dentro de FacelessStudio (fuera se rechaza)
    "Grep",
    "Glob",
    "WebSearch",
    "WebFetch",
    "Task",
    f"Bash({PYTHON} agentes/estado_canales.py:*)",
    f"Bash({PYTHON} agentes/que_hay_nuevo.py)",
]
DENIED = [
    "Edit",
    "Write",
    "NotebookEdit",
    "Read(./datos/**)",
    "Read(**/*.key)",
    "Read(**/.env)",
    "Bash(*--marcar*)",
    "Bash(*--empezar*)",
]

INSTRUCTIONS = f"""Eres el asistente de Faceless Studio dentro del programa (antes JARVIS).
Te escriben Simón o Esteban desde la web del programa o desde Telegram, a menudo desde el móvil.
Lee y cumple siempre agentes/REGLAS_COMUNES.md (en esta carpeta) antes de responder algo que
dependa del estado de los vídeos. Lo más reciente de todo está en TRASPASO.md.

- Estado de proyectos y vídeos: `{PYTHON} agentes/estado_canales.py` (`--videos`, `--guion N`).
- Trabajo nuevo pendiente de revisar: `{PYTHON} agentes/que_hay_nuevo.py`.
- Para revisiones usa los agentes de .claude/agents: verificador, editor-guion, revisor-final,
  coordinador, analista.
- Aquí SOLO puedes leer y revisar. Si piden publicar, programar, borrar, cambiar archivos o el
  guion, explica qué botón del programa deben pulsar (o que lo pidan en Claude en el PC).
- Responde corto, en español sencillo, para leer en el móvil: máximo 12 líneas salvo que pidan
  un informe. Listas numeradas. Sin tablas (Telegram no las muestra)."""


class ClaudeUnavailable(ProviderError):
    pass


def find_claude() -> str | None:
    """La orden `claude` (en Windows, el .cmd que instala npm)."""
    return shutil.which("claude.cmd") or shutil.which("claude")


def workdir() -> Path:
    from app.storage import home_dir

    return home_dir()


def ask(question: str, session_id: str | None = None, runner=subprocess.run) -> tuple[str, str]:
    """Pregunta a Claude. Devuelve (respuesta, id de la conversación para seguirla)."""
    exe = find_claude()
    if not exe:
        raise ClaudeUnavailable(
            "Claude no está instalado en este PC.",
            detail="Instala Claude Code y entra con tu cuenta (en una terminal: claude).",
        )
    args = [exe, "-p", "--output-format", "json", "--append-system-prompt", INSTRUCTIONS]
    args += ["--allowedTools", *ALLOWED, "--disallowedTools", *DENIED]
    if session_id:
        args += ["--resume", session_id]
    try:
        done = runner(
            args,
            input=question,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            cwd=workdir(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(
            "Claude tardó demasiado.", detail=f"Más de {TIMEOUT} s", transient=True
        ) from exc
    except OSError as exc:
        raise ClaudeUnavailable("No se pudo abrir Claude.", detail=str(exc)) from exc
    return parse(done.stdout, done.stderr)


def parse(stdout: str, stderr: str = "") -> tuple[str, str]:
    """La respuesta de `claude -p --output-format json`."""
    try:
        data = json.loads(stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise ProviderError("Claude no respondió bien.", detail=(stderr or stdout)[-300:]) from exc
    result = str(data.get("result") or "")
    if data.get("is_error"):
        if "authenticate" in result.lower() or "login" in result.lower():
            raise ClaudeUnavailable(
                "Claude no tiene la sesión iniciada en este PC.",
                detail="En el PC: abre una terminal, escribe  claude  y luego  /login . "
                f"({result[:150]})",
            )
        raise ProviderError("Claude tuvo un problema.", detail=result[:300], transient=True)
    return result.strip(), str(data.get("session_id") or "")


def to_html(markdown: str) -> str:
    """Texto de Claude (markdown sencillo) → el HTML que entienden el chat y Telegram."""
    text = escape(markdown)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    return re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.M)
