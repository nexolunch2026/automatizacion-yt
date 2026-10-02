from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
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

# Etapas del pipeline que se muestran en la barra de progreso.
STAGES = [
    "Investigación",
    "Estrategia",
    "Guion",
    "Storyboard",
    "Visuales",
    "Voz",
    "Edición",
    "Miniatura",
    "Control de calidad",
    "Publicación",
]

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

    @property
    def progress(self) -> int:
        """Porcentaje aproximado según el estado (se afinará con el pipeline real)."""
        return round(STATUSES.index(self.status) / (len(STATUSES) - 1) * 100)
