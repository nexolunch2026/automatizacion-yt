from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Estados de un proyecto (sección 4 del prompt maestro), en orden.
STATUSES = [
    "Idea",
    "Investigación",
    "Guion",
    "Storyboard",
    "Producción",
    "Edición",
    "Revisión",
    "Listo",
    "Programado",
    "Publicado",
]

# Etapas del pipeline: clave interna → nombre visible, en orden.
STAGES = {
    "research": "Investigación",
    "strategy": "Estrategia",
    "script": "Guion",
    "storyboard": "Escenas",
    "visuals": "Visuales",
    "voice": "Voz",
    "edit": "Vídeo",
    "thumbnail": "Miniatura",
    "qc": "Control de calidad",
    "publish": "Publicación",
    "shorts": "Shorts",
}

DURATIONS = ["Short", "3–5 min", "5–10 min", "10–15 min", "15–30 min"]
LANGUAGES = ["Español", "Inglés"]
VIDEO_TYPES = [
    "Documental",
    "Historia",
    "Misterio",
    "Tecnología",
    "Negocios",
    "Finanzas",
    "Ciencia",
    "Curiosidades",
    "Noticias",
    "Educación",
    "Otro",
]
# Palabras aproximadas de narración según la duración (unas 150 palabras por minuto).
WORDS_BY_DURATION = {
    "Short": 140,
    "3–5 min": 600,
    "5–10 min": 1100,
    "10–15 min": 1900,
    "15–30 min": 3300,
}
SCRIPT_TONES = [
    "Documental",
    "Periodístico",
    "Misterioso",
    "Educativo",
    "Entretenido",
    "Cinematográfico",
    "Conversacional",
]
LEVELS = ["Bajo", "Medio", "Alto"]

AUTOMATION_MODES = {
    "manual": "Manual — tú controlas cada paso",
    "asistido": "Asistido — la IA propone y tú apruebas",
    "automatico": "Automático — la IA hace todo",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    niche: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(30), default="Español")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(Text)
    duration: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(30))
    video_type: Mapped[str] = mapped_column(String(30))
    automation_mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="Idea")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    channel: Mapped[Channel] = relationship(back_populates="projects")
    author: Mapped[User] = relationship()
    jobs: Mapped[list["Job"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    results: Mapped[list["StageResult"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def progress(self) -> int:
        """Porcentaje aproximado según el estado (se afinará con el pipeline real)."""
        return round(STATUSES.index(self.status) / (len(STATUSES) - 1) * 100)


class Setting(Base):
    """Preferencias y claves API (las claves se guardan cifradas)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Job(Base):
    """Una tarea en segundo plano (por ejemplo, investigar un proyecto)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    progress: Mapped[int] = mapped_column(default=0)
    message: Mapped[str] = mapped_column(String(200), default="En cola")
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    run_after: Mapped[datetime | None]
    params: Mapped[dict | None] = mapped_column(JSON)  # opciones elegidas (tono del guion…)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    notified: Mapped[bool | None]  # JARVIS ya avisó por Telegram de cómo terminó

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")


class StageResult(Base):
    """Lo que produce cada etapa de un proyecto (informe, guion, escenas…)."""

    __tablename__ = "stage_results"
    __table_args__ = (UniqueConstraint("project_id", "stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
