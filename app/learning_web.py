"""Página «Aprender»: pega un vídeo de YouTube y Gemini saca lo útil para el canal."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import jobs, learning
from app.auth import DB, CurrentUser
from app.providers.ai import ProviderError
from app.settings_store import api_key_hint
from app.templating import render

router = APIRouter()


def _page(request: Request, db: DB, status_code: int = 200, **ctx):
    return render(
        request,
        "learning.html",
        status_code=status_code,
        lessons=learning.lessons(db),
        has_gemini=api_key_hint(db, "gemini") is not None,
        **ctx,
    )


def watch_with_ai(db, url: str) -> dict:
    """Llama a Gemini para ver el vídeo. Se reemplaza en las pruebas."""
    ai = jobs.get_ai_provider(db)
    item = learning.learn(db, url, ai)
    jobs.remember_working_model(db, ai)
    return item


@router.get("/aprender")
def learning_page(request: Request, db: DB, user: CurrentUser):
    return _page(request, db)


@router.post("/aprender")
def learn_video(request: Request, db: DB, user: CurrentUser, url: Annotated[str, Form()]):
    link = learning.find_link(url)
    if link is None:
        return _page(
            request,
            db,
            status_code=400,
            error="Eso no parece un enlace de YouTube. Copia el enlace del vídeo "
            "(Compartir → Copiar).",
            url=url,
        )
    try:
        item = watch_with_ai(db, link)
    except ProviderError as exc:
        return _page(request, db, status_code=400, error=f"No se pudo ver el vídeo: {exc}", url=url)
    return RedirectResponse(f"/aprender#l-{item['id']}", status_code=303)


@router.post("/aprender/{lesson_id}/aplicar")
def toggle_lesson(db: DB, user: CurrentUser, lesson_id: str):
    learning.toggle_apply(db, lesson_id)
    return RedirectResponse(f"/aprender#l-{lesson_id}", status_code=303)


@router.post("/aprender/{lesson_id}/borrar")
def delete_lesson(db: DB, user: CurrentUser, lesson_id: str):
    learning.delete(db, lesson_id)
    return RedirectResponse("/aprender", status_code=303)
