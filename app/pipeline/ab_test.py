"""«PROBAR Y COMPARAR»: deja listo el A/B de títulos y miniaturas de YouTube Studio.

YouTube enseña cada combinación a una parte del público durante hasta 14 días y gana la
que consigue más TIEMPO VISTO por cada vez que se muestra (no solo más clics). Por eso
conviene probar ideas de verdad distintas, no tres versiones casi iguales. No usa IA: toma
los títulos de Publicación (y su estilo y razón de la Estrategia) y las 3 miniaturas.
"""

import re
import unicodedata

MAX_TITLE = 60  # más largo se corta en el móvil
TOO_SIMILAR = 0.7  # parte de palabras compartidas a partir de la cual dos títulos «son iguales»
STOP = {
    "de", "la", "el", "los", "las", "y", "en", "que", "un", "una", "por", "con", "a", "del",
    "lo", "se", "su", "sus", "al", "es", "o",
}  # fmt: skip


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(ch for ch in plain if unicodedata.category(ch) != "Mn")
    return {w for w in re.findall(r"[a-z0-9ñ]+", plain) if w not in STOP}


def similarity(a: str, b: str) -> float:
    """Parte de las palabras del título más corto que también están en el otro."""
    wa, wb = _words(a), _words(b)
    small = min(len(wa), len(wb))
    return len(wa & wb) / small if small else 0.0


def _strategy_titles(strategy: dict | None) -> dict[str, dict]:
    """Título (en minúsculas) → su estilo y razón, del enfoque elegido en la Estrategia."""
    if not strategy or not strategy.get("selected"):
        return {}
    concept = strategy["concepts"][strategy["selected"]["concept"]]
    return {t["title"].strip().lower(): t for t in concept.get("titles", [])}


def ab_plan(seo: dict | None, strategy: dict | None, thumbnail: dict | None) -> dict:
    seo = seo or {}
    known = _strategy_titles(strategy)
    titles: list[dict] = []
    for text in seo.get("titles", []):
        if len(titles) == 3:
            break
        if any(text.strip().lower() == t["text"].lower() for t in titles):
            continue
        info = known.get(text.strip().lower(), {})
        titles.append(
            {
                "text": text.strip(),
                "length": len(text.strip()),
                "too_long": len(text.strip()) > MAX_TITLE,
                "style": info.get("style", ""),
                "reason": info.get("reason", ""),
            }
        )
    warnings = []
    for i, a in enumerate(titles):
        for b in titles[i + 1 :]:
            if similarity(a["text"], b["text"]) >= TOO_SIMILAR:
                warnings.append(
                    f"«{a['text']}» y «{b['text']}» se parecen demasiado: para que la prueba "
                    "sirva, cambia uno por una idea distinta."
                )
    for t in titles:
        if t["too_long"]:
            warnings.append(f"«{t['text']}» tiene {t['length']} caracteres: en el móvil se corta.")

    variants = (thumbnail or {}).get("variants", [])[:3]
    main_title = titles[0]["text"] if titles else ""
    thumbs = []
    for v in variants:
        words = _words(v.get("text", ""))
        repeats = bool(words) and len(words & _words(main_title)) / len(words) > 0.5
        thumbs.append({"file": v["file"], "text": v.get("text", ""), "repeats_title": repeats})
        if repeats:
            warnings.append(
                f"La miniatura «{v.get('text', '')}» repite el título: el texto de la miniatura "
                "debe añadir algo nuevo."
            )
    return {
        "titles": titles,
        "thumbs": thumbs,
        "warnings": warnings,
        "ready": len(titles) >= 2 and len(thumbs) >= 2,
    }
