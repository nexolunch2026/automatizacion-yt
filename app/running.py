"""EL PROGRAMA YA ENCENDIDO: encontrarlo y apagarlo para poder actualizar.

«JARVIS al encender» deja Faceless Studio encendido en una ventana minimizada cada vez que
se prende el ordenador. Entonces Actualizar no podía hacer nada («el programa está
abierto») y la persona no encontraba qué ventana cerrar. Ahora Actualizar lo apaga solo:
busca qué proceso escucha en el puerto del programa y, si es Python (el nuestro), lo
cierra. Los trabajos a medias se retoman al volver a encenderlo.
"""

import socket
import subprocess
import sys
import time


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _run(args: list[str]) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout or ""


def listener_pid(netstat_output: str, port: int) -> int | None:
    """El proceso que escucha en el puerto, leído de `netstat -ano` de Windows."""
    for line in netstat_output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] == str(port) and parts[4].isdigit():
            return int(parts[4])
    return None


def is_python(tasklist_output: str) -> bool:
    """Si `tasklist /FO CSV` dice que el proceso es Python (y no otro programa)."""
    name = tasklist_output.strip().split(",", 1)[0].strip('"').lower()
    return name.startswith("python")


def stop(host: str, port: int, wait: float = 15.0) -> bool:
    """Apaga el Faceless Studio encendido. True si el puerto quedó libre."""
    if not port_in_use(host, port):
        return True
    if sys.platform != "win32":
        return False
    pid = listener_pid(_run(["netstat", "-ano", "-p", "TCP"]), port)
    if pid is None:
        return False
    if not is_python(_run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])):
        return False  # otro programa usa el puerto: no se toca
    _run(["taskkill", "/PID", str(pid), "/F"])
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not port_in_use(host, port):
            return True
        time.sleep(0.5)
    return False
