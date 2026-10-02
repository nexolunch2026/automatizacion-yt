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


STOCK_PROVIDERS = {"pexels": "Pexels", "pixabay": "Pixabay"}


def check_stock_key(provider: str, api_key: str) -> None:
    """Hace una búsqueda de prueba. Se reemplaza en los tests."""
    from app.providers.stock import PexelsStock, PixabayStock

    stock = PexelsStock(api_key) if provider == "pexels" else PixabayStock(api_key)
    stock.search("city", "image", portrait=False, limit=3)


def _page(request: Request, db: DB, status_code: int = 200, **ctx):
    return render(
        request,
        "settings.html",
        status_code=status_code,
        gemini_hint=api_key_hint(db, "gemini"),
        current_model=get_setting(db, "gemini_model"),
        github_hint=api_key_hint(db, "github"),
        stock_hints={name: api_key_hint(db, name) for name in STOCK_PROVIDERS},
        **ctx,
    )


@router.get("")
def settings_page(request: Request, db: DB, user: CurrentUser):
    return _page(
        request,
        db,
        saved=request.query_params.get("guardado"),
        github_saved=request.query_params.get("github"),
        stock_saved=request.query_params.get("stock"),
    )


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


@router.post("/github")
def save_github(request: Request, db: DB, user: CurrentUser, token: Annotated[str, Form()]):
    token = token.strip()
    if not token:
        return _page(request, db, 400, github_error="Pega el token antes de guardar.")
    save_api_key(db, "github", token)
    return RedirectResponse("/configuracion?github=1", status_code=303)


@router.post("/github/borrar")
def delete_github(db: DB, user: CurrentUser):
    delete_api_key(db, "github")
    return RedirectResponse("/configuracion", status_code=303)


@router.post("/stock/{provider}")
def save_stock_key(
    request: Request, db: DB, user: CurrentUser, provider: str, api_key: Annotated[str, Form()]
):
    if provider not in STOCK_PROVIDERS:
        return RedirectResponse("/configuracion", status_code=303)
    api_key = api_key.strip()
    try:
        if not api_key:
            raise ProviderError("Pega la clave antes de guardar.")
        check_stock_key(provider, api_key)
    except ProviderError as exc:
        return _page(request, db, 400, stock_error={provider: str(exc)})
    save_api_key(db, provider, api_key)
    return RedirectResponse(f"/configuracion?stock={provider}#stock", status_code=303)


@router.post("/stock/{provider}/borrar")
def delete_stock_key(db: DB, user: CurrentUser, provider: str):
    if provider in STOCK_PROVIDERS:
        delete_api_key(db, provider)
    return RedirectResponse("/configuracion#stock", status_code=303)
