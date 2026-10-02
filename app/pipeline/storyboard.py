"""STORYBOARD ENGINE: convierte el guion en escenas con su plan visual.

Cada escena corresponde a un párrafo del guion (por su `id`). Se guarda el texto del
párrafo con el que se hizo la escena para saber cuáles quedan desactualizadas si el
guion cambia.
"""

from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import Project
from app.providers.ai import AIProvider

WORDS_PER_SECOND = 2.5  # unas 150 palabras por minuto


class VisualBible(BaseModel):
    style: str = Field(description="Estilo visual general (ej. documental oscuro, archivo)")
    palette: str = Field(description="Colores dominantes")
    era: str = Field(description="Época y lugar")
    lighting: str
    camera: str = Field(description="Tipo de planos y movimientos habituales")
    characters: list[str] = Field(description="Personas recurrentes y su aspecto, o []")
    locations: list[str] = Field(description="Lugares recurrentes, o []")


class SceneSpec(BaseModel):
    paragraph_id: str
    visual_type: str = Field(description="video, imagen, grafico o texto")
    visual: str = Field(description="Qué se ve en pantalla, en español")
    stock_query: str = Field(description="2–4 palabras en INGLÉS para buscar en bancos de vídeo")
    image_prompt: str = Field(description="Prompt en inglés para generar la imagen con IA")
    motion: str = Field(description="Movimiento de cámara: zoom lento, paneo, estático…")
    transition: str = Field(description="corte, fundido, deslizamiento…")
    on_screen_text: str = Field(description="Texto corto en pantalla (cifras, fechas) o ''")
    sfx: list[str] = Field(description="Efectos de sonido, o []")
    music_mood: str = Field(description="Ambiente musical: tensión, calma, épico…")


class Storyboard(BaseModel):
    visual_bible: VisualBible
    scenes: list[SceneSpec]


def estimate_seconds(text: str) -> float:
    return round(max(len(text.split()) / WORDS_PER_SECOND, 2.0), 1)


def paragraphs_of(script: dict) -> list[dict]:
    return [
        {**p, "section": s["kind"]} for s in script.get("sections", []) for p in s["paragraphs"]
    ]


def _prompt(project: Project, script: dict) -> str:
    lines = "\n".join(f"[{p['id']}] ({p['section']}) {p['text']}" for p in paragraphs_of(script))
    return f"""Eres director de vídeos faceless de YouTube. Crea el storyboard de este guion
(«{script["title"]}», tipo {project.video_type}).

1) Define una «biblia visual» coherente para todo el vídeo.
2) Para CADA párrafo (identificado entre corchetes) crea UNA escena con ese mismo
   paragraph_id, en el mismo orden. Respeta la biblia visual en todos los prompts.
   - Prefiere vídeo de archivo o imágenes reales para hechos; gráficos para cifras.
   - No muestres caras de personas reales inventadas como si fueran reales.
   - stock_query: palabras en inglés, concretas y visuales.
   - image_prompt: en inglés, describiendo estilo, encuadre e iluminación de la biblia.
     MUY IMPORTANTE: la imagen NO debe llevar texto, letras, números, rótulos, gráficos,
     infografías, líneas de tiempo, pantallas con datos ni logotipos legibles (la IA se
     inventa esos textos y cifras). Describe escenas, objetos, lugares y ambiente.
     Las cifras, fechas y nombres van en «on_screen_text», que el programa escribe
     encima con los datos reales.

GUION:
{lines}"""


def run_storyboard(
    project: Project, script: dict, ai: AIProvider, progress: Callable[[int, str], None]
) -> dict:
    progress(20, "Planificando escenas")
    board = ai.generate_json(_prompt(project, script), Storyboard)
    specs = {s.paragraph_id: s for s in board.scenes}

    scenes = []
    for number, paragraph in enumerate(paragraphs_of(script), 1):
        spec = specs.get(paragraph["id"])
        scene = {
            "number": number,
            "paragraph_id": paragraph["id"],
            "section": paragraph["section"],
            "narration": paragraph["text"],
            "seconds": estimate_seconds(paragraph["text"]),
        }
        if spec:
            scene.update(spec.model_dump(exclude={"paragraph_id"}))
        else:  # la IA se saltó este párrafo: escena básica para no perderlo
            scene.update(
                visual_type="imagen",
                visual="(pendiente de definir)",
                stock_query="",
                image_prompt="",
                motion="zoom lento",
                transition="corte",
                on_screen_text="",
                sfx=[],
                music_mood="",
                missing=True,
            )
        scenes.append(scene)
    progress(100, "Escenas listas")
    return {
        "visual_bible": board.visual_bible.model_dump(),
        "scenes": scenes,
        "total_seconds": round(sum(s["seconds"] for s in scenes), 1),
    }


def stale_scenes(storyboard: dict, script: dict) -> dict:
    """Compara las escenas con el guion actual.

    Devuelve los números de escena cuyo texto cambió o cuyo párrafo se borró, y los
    párrafos nuevos que todavía no tienen escena."""
    current = {p["id"]: p["text"] for p in paragraphs_of(script)}
    changed = [
        s["number"]
        for s in storyboard.get("scenes", [])
        if current.get(s["paragraph_id"]) != s["narration"]
    ]
    known = {s["paragraph_id"] for s in storyboard.get("scenes", [])}
    new = [pid for pid in current if pid not in known]
    return {"changed": changed, "new": new}
