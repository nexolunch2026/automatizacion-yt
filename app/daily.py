"""JARVIS para el día a día: lista de la compra y cuentas al instante (sin gastar IA).

- «añade leche y huevos a la lista de la compra», «¿qué hay en la lista?», «ya compré
  los huevos», «borra la lista de la compra».
- «¿cuánto es 25 por 4?», «el 15 por ciento de 80000», «calcula 3500 entre 7».
"""

import ast
import json
import operator
import re

from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

KEY = "shopping_list"
MAX_ITEMS = 60

LIST = r"(?:la )?lista(?: de (?:la )?compra| del (?:super|mercado)| de mercado)?"
ADD = re.compile(rf"^(?:anade|agrega|apunta|pon|mete|suma)\s+(.+?)\s+(?:a|en)\s+{LIST}$")
# «ya compré los huevos» o «quita el pan de la lista» (sin pisar «borra la tarea…»).
BOUGHT = re.compile(rf"^(?:(?:ya )?compre\s+(.+)|(?:quita|borra|tacha)\s+(.+?)\s+de\s+{LIST})$")
SHOW = (
    "lista de la compra",
    "la lista de la compra",
    "lista del mercado",
    "lista del super",
    "que hay en la lista",
    "que hay en la lista de la compra",
    "que tengo que comprar",
    "que hay que comprar",
    "que me falta comprar",
)
CLEAR = (
    "borra la lista de la compra",
    "vacia la lista de la compra",
    "ya compre todo",
    "borra la lista del mercado",
    "vacia la lista",
)


def items(db: Session) -> list[str]:
    try:
        return json.loads(get_setting(db, KEY) or "[]")
    except ValueError:
        return []


def _save(db: Session, values: list[str]) -> None:
    set_setting(db, KEY, json.dumps(values[:MAX_ITEMS], ensure_ascii=False))


def split_items(text: str) -> list[str]:
    parts = re.split(r",|\by\b|\be\b|;", text)
    return [p.strip(" .").strip() for p in parts if p.strip(" .").strip()]


def add(db: Session, text: str) -> str:
    current = items(db)
    new = [i for i in split_items(text) if i.lower() not in {c.lower() for c in current}]
    _save(db, current + new)
    if not new:
        return "🛒 Eso ya estaba en la lista."
    return f"🛒 Añadido a la lista: {', '.join(new)}. Llevas {len(current) + len(new)}."


def remove(db: Session, text: str) -> str | None:
    """Quita lo comprado. None si no estaba en la lista (entonces era otra orden)."""
    wanted = [w.lower() for w in split_items(text)]
    current = items(db)
    keep = [i for i in current if not any(w in i.lower() or i.lower() in w for w in wanted)]
    if len(keep) == len(current):
        return None
    _save(db, keep)
    left = f"Quedan {len(keep)}." if keep else "¡Lista terminada!"
    return f"✅ Tachado. {left}"


def show(db: Session) -> str:
    current = items(db)
    if not current:
        return "🛒 La lista de la compra está vacía."
    return "🛒 <b>Lista de la compra</b>\n" + "\n".join(f"• {i}" for i in current)


def clear(db: Session) -> str:
    _save(db, [])
    return "🛒 Lista de la compra borrada."


# ---------------------------------------------------------------- cuentas

CALC = re.compile(r"^(?:cuanto es|cuanto son|calcula|calculame|cuanto da)\s+(.+)$")
PERCENT = re.compile(r"^(?:el\s+)?([\d.,]+)\s*(?:%|por ciento)\s+de\s+([\d.,]+)$")
WORDS = [
    (r"\bmultiplicado por\b|\bpor\b|\bx\b|×", "*"),
    (r"\bdividido (?:entre|por)\b|\bentre\b|÷", "/"),
    (r"\bmas\b", "+"),
    (r"\bmenos\b", "-"),
    (r"\bal cuadrado\b", "**2"),
]
OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _number(text: str) -> float:
    """«80.000» y «1.234,5» (como se escribe en Colombia) o «12.5»."""
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    return float(text)


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        right = _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("demasiado grande")
        return OPS[type(node.op)](_eval(node.left), right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError("no es una cuenta")


def calculate(expression: str) -> float | None:
    """Resultado de una cuenta dicha con palabras, o None si no lo es."""
    text = expression.strip(" ?¿.")
    match = PERCENT.match(text)
    if match:
        return _number(match.group(1)) * _number(match.group(2)) / 100
    for pattern, symbol in WORDS:
        text = re.sub(pattern, symbol, text)
    text = re.sub(r"\d[\d.,]*", lambda m: repr(_number(m.group(0))), text)
    if not re.fullmatch(r"[\d.+\-*/() e]+", text):
        return None
    try:
        return _eval(ast.parse(text, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None


def say_number(value: float) -> str:
    """Como se escribe en Colombia: 1.234,5 (sin decimales si es entero)."""
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}".replace(",", ".")
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", "_").replace(".", ",").replace("_", ".")
