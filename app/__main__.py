"""Arranca Faceless Studio y abre el navegador. Uso: python -m app"""

import threading
import webbrowser

import uvicorn

from app.config import HOST, PORT


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    print(f"\n  Faceless Studio está encendido en {url}")
    print("  Para apagarlo, cierra esta ventana.\n")
    threading.Timer(2.0, webbrowser.open, args=[url]).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
