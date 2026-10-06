"""GUION MÁS HUMANO: busca frases que suenan a máquina al narrarlas.

No usa IA ni internet. Mira cada párrafo del guion y avisa de tres cosas que cansan al
oído en un documental:
- Frases demasiado largas: al narrarlas se pierde el hilo (y la voz no respira).
- Palabras repetidas: la misma palabra varias veces en el mismo párrafo.
- Palabras de relleno: «básicamente», «cabe destacar»… alargan sin decir nada.

El botón «Hacerlo más humano» de cada párrafo pide a la IA que cambie solo esas frases.
"""

import re
import unicodedata

LONG_SENTENCE_WORDS = 30  # más de 30 palabras seguidas sin punto: difícil de seguir
REPEAT_MIN_TIMES = 3  # la misma palabra 3 veces en un párrafo
REPEAT_MIN_LETTERS = 5  # solo palabras con contenido (no «que», «para», «como»…)
SHARE_WARN = 0.15  # más del 15 % de párrafos con avisos: el control de calidad avisa

# Muletillas típicas de textos escritos por IA o de relleno (sin tildes, en minúsculas).
FILLERS = (
    "basicamente",
    "literalmente",
    "realmente",
    "sin duda alguna",
    "cabe destacar",
    "cabe mencionar",
    "es importante destacar",
    "es importante mencionar",
    "vale la pena mencionar",
    "en pocas palabras",
    "en definitiva",
    "de alguna manera",
    "por asi decirlo",
    "a lo largo de la historia",
    "en el mundo actual",
    "hoy en dia",
    "sin lugar a dudas",
    "en ultima instancia",
    "dicho esto",
    "no es ningun secreto",
)

# Palabras largas que se repiten sin que suene mal (conectores y verbos comunes).
COMMON = {
    "porque",
    "aunque",
    "cuando",
    "donde",
    "entre",
    "sobre",
    "hasta",
    "desde",
    "tambien",
    "despues",
    "antes",
    "mientras",
    "estaba",
    "estaban",
    "habia",
    "tenia",
    "tenian",
    "fueron",
    "siempre",
    "nunca",
    "todos",
    "todas",
    "mucho",
    "muchos",
    "muchas",
    "otros",
    "otras",
    "puede",
    "podia",
    "hacer",
}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def sentences(text: str) -> list[str]:
    """Frases del párrafo, cortando por punto, signo de exclamación o interrogación."""
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s.strip()]


def paragraph_issues(text: str) -> list[dict]:
    """Avisos de un párrafo: [{kind, text, detail}]. Lista vacía si suena bien."""
    issues = []
    for sentence in sentences(text):
        words = len(sentence.split())
        if words > LONG_SENTENCE_WORDS:
            issues.append(
                {"kind": "long", "text": sentence, "detail": f"Frase de {words} palabras"}
            )

    plain = _plain(text)
    counts: dict[str, int] = {}
    for word in re.findall(r"[a-zñ]+", plain):
        if len(word) >= REPEAT_MIN_LETTERS and word not in COMMON:
            counts[word] = counts.get(word, 0) + 1
    for word, times in sorted(counts.items(), key=lambda item: -item[1]):
        if times >= REPEAT_MIN_TIMES:
            issues.append(
                {"kind": "repeat", "text": word, "detail": f"«{word}» se repite {times} veces"}
            )

    for filler in FILLERS:
        if re.search(rf"\b{filler}\b", plain):
            issues.append({"kind": "filler", "text": filler, "detail": f"Relleno: «{filler}»"})
    return issues


def script_issues(script: dict | None) -> dict:
    """Revisa el guion entero: avisos por párrafo y cuántos hay de cada tipo."""
    by_paragraph: dict[str, list[dict]] = {}
    total = 0
    for section in (script or {}).get("sections", []):
        for paragraph in section["paragraphs"]:
            total += 1
            issues = paragraph_issues(paragraph["text"])
            if issues:
                by_paragraph[paragraph["id"]] = issues
    counts = {"long": 0, "repeat": 0, "filler": 0}
    for issues in by_paragraph.values():
        for issue in issues:
            counts[issue["kind"]] += 1
    return {"paragraphs": by_paragraph, "counts": counts, "total": total}


def humanize_instruction(text: str) -> str:
    """Instrucción para la IA: cambiar solo las frases con avisos y dejar el resto igual."""
    issues = paragraph_issues(text)
    if not issues:
        return "Haz que este párrafo suene más natural al narrarlo, sin cambiar los datos."
    lines = []
    for issue in issues:
        if issue["kind"] == "long":
            lines.append(f"- Parte en dos o tres frases cortas: «{issue['text']}»")
        elif issue["kind"] == "repeat":
            lines.append(f"- Cambia a veces «{issue['text']}» por un sinónimo o un pronombre.")
        else:
            lines.append(f"- Quita el relleno «{issue['text']}» (o di algo concreto en su lugar).")
    return (
        "Haz que este párrafo suene más humano al narrarlo. Cambia SOLO esto y deja el resto "
        "de frases como están, con los mismos datos:\n" + "\n".join(lines)
    )
