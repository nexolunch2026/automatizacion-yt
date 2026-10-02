from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, web
from app.config import SECRET_KEY
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Faceless Studio", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="faceless_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(web.router)


@app.exception_handler(auth.LoginRequired)
def _login_required(*_):
    return RedirectResponse("/entrar", status_code=303)


@app.get("/salud")
def health() -> dict:
    return {"ok": True}
