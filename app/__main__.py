"""Arranca Faceless Studio y abre el navegador.

Uso: python -m app            (el programa)
     python -m app --jarvis   (la pantalla de JARVIS, a pantalla completa)
"""

import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.config import HOST, PORT, ROOT, VERSION

# Perfil propio del navegador de JARVIS: recuerda el permiso del micrófono y la sesión.
JARVIS_PROFILE = ROOT / "navegador_jarvis"


def find_browser() -> str | None:
    """Edge (viene con Windows y tiene las mejores voces) o Chrome."""
    candidates = []
    for base in (
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if base:
            candidates.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
            candidates.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    for path in candidates:
        if path.exists():
            return str(path)
    for name in ("msedge", "google-chrome", "chromium", "chrome"):
        if found := shutil.which(name):
            return found
    return None


def open_jarvis(url: str) -> None:
    """Abre JARVIS a pantalla completa, sin barras, con permiso para hablar solo."""
    browser = find_browser()
    if browser is None:
        webbrowser.open(url)
        return
    subprocess.Popen(
        [
            browser,
            f"--app={url}",
            "--start-fullscreen",
            "--autoplay-policy=no-user-gesture-required",
            f"--user-data-dir={JARVIS_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    )


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    jarvis = "--jarvis" in sys.argv
    if jarvis and port_in_use(HOST, PORT):  # el programa ya está abierto: solo la pantalla
        open_jarvis(f"{url}/jarvis/hud")
        return
    if port_in_use(HOST, PORT):
        print("\n  ATENCION: ya hay otro Faceless Studio abierto.")
        print("  Busca la otra ventana negra, cierrala y vuelve a hacer doble clic en Iniciar.")
        print("  (Si no la encuentras, reinicia el ordenador.)\n")
        sys.exit(1)

    print(f"\n  Faceless Studio version {VERSION} esta encendido en {url}")
    print("  Para apagarlo, cierra esta ventana.\n")
    if jarvis:
        threading.Timer(2.0, open_jarvis, args=[f"{url}/jarvis/hud"]).start()
    else:
        threading.Timer(2.0, webbrowser.open, args=[url]).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
