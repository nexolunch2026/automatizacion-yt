"""CONTROL DE CALIDAD: revisa si el vídeo cumple lo que YouTube pide para ganar dinero.

No usa IA ni internet: mira lo que ya hicieron las etapas (guion, escenas, visuales, voz,
vídeo, publicación, miniatura, Shorts) y devuelve una lista de comprobaciones con un
semáforo y qué hacer para arreglar cada una. Se basa en las normas del Programa de
Socios de YouTube:
- Contenido no auténtico (antes «repetitivo»): YouTube no paga vídeos hechos en serie con
  plantilla o que solo leen datos sin aportar nada. Hace falta análisis propio y variedad.
- Contenido reutilizado y derechos: imágenes, vídeos y música con licencia y con créditos.
- Anuncios: los de mitad del vídeo solo se pueden poner a partir de 8 minutos. Las
  palabrotas o temas delicados en el título o al principio limitan los anuncios.
- Contenido alterado o sintético: marcarlo en YouTube Studio si hay imágenes realistas de IA.
"""

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, StageResult

OK, WARN, FAIL, PENDING = "ok", "warn", "fail", "pending"
POINTS = {OK: 1.0, WARN: 0.5, FAIL: 0.0, PENDING: 0.0}
AREAS = {
    "ads": "Anuncios e ingresos",
    "original": "Originalidad (contenido no auténtico)",
    "rights": "Derechos y avisos",
    "audience": "Retención del público",
    "publish": "Listo para subir",
}

MIDROLL_SECONDS = 8 * 60  # desde aquí YouTube deja poner anuncios a mitad del vídeo
WORDS_PER_SECOND = 2.5
HOOK_MAX_SECONDS = 30
SCENE_MAX_SECONDS = 12
CARD_MAX_SHARE = 0.2
SOURCED_MIN_SHARE = 0.5
TITLE_MAX = 70
NGRAM = 5
OVERLAP_WARN, OVERLAP_FAIL = 0.15, 0.3
SLOW_OPENINGS = ("hola", "bienvenid", "en este video", "en el video de hoy", "hoy vamos a")

# Palabras que hacen que YouTube limite los anuncios (sin tildes, en minúsculas).
# Las palabrotas son lo más grave; los temas delicados se pueden tratar con tono
# informativo, pero mejor fuera del título y del principio.
PROFANITY = {"mierda", "joder", "puta", "puto", "cabron", "gilipollas", "coño", "carajo"}
SENSITIVE = {
    "suicidio",
    "suicido",
    "asesinato",
    "masacre",
    "violacion",
    "cocaina",
    "heroina",
    "terrorismo",
    "terrorista",
    "genocidio",
    "tortura",
    "nazi",
    "nazis",
    "pornografia",
}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zñ0-9]+", _plain(text))


def script_text(script: dict | None) -> str:
    return " ".join(p["text"] for s in (script or {}).get("sections", []) for p in s["paragraphs"])


def ngrams(text: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    words = _words(text)
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def overlap(text: str, other: str) -> float:
    """Parte de las frases de `text` (en grupos de 5 palabras) que ya están en `other`."""
    mine = ngrams(text)
    return len(mine & ngrams(other)) / len(mine) if mine else 0.0


def flagged_words(text: str) -> tuple[list[str], list[str]]:
    words = set(_words(text))
    return sorted(words & PROFANITY), sorted(words & SENSITIVE)


def video_seconds(results: dict) -> float | None:
    for stage, key in (("edit", "seconds"), ("voice", "seconds"), ("storyboard", "total_seconds")):
        value = (results.get(stage) or {}).get(key)
        if value:
            return float(value)
    script = results.get("script")
    return len(script_text(script).split()) / WORDS_PER_SECOND if script else None


def _check(key, area, status, title, detail, fix="", link=""):
    return {
        "key": key,
        "area": area,
        "status": status,
        "title": title,
        "detail": detail,
        "fix": fix,
        "link": link,
    }


def _minutes(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02}"


def _ads_checks(project: Project, results: dict, title: str) -> list[dict]:
    checks = []
    seconds = video_seconds(results)
    if project.duration == "Short":
        checks.append(_check("midroll", "ads", OK, "Short", "Los Shorts cobran por visitas."))
    elif seconds is None:
        checks.append(_check("midroll", "ads", PENDING, "Duración", "Falta el guion.", "", "guion"))
    elif seconds >= MIDROLL_SECONDS:
        checks.append(
            _check(
                "midroll",
                "ads",
                OK,
                f"Dura {_minutes(seconds)}: admite anuncios a mitad del vídeo",
                "Con 8 minutos o más puedes activar varios anuncios y ganar más por visita.",
            )
        )
    else:
        checks.append(
            _check(
                "midroll",
                "ads",
                WARN,
                f"Dura {_minutes(seconds)}: menos de 8 minutos",
                "Por debajo de 8 minutos solo hay anuncios al principio y al final.",
                "Crea el próximo proyecto con la duración «10–15 min» o alarga el guion.",
                "guion",
            )
        )

    beginning = " ".join(_words(script_text(results.get("script")))[:40])
    bad_title, sensitive_title = flagged_words(title)
    bad_start, _ = flagged_words(beginning)
    bad_all, sensitive_all = flagged_words(script_text(results.get("script")))
    if bad_title or bad_start or sensitive_title:
        found = ", ".join(sorted(set(bad_title + bad_start + sensitive_title)))
        checks.append(
            _check(
                "friendly",
                "ads",
                FAIL,
                "Palabras que quitan anuncios en el título o al principio",
                f"Encontradas: {found}. YouTube limita los anuncios por esto.",
                "Cámbialas por palabras neutras (p. ej. «quiebra» en vez de «masacre»).",
                "guion",
            )
        )
    elif bad_all or sensitive_all:
        found = ", ".join(bad_all + sensitive_all)
        checks.append(
            _check(
                "friendly",
                "ads",
                WARN,
                "Temas delicados dentro del guion",
                f"Encontradas: {found}. Se puede hablar de ello con tono informativo,"
                " pero sin detalles gráficos ni palabrotas.",
                "Revisa esos párrafos en el guion.",
                "guion",
            )
        )
    elif results.get("script"):
        checks.append(
            _check("friendly", "ads", OK, "Lenguaje apto para anunciantes", "Sin palabrotas.")
        )
    return checks


def _original_checks(results: dict, others: list[str]) -> list[dict]:
    script = results.get("script")
    if not script:
        return [_check("original", "original", PENDING, "Originalidad", "Falta el guion.")]
    text = script_text(script)
    checks = []
    worst = max((overlap(text, other) for other in others), default=0.0)
    pct = round(worst * 100)
    if worst >= OVERLAP_FAIL:
        status, title = FAIL, f"El {pct} % del guion se repite de otro vídeo tuyo"
    elif worst >= OVERLAP_WARN:
        status, title = WARN, f"El {pct} % del guion se parece a otro vídeo tuyo"
    else:
        status, title = OK, "Guion distinto a tus otros vídeos"
    checks.append(
        _check(
            "repeat",
            "original",
            status,
            title,
            "YouTube no paga canales con vídeos hechos en serie con la misma plantilla.",
            "" if status == OK else "Reescribe los párrafos repetidos (botón «Otra forma»).",
            "guion",
        )
    )

    paragraphs = [p for s in script["sections"] for p in s["paragraphs"]]
    facts = [
        p
        for s in script["sections"]
        if s["kind"] in ("development", "climax")
        for p in s["paragraphs"]
    ] or paragraphs
    sourced = sum(1 for p in facts if p.get("sources")) / len(facts) if facts else 0
    checks.append(
        _check(
            "sources",
            "original",
            OK if sourced >= SOURCED_MIN_SHARE else WARN,
            f"{round(sourced * 100)} % de los datos con fuente",
            "Los datos comprobables dan valor propio y protegen de quejas por desinformación.",
            "" if sourced >= SOURCED_MIN_SHARE else "Vuelve a investigar o reescribe esos datos.",
            "guion",
        )
    )

    edited = script.get("edited", 0)
    checks.append(
        _check(
            "human",
            "original",
            OK if edited else WARN,
            "Guion revisado por ti" if edited else "Guion sin retocar",
            "Tu toque personal (opinión, lección, humor) es lo que separa un canal monetizable"
            " de uno automático.",
            "" if edited else "Cambia al menos un par de párrafos con tus palabras.",
            "guion",
        )
    )
    return checks


def _rights_checks(results: dict) -> list[dict]:
    checks = []
    visuals = results.get("visuals")
    items = list((visuals or {}).get("items", {}).values())
    if not visuals:
        checks.append(_check("license", "rights", PENDING, "Visuales", "Aún no hay visuales."))
    else:
        unknown = [e for e in items if e.get("kind") != "card" and not e.get("license")]
        checks.append(
            _check(
                "license",
                "rights",
                WARN if unknown else OK,
                f"{len(unknown)} visuales sin licencia" if unknown else "Visuales con licencia",
                "Las imágenes de bancos gratis y las de IA no dan problemas de derechos.",
                "Cambia esas escenas por otras del banco o generadas con IA." if unknown else "",
                "visuales",
            )
        )
        if any(e.get("ai") for e in items):
            checks.append(
                _check(
                    "synthetic",
                    "rights",
                    WARN,
                    "Hay imágenes de IA: márcalo al subir",
                    "YouTube pide avisar del contenido alterado o sintético si parece real.",
                    "En YouTube Studio → Detalles → «Contenido alterado» marca «Sí».",
                    "publicacion",
                )
            )

    voice = results.get("voice") or {}
    if voice.get("provider") == "elevenlabs":
        checks.append(
            _check(
                "voice",
                "rights",
                WARN,
                "Voz de ElevenLabs",
                "El plan gratis de ElevenLabs no permite uso comercial (canal monetizado).",
                "Usa un plan de pago de ElevenLabs o una voz Piper.",
                "voz",
            )
        )
    elif voice:
        checks.append(_check("voice", "rights", OK, "Voz libre de uso", "Voz Piper sin coste."))

    music = (results.get("edit") or {}).get("music")
    if music:
        checks.append(
            _check(
                "music",
                "rights",
                WARN,
                f"Música: {music}",
                "Solo es segura la música de la Biblioteca de audio de YouTube o con licencia.",
                "Si no sabes de dónde salió, cámbiala antes de subir.",
                "video",
            )
        )
    return checks


def _audience_checks(results: dict) -> list[dict]:
    checks = []
    script = results.get("script")
    if script:
        hook = [s for s in script["sections"] if s["kind"] in ("hook", "promise")]
        hook_seconds = len(script_text({"sections": hook}).split()) / WORDS_PER_SECOND
        first = _plain(script_text(script)[:60])
        slow = any(first.startswith(_plain(w)) for w in SLOW_OPENINGS)
        good = hook and hook_seconds <= HOOK_MAX_SECONDS and not slow
        checks.append(
            _check(
                "hook",
                "audience",
                OK if good else WARN,
                "Gancho rápido" if good else "El principio tarda en enganchar",
                "Los primeros 30 segundos deciden si la gente se queda.",
                ""
                if good
                else "Empieza con lo más intrigante, sin saludar ni decir «en este vídeo».",
                "guion",
            )
        )

    board = results.get("storyboard")
    if board and board.get("scenes"):
        scenes = board["scenes"]
        average = sum(s["seconds"] for s in scenes) / len(scenes)
        checks.append(
            _check(
                "pace",
                "audience",
                OK if average <= SCENE_MAX_SECONDS else WARN,
                f"Cambio de imagen cada {round(average)} s de media",
                "Cambiar de imagen a menudo mantiene la atención.",
                "" if average <= SCENE_MAX_SECONDS else "Divide los párrafos largos del guion.",
                "escenas",
            )
        )

    items = list((results.get("visuals") or {}).get("items", {}).values())
    if items:
        cards = sum(1 for e in items if e.get("kind") == "card") / len(items)
        checks.append(
            _check(
                "cards",
                "audience",
                OK if cards <= CARD_MAX_SHARE else WARN,
                f"{round(cards * 100)} % de escenas solo con texto",
                "Muchas tarjetas de texto parecen un vídeo de poco esfuerzo.",
                "" if cards <= CARD_MAX_SHARE else "Pon imágenes en esas escenas (IA o banco).",
                "visuales",
            )
        )
    return checks


def _publish_checks(project: Project, results: dict, title: str) -> list[dict]:
    checks = []
    seo = results.get("publish")
    if not seo:
        checks.append(
            _check(
                "seo",
                "publish",
                PENDING,
                "Textos de publicación",
                "Falta preparar título, descripción y etiquetas.",
                link="publicacion",
            )
        )
    else:
        long_title = len(title) > TITLE_MAX
        checks.append(
            _check(
                "title",
                "publish",
                WARN if long_title else OK,
                f"Título de {len(title)} caracteres",
                "Más de 70 se corta en el móvil.",
                "Elige un título más corto." if long_title else "",
                "publicacion",
            )
        )
        exact = seo.get("chapters") and seo.get("chapters_exact")
        checks.append(
            _check(
                "chapters",
                "publish",
                OK if exact else WARN,
                "Capítulos exactos" if exact else "Capítulos aproximados o sin capítulos",
                "Los capítulos ayudan a salir en Google y a que vean más minutos.",
                "" if exact else "Graba la voz y pulsa «Volver a generar» en Publicación.",
                "publicacion",
            )
        )

    thumb = results.get("thumbnail")
    chosen = thumb and thumb.get("selected") is not None
    checks.append(
        _check(
            "thumbnail",
            "publish",
            OK if chosen else PENDING,
            "Miniatura elegida" if chosen else "Falta elegir la miniatura",
            "La miniatura decide gran parte de los clics.",
            link="miniatura",
        )
    )
    if project.duration != "Short":
        has_shorts = bool((results.get("shorts") or {}).get("shorts"))
        checks.append(
            _check(
                "shorts",
                "publish",
                OK if has_shorts else PENDING,
                "Shorts preparados" if has_shorts else "Sin Shorts",
                "Los Shorts traen suscriptores nuevos hacia el vídeo largo.",
                link="shorts",
            )
        )
    return checks


def chosen_title(results: dict, project: Project) -> str:
    seo = results.get("publish") or {}
    if seo.get("titles"):
        return seo["titles"][0]
    return (results.get("script") or {}).get("title") or project.title


def review(project: Project, results: dict, other_scripts: list[str]) -> dict:
    """Revisa el proyecto. `other_scripts` son los guiones de los demás vídeos del canal."""
    title = chosen_title(results, project)
    checks = (
        _ads_checks(project, results, title)
        + _original_checks(results, other_scripts)
        + _rights_checks(results)
        + _audience_checks(results)
        + _publish_checks(project, results, title)
    )
    score = round(100 * sum(POINTS[c["status"]] for c in checks) / len(checks)) if checks else 0
    fails = sum(1 for c in checks if c["status"] == FAIL)
    pending = sum(1 for c in checks if c["status"] == PENDING)
    if fails:
        verdict = "Hay cosas que pueden quitarte los anuncios: arréglalas antes de subir."
    elif pending:
        verdict = "Aún faltan etapas por terminar."
    elif score >= 85:
        verdict = "Listo para subir y monetizar."
    else:
        verdict = "Se puede subir, pero mejorando los avisos ganarás más."
    return {
        "score": score,
        "verdict": verdict,
        "checks": checks,
        "counts": {s: sum(1 for c in checks if c["status"] == s) for s in POINTS},
        "title": title,
    }


def project_review(db: Session, project: Project) -> dict:
    """Revisa un proyecto guardado comparando su guion con los demás vídeos del canal."""
    results = {
        r.stage: r.data
        for r in db.scalars(select(StageResult).where(StageResult.project_id == project.id))
    }
    others = db.scalars(
        select(StageResult)
        .join(Project, Project.id == StageResult.project_id)
        .where(
            StageResult.stage == "script",
            Project.channel_id == project.channel_id,
            Project.id != project.id,
        )
    )
    return review(project, results, [script_text(r.data) for r in others])


def summary_text(qc: dict) -> str:
    """Resumen corto (para JARVIS): la nota y lo que hay que arreglar primero."""
    icons = {FAIL: "⛔", WARN: "⚠️", PENDING: "⏳"}
    order = {FAIL: 0, WARN: 1, PENDING: 2}
    todo = sorted((c for c in qc["checks"] if c["status"] != OK), key=lambda c: order[c["status"]])
    lines = [f"Nota de monetización: {qc['score']}/100. {qc['verdict']}"]
    lines += [
        f"{icons[c['status']]} {c['title']}" + (f" → {c['fix']}" if c["fix"] else "")
        for c in todo[:5]
    ]
    return "\n".join(lines)
