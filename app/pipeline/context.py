"""Convierte resultados de etapas anteriores en texto para dárselo a la IA."""


def research_summary(research: dict) -> str:
    """Resumen del informe con los números de fuente, para que el guion no invente datos."""
    lines = [f"CONTEXTO: {research.get('context', '')}", "", "DATOS VERIFICADOS:"]
    for key in ("key_facts", "timeline", "people", "figures"):
        for fact in research.get(key, []):
            refs = ",".join(str(n) for n in fact.get("sources", []))
            lines.append(f"- {fact['text']} [{refs}]")
    if research.get("controversial"):
        lines += ["", "PUNTOS CONTROVERTIDOS (preséntalos como discutidos):"]
        lines += [f"- {c}" for c in research["controversial"]]
    if research.get("needs_verification"):
        lines += ["", "NO VERIFICADO (no lo afirmes como hecho):"]
        lines += [f"- {c}" for c in research["needs_verification"]]
    return "\n".join(lines)
