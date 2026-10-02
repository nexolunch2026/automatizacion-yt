"""CONTENT STRATEGY ENGINE: propone enfoques, títulos y miniaturas a partir del informe."""

from collections.abc import Callable

from pydantic import BaseModel, Field

from app.models import Project
from app.pipeline.context import research_summary
from app.providers.ai import AIProvider


class TitleOption(BaseModel):
    title: str
    style: str = Field(
        description="curiosidad, misterio, conflicto, historia, pregunta o transformación"
    )
    reason: str = Field(description="Por qué podría funcionar, sin inventar métricas")


class Thumbnail(BaseModel):
    concept: str
    text: str = Field(description="Texto corto en la miniatura (máx. 4 palabras)")
    composition: str = Field(description="Sujeto, fondo y contraste")


class Concept(BaseModel):
    angle: str = Field(description="Nombre corto del enfoque")
    summary: str
    audience: str = Field(description="A quién va dirigido")
    promise: str = Field(description="Qué se lleva el espectador al terminar")
    hook: str = Field(description="Primera frase del vídeo para enganchar")
    titles: list[TitleOption]
    thumbnail: Thumbnail


class Strategy(BaseModel):
    concepts: list[Concept]


def _prompt(project: Project, research: dict) -> str:
    return f"""Eres estratega de contenido de YouTube. Propón 3 enfoques DISTINTOS para un
vídeo de tipo «{project.video_type}», duración «{project.duration}», en {project.language}.

Idea del creador: {project.topic}

Para cada enfoque da: nombre, resumen, audiencia, promesa al espectador, una frase de
gancho para los primeros segundos, 3 títulos (de estilos distintos: curiosidad,
misterio, conflicto, historia, pregunta o transformación, con la razón de cada uno) y un
concepto de miniatura.

Reglas: basa todo en la investigación; los títulos deben ser atractivos pero honestos
(nada que el vídeo no cumpla); no inventes cifras de CTR ni de visitas.

INVESTIGACIÓN:
{research_summary(research)}"""


def run_strategy(
    project: Project, research: dict, ai: AIProvider, progress: Callable[[int, str], None]
) -> dict:
    progress(20, "Pensando enfoques y títulos")
    strategy = ai.generate_json(_prompt(project, research), Strategy)
    progress(100, "Propuestas listas")
    return {"concepts": [c.model_dump() for c in strategy.concepts[:3]], "selected": None}
