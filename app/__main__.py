"""Arranca Faceless Studio y abre el navegador. Uso: python -m app"""

import socket
import sys
import threading
import webbrowser

import uvicorn

from app.config import HOST, PORT, VERSION


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    if port_in_use(HOST, PORT):
        print("\n  ATENCION: ya hay otro Faceless Studio abierto.")
        print("  Busca la otra ventana negra, cierrala y vuelve a hacer doble clic en Iniciar.")
        print("  (Si no la encuentras, reinicia el ordenador.)\n")
        sys.exit(1)

    print(f"\n  Faceless Studio version {VERSION} esta encendido en {url}")
    print("  Para apagarlo, cierra esta ventana.\n")
    threading.Timer(2.0, webbrowser.open, args=[url]).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
