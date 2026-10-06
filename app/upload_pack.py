"""PAQUETE DE SUBIDA: todo lo que hace falta para subir un vídeo, en un solo .zip.

Vídeo (el final si existe; si no, la vista previa), subtítulos, miniatura elegida, un texto
con título, descripción, etiquetas y comentario fijado listos para pegar, y los Shorts con
sus portadas y textos. Se guarda dentro de la carpeta del proyecto y se rehace cada vez.
"""

import re
import unicodedata
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app import jobs
from app.media import project_dir
from app.models import Project

STEPS = """CÓMO SUBIRLO A YOUTUBE
1. YouTube Studio → Crear → Subir vídeos → elige «video.mp4».
2. Pega el título y la descripción de «textos.txt».
3. Miniatura: sube «miniatura.jpg».
4. Subtítulos: sube «subtitulos.srt».
5. «Contenido alterado o sintético»: marca «Sí» solo si alguna imagen de IA parece real.
6. Pega las etiquetas y, al publicar, escribe y fija el comentario.
7. Shorts: súbelos en días distintos, con su texto, y elige el documental como
   «Vídeo relacionado».
"""


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(ch for ch in plain if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:50] or "video"


def texts(project: Project, seo: dict, script: dict) -> str:
    titles = seo.get("titles") or [script.get("title") or project.title]
    parts = ["TÍTULO", titles[0]]
    if len(titles) > 1:
        parts += ["", "OTROS TÍTULOS (para «Probar y comparar»)", *titles[1:]]
    parts += ["", "DESCRIPCIÓN", seo.get("description", "")]
    if seo.get("tags"):
        parts += ["", "ETIQUETAS", ", ".join(seo["tags"])]
    if seo.get("pinned_comment"):
        parts += ["", "COMENTARIO FIJADO", seo["pinned_comment"]]
    if seo.get("category"):
        parts += ["", "CATEGORÍA", seo["category"]]
    return "\n".join(parts).strip() + "\n"


def build(db: Session, project: Project) -> Path:
    """Crea el .zip y devuelve su ruta. Lanza ValueError si aún no hay vídeo montado."""
    from app.pipeline.monetization import last_render

    folder = project_dir(project.id)
    render = last_render({"edit": jobs.get_result(db, project.id, "edit") or {}})
    video = folder / render["file"] if render.get("file") else None
    if video is None or not video.exists():
        raise ValueError("Primero hay que montar el vídeo.")
    seo = jobs.get_result(db, project.id, "publish") or {}
    script = jobs.get_result(db, project.id, "script") or {}
    out = folder / "paquete" / f"subida-{slug(project.title)}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    # Sin comprimir: el vídeo y las imágenes ya lo están, y así se crea al momento.
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as pack:
        pack.write(video, "video.mp4")
        srt = folder / "video" / "subtitulos.srt"
        if srt.exists():
            pack.write(srt, "subtitulos.srt")
        thumb = jobs.get_result(db, project.id, "thumbnail") or {}
        variants = thumb.get("variants") or []
        chosen = thumb.get("selected")
        if variants:
            index = chosen if isinstance(chosen, int) and 0 <= chosen < len(variants) else 0
            image = folder / "miniaturas" / variants[index]["file"]
            if image.exists():
                pack.write(image, "miniatura.jpg")
        pack.writestr("textos.txt", texts(project, seo, script))
        credits = folder / "video" / "creditos.txt"
        if credits.exists() and credits.read_text(encoding="utf-8").strip():
            pack.write(credits, "creditos.txt")
        shorts = (jobs.get_result(db, project.id, "shorts") or {}).get("shorts", [])
        for n, short in enumerate(shorts, 1):
            for key, name in (
                ("file", f"shorts/short-{n}.mp4"),
                ("cover", f"shorts/short-{n}-portada.jpg"),
            ):
                path = folder / short[key] if short.get(key) else None
                if path is not None and path.exists():
                    pack.write(path, name)
            title, description = short.get("title", ""), short.get("description", "")
            pack.writestr(
                f"shorts/short-{n}.txt", f"TÍTULO\n{title}\n\nDESCRIPCIÓN\n{description}\n"
            )
        pack.writestr("LEEME.txt", STEPS)
    tmp.replace(out)
    return out
