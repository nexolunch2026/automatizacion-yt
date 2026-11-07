"""GUION MÁS HUMANO: busca frases que suenan a máquina al narrarlas.

No usa IA ni internet. Mira cada párrafo del guion y avisa de tres cosas que cansan al
oído en un documental:
- Frases demasiado largas: al narrarlas se pierde el hilo (y la voz no respira).
- Palabras repetidas: la misma palabra varias veces en el mismo párrafo.
- Palabras de relleno: «básicamente», «cabe destacar»… alargan sin decir nada.
- Frases de IA: «en un mundo donde», «fascinante», «no solo… sino»… delatan a la máquina.

El botón «Hacerlo más humano» de cada párrafo pide a la IA que cambie solo esas frases;
«Humanizar todo el guion» (jobs._run_humanize) lo hace con todos los párrafos marcados.
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
    "sin lugar a dudas",
    "en ultima instancia",
    "dicho esto",
    "no es ningun secreto",
)

# Frases hechas que delatan un texto escrito por IA (sin tildes, en minúsculas). No son
# relleno: dicen algo, pero de la forma en que lo diría cualquier máquina.
CLICHES = (
    "en un mundo donde",
    "en un mundo en el que",
    "sumergete",
    "sumerjamonos",
    "adentremonos",
    "un viaje fascinante",
    "fascinante",
    "crucial",
    "en conclusion",
    "en resumen",
    "juega un papel",
    "jugo un papel",
    "cabe senalar",
    "pero eso no es todo",
    "y aqui es donde",
    "en el corazon de",
    "a medida que avanzamos",
    "un testimonio de",
    "dejo una huella imborrable",
    "un antes y un despues",
    "en la era de",
    "el panorama",
    "redefinir",
    "redefinio",
)
# Va en todos los prompts del guion (escribir y reescribir párrafos): así ya sale humano.
HUMAN_VOICE = (
    "Voz humana: escribe como habla un narrador que se lo cuenta a un amigo, no como un "
    "texto de IA. Mezcla frases cortas con alguna más larga, usa palabras sencillas y "
    "concretas (cifras, nombres, lugares) y algún giro coloquial. Nunca uses frases hechas "
    "de IA como «en un mundo donde», «fascinante», «crucial», «juega un papel», «en "
    "resumen», «pero eso no es todo», «un antes y un después» ni la estructura «no solo… "
    "sino también»."
)

# «No solo… sino (también)…»: la estructura favorita de los textos de IA.
NOT_ONLY = re.compile(r"\bno solo\b[^.!?…]*\bsino\b")

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
    # En un canal de marcas, estas salen en casi todos los párrafos.
    "empresa",
    "empresas",
    "compania",
    "marca",
    "marcas",
}


def _plain(text: str) -> str:
    """Minúsculas y sin tildes, letra a letra: mide lo mismo que el texto original, así
    lo encontrado se puede recortar del original con sus tildes."""
    out = []
    for ch in text:
        bare = unicodedata.normalize("NFD", ch.lower())
        out.append("".join(c for c in bare if unicodedata.category(c) != "Mn")[:1] or ch)
    return "".join(out)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zñ]+", _plain(text)))


def sentences(text: str) -> list[str]:
    """Frases del párrafo, cortando por punto, signo de exclamación o interrogación."""
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s.strip()]


def paragraph_issues(text: str, names: set[str] | None = None) -> list[dict]:
    """Avisos de un párrafo: [{kind, text, detail}]. Lista vacía si suena bien.
    `names` son palabras que no cuentan como repetidas (las del título: la marca)."""
    skip = COMMON | (names or set())
    issues = []
    for sentence in sentences(text):
        words = len(sentence.split())
        if words > LONG_SENTENCE_WORDS:
            issues.append(
                {"kind": "long", "text": sentence, "detail": f"Frase de {words} palabras"}
            )

    plain = _plain(text)
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}  # la palabra tal como está escrita (con tildes)
    for match in re.finditer(r"[a-zñ]+", plain):
        word = match.group()
        if len(word) >= REPEAT_MIN_LETTERS and word not in skip:
            counts[word] = counts.get(word, 0) + 1
            shown.setdefault(word, text[match.start() : match.end()].lower())
    for word, times in sorted(counts.items(), key=lambda item: -item[1]):
        if times >= REPEAT_MIN_TIMES:
            original = shown[word]
            issues.append(
                {
                    "kind": "repeat",
                    "text": original,
                    "detail": f"«{original}» se repite {times} veces",
                }
            )

    for filler in FILLERS:
        found = re.search(rf"\b{filler}\b", plain)
        if found:
            original = text[found.start() : found.end()].lower()
            issues.append({"kind": "filler", "text": original, "detail": f"Relleno: «{original}»"})

    for cliche in CLICHES:
        found = re.search(rf"\b{cliche}\b", plain)
        if found:
            original = text[found.start() : found.end()].lower()
            issues.append(
                {"kind": "cliche", "text": original, "detail": f"Suena a IA: «{original}»"}
            )
    found = NOT_ONLY.search(plain)
    if found:
        original = text[found.start() : found.end()]
        issues.append({"kind": "cliche", "text": original, "detail": "Suena a IA: «no solo… sino»"})
    return issues


def script_issues(script: dict | None) -> dict:
    """Revisa el guion entero: avisos por párrafo y cuántos hay de cada tipo."""
    by_paragraph: dict[str, list[dict]] = {}
    total = 0
    names = _words((script or {}).get("title", ""))
    for section in (script or {}).get("sections", []):
        for paragraph in section["paragraphs"]:
            total += 1
            issues = paragraph_issues(paragraph["text"], names)
            if issues:
                by_paragraph[paragraph["id"]] = issues
    counts = {"long": 0, "repeat": 0, "filler": 0, "cliche": 0}
    for issues in by_paragraph.values():
        for issue in issues:
            counts[issue["kind"]] += 1
    return {"paragraphs": by_paragraph, "counts": counts, "total": total}


def humanize_instruction(text: str, title: str = "") -> str:
    """Instrucción para la IA: cambiar solo las frases con avisos y dejar el resto igual."""
    issues = paragraph_issues(text, _words(title))
    if not issues:
        return "Haz que este párrafo suene más natural al narrarlo, sin cambiar los datos."
    lines = []
    for issue in issues:
        if issue["kind"] == "long":
            lines.append(f"- Parte en dos o tres frases cortas: «{issue['text']}»")
        elif issue["kind"] == "repeat":
            lines.append(f"- Cambia a veces «{issue['text']}» por un sinónimo o un pronombre.")
        elif issue["kind"] == "cliche":
            lines.append(
                f"- «{issue['text']}» suena a texto de máquina: dilo como lo contaría una "
                "persona a un amigo, con palabras sencillas y concretas."
            )
        else:
            lines.append(f"- Quita el relleno «{issue['text']}» (o di algo concreto en su lugar).")
    return (
        "Haz que este párrafo suene más humano al narrarlo. Cambia SOLO esto y deja el resto "
        "de frases como están, con los mismos datos:\n" + "\n".join(lines)
    )
