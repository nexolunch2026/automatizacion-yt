from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import DB, CurrentUser
from app.providers.ai import GeminiProvider, ProviderError
from app.providers.search import WikipediaSearch
from app.settings_store import (
    api_key_hint,
    delete_api_key,
    get_api_key,
    get_setting,
    save_api_key,
    set_setting,
)
from app.templating import render

router = APIRouter(prefix="/configuracion")


def check_gemini_key(api_key: str) -> str:
    """Prueba la clave contra Google. Se reemplaza en los tests."""
    return GeminiProvider(api_key).check()


def run_diagnostics(api_key: str, preferred: str | None) -> tuple[list[dict], str | None]:
    """Prueba Gemini (texto y búsqueda de Google) y Wikipedia. Devuelve los resultados y el
    modelo que funcionó. Se reemplaza en los tests."""
    provider = GeminiProvider(api_key, preferred=preferred)
    results = provider.diagnose()
    try:
        WikipediaSearch(max_documents=1, max_chars=100).search(["Wikipedia"], "Español")
        results.append({"name": "Wikipedia (plan B)", "ok": True, "message": "Funciona"})
    except ProviderError as exc:
        results.append(
            {"name": "Wikipedia (plan B)", "ok": False, "message": str(exc), "detail": exc.detail}
        )
    return results, provider.last_model


def _page(request: Request, db: DB, status_code: int = 200, **ctx):
    return render(
        request,
        "settings.html",
        status_code=status_code,
        gemini_hint=api_key_hint(db, "gemini"),
        current_model=get_setting(db, "gemini_model"),
        **ctx,
    )


@router.get("")
def settings_page(request: Request, db: DB, user: CurrentUser):
    return _page(request, db, saved=request.query_params.get("guardado"))


@router.post("/gemini")
def save_gemini(request: Request, db: DB, user: CurrentUser, api_key: Annotated[str, Form()]):
    api_key = api_key.strip()
    if not api_key:
        return _page(request, db, 400, error="Pega la clave antes de guardar.")
    try:
        check_gemini_key(api_key)
    except ProviderError as exc:
        return _page(request, db, 400, error=f"No se pudo guardar: {exc}")
    save_api_key(db, "gemini", api_key)
    set_setting(db, "gemini_model", "")  # clave nueva: volver a buscar qué modelo funciona
    return RedirectResponse("/configuracion?guardado=1", status_code=303)


@router.post("/gemini/borrar")
def delete_gemini(db: DB, user: CurrentUser):
    delete_api_key(db, "gemini")
    return RedirectResponse("/configuracion", status_code=303)


@router.post("/gemini/probar")
def test_gemini(request: Request, db: DB, user: CurrentUser):
    api_key = get_api_key(db, "gemini")
    if not api_key:
        return _page(request, db, 400, error="Primero guarda una clave.")
    results, model = run_diagnostics(api_key, get_setting(db, "gemini_model"))
    if model:
        set_setting(db, "gemini_model", model)
    return _page(request, db, diagnostics=results, working_model=model)
