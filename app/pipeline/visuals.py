"""VISUAL ENGINE: busca y descarga un visual para cada escena en bancos gratuitos.

Orden de preferencia según el tipo de escena (vídeo o imagen) y los proveedores con
clave configurada. Si no hay clave o no aparece nada, la escena usa una tarjeta con texto
(se genera al montar el vídeo). Cada visual guarda autor, licencia y página de origen.
"""

from collections.abc import Callable
from pathlib import Path

from app.providers.ai import ProviderError
from app.providers.stock import StockItem, StockProvider, download

EXTENSIONS = {"video": ".mp4", "image": ".jpg"}


def _search_order(visual_type: str) -> list[str]:
    if visual_type in ("grafico", "gráfico", "texto"):
        return []
    return ["video", "image"] if visual_type == "video" else ["image", "video"]


def pick_item(
    scene: dict,
    providers: list[StockProvider],
    portrait: bool,
    used: set[str],
    skip: int = 0,
) -> StockItem | None:
    """Primer resultado no usado aún en otra escena. `skip` salta resultados (para
    «cambiar visual»)."""
    query = (scene.get("stock_query") or "").strip()
    if not query:
        return None
    candidates: list[StockItem] = []
    for kind in _search_order(scene.get("visual_type", "imagen")):
        for provider in providers:
            try:
                results = provider.search(query, kind, portrait)
            except ProviderError as exc:
                if not exc.transient:
                    raise
                continue
            if kind == "video":
                long_enough = [r for r in results if r.duration >= scene.get("seconds", 0) * 0.6]
                results = long_enough or results
            candidates += [r for r in results if f"{r.provider}:{r.id}" not in used]
        if len(candidates) > skip:
            return candidates[skip]
    return candidates[skip] if len(candidates) > skip else None


def run_visuals(
    scenes: list[dict],
    providers: list[StockProvider],
    portrait: bool,
    folder: Path,
    previous: dict | None,
    progress: Callable[[int, str], None],
    only: set[str] | None = None,
    skip: dict[str, int] | None = None,
    mode: str = "stock",
    images=None,
    visual_bible: dict | None = None,
) -> dict:
    """Asigna un visual a cada escena. Reutiliza los ya descargados de la vez anterior
    salvo para las escenas de `only` (las que se quieren cambiar).

    mode="stock": bancos de imágenes. mode="ai": imágenes generadas con IA (`images` es
    un `ImageChain`); sin `only`, genera las que aún no tienen imagen de IA."""
    folder.mkdir(parents=True, exist_ok=True)
    old = (previous or {}).get("items", {})
    items, used = {}, set()
    for entry in old.values():
        if entry.get("provider"):
            used.add(f"{entry['provider']}:{entry['id']}")

    errors = []
    for i, scene in enumerate(scenes):
        pid = scene["paragraph_id"]
        keep = old.get(pid)
        exists = keep and (keep["kind"] == "card" or (folder / keep.get("file", "")).exists())
        if mode == "ai":
            own = keep and (keep.get("ai") or keep.get("uploaded")) and exists
            wanted = pid in only if only is not None else not own
            if not wanted:
                if keep:
                    items[pid] = keep
                continue
            progress(
                round(5 + 90 * i / len(scenes)),
                f"Creando imagen con IA para la escena {i + 1} de {len(scenes)}",
            )
            try:
                items[pid] = _ai_image(scene, images, portrait, folder, visual_bible or {})
            except ProviderError as exc:
                if exc.transient and not items and i == 0:
                    raise  # ni siquiera la primera: que la tarea se reintente más tarde
                errors.append(f"Escena {scene['number']}: {exc}")
                if keep:
                    items[pid] = keep
                else:
                    items[pid] = {"kind": "card", "reason": "no se pudo generar"}
            continue
        changing = only is not None and pid in only
        if keep and not changing and exists:
            items[pid] = keep
            continue
        progress(
            round(5 + 90 * i / len(scenes)),
            f"Buscando visual para la escena {i + 1} de {len(scenes)}",
        )
        item = pick_item(scene, providers, portrait, used, (skip or {}).get(pid, 0))
        if item is None:
            items[pid] = {"kind": "card", "reason": "sin resultados" if providers else "sin clave"}
            continue
        filename = f"{scene['number']:03}-{item.provider}-{item.id}{EXTENSIONS[item.kind]}"
        download(item, folder / filename)
        poster = _poster(folder / filename) if item.kind == "video" else None
        used.add(f"{item.provider}:{item.id}")
        items[pid] = {
            "kind": item.kind,
            "file": filename,
            "provider": item.provider,
            "id": item.id,
            "author": item.author,
            "license": item.license,
            "page_url": item.page_url,
            "query": scene.get("stock_query", ""),
            "skip": (skip or {}).get(pid, 0),
            "poster": poster,
        }

    in_use = {e["file"] for e in items.values() if e.get("file")}
    in_use |= {e["poster"] for e in items.values() if e.get("poster")}
    for leftover in folder.iterdir():
        if leftover.is_file() and leftover.name not in in_use:
            leftover.unlink(missing_ok=True)
    progress(100, "Visuales listos")
    notes = list(getattr(images, "notes", []) or [])
    return {
        "items": items,
        "providers": [p.name for p in providers],
        "errors": errors[:10],
        "notes": notes,
    }


def image_prompt(scene: dict, visual_bible: dict) -> str:
    """Prompt de la escena con la biblia visual, para que todas se vean coherentes."""
    base = (scene.get("image_prompt") or scene.get("visual") or "").strip()
    style = ", ".join(
        v
        for v in (
            visual_bible.get("style"),
            visual_bible.get("palette"),
            visual_bible.get("lighting"),
            visual_bible.get("era"),
        )
        if v
    )
    return f"{base}. Style: {style}" if style else base


def _ai_image(scene: dict, images, portrait: bool, folder: Path, visual_bible: dict) -> dict:
    import random

    prompt = image_prompt(scene, visual_bible)
    if not prompt:
        raise ProviderError("Esta escena no tiene prompt de imagen.")
    seed = random.randint(1, 10_000_000)
    data, ext, provider = images.generate(prompt, portrait, seed)
    filename = f"{scene['number']:03}-ia-{seed}{ext}"
    (folder / filename).write_bytes(data)
    return {
        "kind": "image",
        "file": filename,
        "provider": provider.name,
        "id": str(seed),
        "author": "",
        "license": f"Imagen generada con IA ({provider.label})",
        "page_url": "",
        "query": prompt,
        "ai": True,
    }


def _poster(video: Path) -> str | None:
    """Foto fija del vídeo para mostrarla como miniatura en la página."""
    from app.pipeline.render import run_ffmpeg

    poster = video.with_suffix(".jpg")
    try:
        run_ffmpeg(
            ["-ss", "0.5", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2", str(poster)]
        )
    except RuntimeError:
        return None
    return poster.name if poster.exists() else None


def credits_text(visuals: dict) -> str:
    """Créditos para la descripción del vídeo (no obligatorios, pero recomendables)."""
    lines = []
    for entry in visuals.get("items", {}).values():
        if entry.get("provider") and not entry.get("ai"):
            name = "Pexels" if entry["provider"] == "pexels" else "Pixabay"
            lines.append(
                f"- {entry['author'] or 'Autor desconocido'} ({name}): {entry['page_url']}"
            )
    unique = list(dict.fromkeys(lines))
    return "Imágenes y vídeos:\n" + "\n".join(unique) if unique else ""
