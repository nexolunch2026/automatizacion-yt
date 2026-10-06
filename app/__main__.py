"""Arranca Faceless Studio y abre el navegador.

Uso: python -m app            (el programa)
     python -m app --jarvis   (la pantalla de JARVIS, a pantalla completa)
"""

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.config import DATA_DIR, HOST, PORT, VERSION
from app.running import port_in_use

# Perfil propio del navegador de JARVIS: recuerda el permiso del micrófono y la sesión.
JARVIS_PROFILE = DATA_DIR.parent / "navegador_jarvis"
# Código de salida cuando ya estaba encendido: Iniciar.bat cierra su ventana sin esperar.
ALREADY_RUNNING = 3


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
        sys.exit(ALREADY_RUNNING)
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


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    jarvis = "--jarvis" in sys.argv
    if jarvis and port_in_use(HOST, PORT):  # el programa ya está abierto: solo la pantalla
        open_jarvis(f"{url}/jarvis/hud")
        sys.exit(ALREADY_RUNNING)
    if port_in_use(HOST, PORT):  # ya encendido (p. ej. por JARVIS al encender): se abre
        print("\n  Faceless Studio ya estaba encendido. Lo abro en tu navegador.")
        print("  (Para actualizar no hace falta cerrarlo: Actualizar lo apaga solo.)\n")
        webbrowser.open(url)
        sys.exit(ALREADY_RUNNING)

    print(f"\n  Faceless Studio version {VERSION} esta encendido en {url}")
    print(f"  Tus proyectos y videos estan en: {DATA_DIR}")
    if "onedrive" in str(DATA_DIR).lower():
        print("  AVISO: tus datos estan dentro de OneDrive; puede llenarse con los videos.")
    print("  Para apagarlo, cierra esta ventana.\n")
    if jarvis:
        threading.Timer(2.0, open_jarvis, args=[f"{url}/jarvis/hud"]).start()
    else:
        threading.Timer(2.0, webbrowser.open, args=[url]).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
