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
) -> dict:
    """Asigna un visual a cada escena. Reutiliza los ya descargados de la vez anterior
    salvo para las escenas de `only` (las que se quieren cambiar)."""
    folder.mkdir(parents=True, exist_ok=True)
    old = (previous or {}).get("items", {})
    items, used = {}, set()
    for entry in old.values():
        if entry.get("provider"):
            used.add(f"{entry['provider']}:{entry['id']}")

    for i, scene in enumerate(scenes):
        pid = scene["paragraph_id"]
        keep = old.get(pid)
        changing = only is not None and pid in only
        if keep and not changing and (keep["kind"] == "card" or (folder / keep["file"]).exists()):
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
    return {"items": items, "providers": [p.name for p in providers]}


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
        if entry.get("provider"):
            name = "Pexels" if entry["provider"] == "pexels" else "Pixabay"
            lines.append(
                f"- {entry['author'] or 'Autor desconocido'} ({name}): {entry['page_url']}"
            )
    unique = list(dict.fromkeys(lines))
    return "Imágenes y vídeos:\n" + "\n".join(unique) if unique else ""
