"""Sala de montaje: la línea de tiempo del vídeo (escenas, voz y subtítulos) y los avisos de
JARVIS como copiloto, para la página de cada proyecto.

Todo sale de lo que ya está guardado (guion de escenas, imágenes, voz y control de calidad):
no llama a internet, así que la página carga al momento."""

import array
import json
import wave
from pathlib import Path

from app.media import project_dir

WAVE_BARS = 160  # columnas de la onda de la voz
MAX_TIPS = 4


def _scene_starts(storyboard: dict, voice: dict | None) -> list[tuple[dict, float, float]]:
    """(escena, empieza, dura) en segundos: con la voz grabada, los tiempos reales."""
    takes = {
        t["paragraph_id"]: float(t.get("seconds") or 0) for t in (voice or {}).get("takes", [])
    }
    out, t = [], 0.0
    for scene in storyboard.get("scenes", []):
        seconds = takes.get(scene.get("paragraph_id")) or float(scene.get("seconds") or 0)
        out.append((scene, t, seconds))
        t += seconds
    return out


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def voice_wave(project_id: int, bars: int = WAVE_BARS) -> list[int]:
    """La forma de la onda de la narración (0-100 por columna), guardada en caché junto al
    audio para no leer el WAV entero en cada visita."""
    folder = project_dir(project_id) / "voz"
    audio = folder / "narracion.wav"
    if not audio.exists():
        return []
    cache = folder / "onda.json"
    stamp = audio.stat().st_mtime
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("stamp") == stamp and len(saved.get("bars", [])) == bars:
            return saved["bars"]
    except (OSError, ValueError):
        pass
    try:
        with wave.open(str(audio), "rb") as w:
            if w.getsampwidth() != 2:
                return []
            frames = w.getnframes()
            per_bar = max(frames // bars, 1)
            step = max(per_bar // 400, 1)  # muestrea: rápido aunque el audio dure 15 minutos
            peaks = []
            for _ in range(bars):
                chunk = array.array("h")
                chunk.frombytes(w.readframes(per_bar)[: per_bar * 2 * w.getnchannels()])
                if not chunk:
                    peaks.append(0)
                    continue
                peaks.append(max(abs(chunk[i]) for i in range(0, len(chunk), step)))
    except (OSError, wave.Error, EOFError):
        return []
    top = max(peaks) or 1
    result = [max(6, round(100 * p / top)) for p in peaks]
    try:
        cache.write_text(json.dumps({"stamp": stamp, "bars": result}), encoding="utf-8")
    except OSError:
        pass
    return result


def timeline(project_id: int, results: dict) -> dict | None:
    """Las escenas con su imagen, cuándo empiezan y cuánto duran, más la onda de la voz."""
    storyboard = results.get("storyboard")
    if not storyboard or not storyboard.get("scenes"):
        return None
    items = (results.get("visuals") or {}).get("items") or {}
    rows = _scene_starts(storyboard, results.get("voice"))
    total = sum(d for _, _, d in rows) or 1.0
    scenes = []
    for scene, start, seconds in rows:
        entry = items.get(scene.get("paragraph_id")) or {}
        file = entry.get("file")
        scenes.append(
            {
                "n": scene.get("number"),
                "img": f"/proyectos/{project_id}/archivos/visuales/{file}" if file else None,
                "start": round(start, 2),
                "at": _fmt(start),
                "width": round(100 * seconds / total, 3),
                "text": " ".join((scene.get("narration") or "").split()),
            }
        )
    return {
        "scenes": scenes,
        "total": _fmt(total),
        # unas 6 columnas por escena: la onda se ve fina aunque la línea sea larga
        "wave": voice_wave(project_id, max(WAVE_BARS, 6 * len(scenes)))
        if results.get("voice")
        else [],
    }


def _duplicates(project_id: int, results: dict) -> list[int]:
    """Escenas cuya imagen es idéntica (mismo tamaño de archivo) a la de otra escena anterior."""
    items = (results.get("visuals") or {}).get("items") or {}
    seen, repeated = {}, []
    for scene in (results.get("storyboard") or {}).get("scenes", []):
        file = (items.get(scene.get("paragraph_id")) or {}).get("file")
        if not file:
            continue
        path = Path(project_dir(project_id)) / "visuales" / file
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size in seen:
            repeated.append(scene.get("number"))
        else:
            seen[size] = scene.get("number")
    return repeated


def copilot(project_id: int, results: dict, qc: dict | None) -> list[dict]:
    """Los avisos de JARVIS, lo más importante primero: [{level, text, fix, link}]."""
    tips = []
    storyboard = results.get("storyboard") or {}
    items = (results.get("visuals") or {}).get("items") or {}
    scenes = storyboard.get("scenes", [])
    if scenes and results.get("visuals") is not None:
        missing = [
            s["number"] for s in scenes if not (items.get(s.get("paragraph_id")) or {}).get("file")
        ]
        if missing:
            shown = ", ".join(str(n) for n in missing[:8]) + ("…" if len(missing) > 8 else "")
            tips.append(
                {
                    "level": "fail",
                    "text": f"Faltan {len(missing)} imágenes (escenas {shown}).",
                    "fix": "Pedirlas a Flow",
                    "link": f"/proyectos/{project_id}/visuales",
                }
            )
    repeated = _duplicates(project_id, results)
    if repeated:
        shown = ", ".join(str(n) for n in repeated[:8])
        tips.append(
            {
                "level": "warn",
                "text": f"{len(repeated)} escenas repiten imagen ({shown}). Se nota en el vídeo.",
                "fix": "Ver las escenas",
                "link": f"/proyectos/{project_id}/visuales",
            }
        )
    order = {"fail": 0, "warn": 1, "pending": 2}
    for check in sorted(
        (c for c in (qc or {}).get("checks", []) if c["status"] in order),
        key=lambda c: order[c["status"]],
    ):
        tips.append(
            {
                "level": check["status"],
                "text": check["title"] + (f": {check['detail']}" if check.get("detail") else ""),
                "fix": "Ir a arreglarlo" if check.get("link") else "",
                "link": f"/proyectos/{project_id}/{check['link']}" if check.get("link") else "",
                "detail_fix": check.get("fix") or "",
            }
        )
    if not tips and results.get("edit"):
        tips.append(
            {
                "level": "ok",
                "text": "Revisé el vídeo y no veo nada que arreglar. Listo para estrenar.",
                "fix": "Preparar el estreno",
                "link": f"/proyectos/{project_id}/publicacion",
            }
        )
    return tips[:MAX_TIPS]
