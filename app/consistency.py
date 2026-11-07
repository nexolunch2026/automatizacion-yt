"""REVISIÓN DEL PROTAGONISTA: que salga igual en todas las imágenes del vídeo.

Con Google Flow el protagonista a veces cambia (pelo blanco en vez de negro, solo el contorno
del pelo, un marco blanco alrededor, otro estilo de dibujo…). Antes había que mirar las 70
imágenes a ojo. Ahora:
1. En Visuales se elige la imagen en la que el protagonista sale mejor: es la «ficha».
2. Gemini mira cada imagen (de 4 en 4) y dice datos concretos: color del pelo del
   protagonista, si hay marco blanco, texto u otro estilo. El programa los compara con la
   ficha y marca las distintas con el motivo («pelo blanco o gris», «marco blanco»…).
3. Con un botón, las marcadas pasan a «rehacer»: los mensajes para Flow piden solo esas, y
   al recogerlas de Flow ocupan su sitio. El mensaje pide adjuntar la ficha en Flow.
"""

import json
import re
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.providers.ai import ProviderError

STAGE = "consistency"  # se guarda como un resultado más del proyecto
REFERENCE_FILE = "referencia-protagonista.jpg"
BATCH = 4  # imágenes por consulta (más, y Gemini se fija menos en los detalles)
PARALLEL = 4  # consultas a la vez: de 10-15 minutos a 2-3 (cabe en el límite por minuto)
REDO = "rehacer"  # proveedor de las escenas pendientes de rehacer en Flow


def set_reference(project_folder: Path, image: Path, scene_number: int) -> dict:
    """Copia la imagen elegida como ficha del protagonista (y borra la revisión anterior)."""
    shutil.copyfile(image, project_folder / REFERENCE_FILE)
    return {"reference": REFERENCE_FILE, "from_scene": scene_number, "checked": {}}


def save_uploaded_reference(project_folder: Path, data: bytes) -> dict:
    """La ficha hecha aparte en Flow y subida desde el ordenador (antes de las escenas)."""
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        picture = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("no es una imagen válida") from exc
    picture.save(project_folder / REFERENCE_FILE, "JPEG", quality=95)
    return {"reference": REFERENCE_FILE, "from_scene": 0, "checked": {}}


def _fingerprint(data: bytes) -> list[int] | None:
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        small = Image.open(io.BytesIO(data)).convert("L").resize((16, 16))
    except (UnidentifiedImageError, OSError):
        return None
    pixels = list(small.tobytes())
    mean = sum(pixels) / len(pixels)
    return [p > mean for p in pixels]


def is_reference(data: bytes, reference: bytes, tolerance: int = 20) -> bool:
    """¿Es esta imagen de Flow la propia ficha? (está en el mismo proyecto de Flow y no debe
    acabar en una escena). Compara una huella de 16×16 píxeles."""
    a, b = _fingerprint(data), _fingerprint(reference)
    if a is None or b is None:
        return False
    return sum(x != y for x, y in zip(a, b, strict=True)) <= tolerance


HAIR = ("black", "brown", "blond", "white_or_grey", "outline_only", "none")
HAIR_ES = {
    "black": "pelo negro",
    "brown": "pelo castaño",
    "blond": "pelo rubio",
    "white_or_grey": "pelo blanco o gris",
    "outline_only": "pelo solo con el contorno",
    "none": "sin pelo",
}


def _prompt(hero: str, numbers: list[int]) -> str:
    listing = ", ".join(f"IMAGE {n + 1} = scene {num}" for n, num in enumerate(numbers))
    who = f" ({hero})" if hero else ""
    hair = " | ".join(HAIR)
    return (
        "You are checking a 2D stickman cartoon video for visual consistency. Look closely, "
        "like a strict art director.\n"
        f"The first picture is the REFERENCE of the MAIN CHARACTER{who}.\n"
        f"Then come the images to check: {listing}.\n"
        "Describe FACTS, do not judge similarity:\n"
        f"- reference_hair: the main character's hair in the reference, one of: {hair}. "
        "«outline_only» means the hair is just a line drawing filled with white or skin colour "
        "(it looks white or bald); «white_or_grey» means visibly white or grey hair.\n"
        "For each image: hero_visible (is the main character in it), hair (same options, for "
        "the main character), facial_hair (true/false, for the main character), white_frame "
        "(a white border or frame around the whole picture), other_style (realistic, 3D or "
        "photo instead of flat 2D cartoon).\n"
        'Answer only JSON: {"reference_hair": "black", "results": [{"image": 1, '
        '"hero_visible": true, "hair": "black", "facial_hair": true, "white_frame": false, '
        '"other_style": false}]}'
    )


def _verdict(item: dict, ref_hair: str, ref_beard: bool | None) -> dict:
    """Decide con los datos que vio Gemini (no con su opinión): más fiable."""
    reasons = []
    if item.get("white_frame"):
        reasons.append("marco blanco")
    if item.get("other_style"):
        reasons.append("otro estilo de dibujo")
    if item.get("hero_visible"):
        hair = str(item.get("hair") or "")
        if hair in HAIR and ref_hair in HAIR and hair != ref_hair and hair != "none":
            reasons.append(HAIR_ES[hair])
        if ref_beard and item.get("facial_hair") is False:
            reasons.append("sin barba")
    if reasons:
        return {"ok": False, "reason": ", ".join(reasons)}
    return {
        "ok": True,
        "reason": "igual que la ficha" if item.get("hero_visible") else "no aparece",
    }


def check_batch(ai, reference: bytes, hero: str, batch: list[tuple[int, bytes]]) -> dict:
    """{número de escena: {"ok", "reason"}} para un grupo de imágenes."""
    from google.genai import types

    numbers = [n for n, _ in batch]
    contents: list = [
        _prompt(hero, numbers),
        "REFERENCE",
        types.Part.from_bytes(data=reference, mime_type="image/jpeg"),
    ]
    for i, (_, data) in enumerate(batch, 1):
        contents += [f"IMAGE {i}", types.Part.from_bytes(data=data, mime_type="image/jpeg")]
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
    response = ai._generate(contents, config)
    try:
        data = json.loads(response.text or "{}")
    except ValueError as exc:
        raise ProviderError("Gemini respondió algo raro al revisar las imágenes.") from exc
    ref_hair = str(data.get("reference_hair") or "")
    results = [r for r in data.get("results", []) if isinstance(r, dict)]
    visible = [r for r in results if r.get("hero_visible")]
    # ¿Lleva barba el protagonista? Lo que diga la mayoría de las imágenes donde sale.
    ref_beard = (
        sum(bool(r.get("facial_hair")) for r in visible) > len(visible) / 2 if visible else None
    )
    found = {}
    for item in results:
        try:
            index = int(item["image"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= index < len(numbers):
            found[numbers[index]] = _verdict(item, ref_hair, ref_beard)
    return found


def appears(hero: str, scene: dict) -> bool:
    """¿Sale el protagonista en esta escena? (su nombre o apellido en la descripción)."""
    name = re.split(r"[:(,]", hero or "", maxsplit=1)[0].strip()
    words = [w for w in re.findall(r"[\w']+", name) if len(w) > 2 and w.lower() not in SKIP]
    text = " ".join(str(scene.get(k) or "") for k in ("image_prompt", "visual")).lower()
    return bool(words) and any(re.search(r"\b" + re.escape(w.lower()) + r"\b", text) for w in words)


SKIP = {"jr", "the", "del", "los", "las"}


def run_check(
    ai,
    project_folder: Path,
    scenes: list[dict],
    visuals: dict,
    previous: dict,
    hero: str,
    progress: Callable[[int, str], None],
) -> dict:
    """Revisa todas las imágenes del vídeo contra la ficha del protagonista."""
    from app.flow import thumbnail

    reference = project_folder / (previous or {}).get("reference", REFERENCE_FILE)
    if not reference.exists():
        raise ProviderError(
            "Primero elige la ficha del protagonista: en una escena donde salga bien, pulsa "
            "«Usar como ficha del protagonista»."
        )
    ref = thumbnail(reference.read_bytes(), 640)
    items = visuals.get("items", {})
    todo = []
    for scene in scenes:
        entry = items.get(scene["paragraph_id"]) or {}
        path = project_folder / "visuales" / entry.get("file", "")
        if entry.get("kind") == "image" and entry.get("file") and path.exists():
            todo.append((scene, entry["file"], path))
    todo = [t for t in todo if appears(hero, t[0])] or todo  # sin él no hay nada que mirar
    checked: dict = {}
    problems = []
    chunks = [todo[i : i + BATCH] for i in range(0, len(todo), BATCH)]

    def check(chunk):
        batch = [(scene["number"], thumbnail(path.read_bytes(), 512)) for scene, _, path in chunk]
        return check_batch(ai, ref, hero, batch)

    progress(5, f"Revisando {len(todo)} escenas donde sale el protagonista")
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:  # varias consultas a la vez
        futures = {pool.submit(check, chunk): chunk for chunk in chunks}
        for done, future in enumerate(as_completed(futures), 1):
            chunk = futures[future]
            label = f"{chunk[0][0]['number']}–{chunk[-1][0]['number']}"
            progress(5 + int(90 * done / len(chunks)), f"Revisadas las escenas {label}")
            try:
                verdicts = future.result()
            except ProviderError as exc:
                problems.append(f"Escenas {label}: {exc}")
                continue
            for scene, filename, _ in chunk:
                verdict = verdicts.get(scene["number"])
                if verdict is not None:
                    checked[scene["paragraph_id"]] = {
                        "number": scene["number"],
                        "file": filename,
                        **verdict,
                    }
    if todo and not checked:
        raise ProviderError("Gemini no pudo revisar ninguna imagen. Prueba otra vez en un rato.")
    progress(100, "Revisión terminada")
    bad = sum(1 for c in checked.values() if not c["ok"])
    return {
        **(previous or {}),
        "checked": checked,
        "summary": {"total": len(checked), "bad": bad},
        "problems": problems[:10],
    }


def current(consistency: dict | None, visuals: dict) -> dict:
    """La revisión que sigue valiendo para cada escena (si la imagen no cambió después):
    {paragraph_id: {"ok", "reason", "number"}}."""
    items = (visuals or {}).get("items", {})
    out = {}
    for pid, verdict in ((consistency or {}).get("checked") or {}).items():
        if (items.get(pid) or {}).get("file") == verdict.get("file"):
            out[pid] = verdict
    return out


def flagged(consistency: dict | None, visuals: dict) -> list[str]:
    """Escenas (paragraph_id) que la revisión marcó como distintas y aún no se rehicieron."""
    items = (visuals or {}).get("items", {})
    return [
        pid
        for pid, v in current(consistency, visuals).items()
        if not v["ok"] and (items.get(pid) or {}).get("provider") != REDO
    ]
