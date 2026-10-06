"""Color de acento del canal (líneas, cifras resaltadas, subtítulos, miniaturas, gráficos).

Cada canal puede tener el suyo; por defecto, el rojo de siempre. El trabajador lo fija
mientras hace una tarea del canal (`use`) y los dibujos lo leen con `color()`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

RED = (230, 57, 70)
# Nombre → color (RGB). Todos se leen bien sobre fondo oscuro y con texto blanco.
PALETTE = {
    "rojo": RED,
    "amarillo": (255, 196, 0),
    "naranja": (255, 122, 26),
    "verde": (46, 196, 112),
    "cian": (0, 184, 212),
    "azul": (52, 120, 246),
    "morado": (150, 92, 230),
    "rosa": (236, 72, 153),
}
_current: ContextVar[tuple[int, int, int]] = ContextVar("accent", default=RED)


def color() -> tuple[int, int, int]:
    return _current.get()


def by_name(name: str | None) -> tuple[int, int, int]:
    return PALETTE.get((name or "").strip().lower(), RED)


def ass() -> str:
    """El color para los subtítulos ASS (&H00BBGGRR&)."""
    r, g, b = color()
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def css(name: str | None) -> str:
    r, g, b = by_name(name)
    return f"#{r:02x}{g:02x}{b:02x}"


@contextmanager
def use(name: str | None) -> Iterator[None]:
    token = _current.set(by_name(name))
    try:
        yield
    finally:
        _current.reset(token)
