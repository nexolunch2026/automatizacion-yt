from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import analytics_web, auth, jarvis_web, learning_web, settings_web, stages_web, web
from app.config import SECRET_KEY, WORKER_ENABLED
from app.db import init_db
from app.jobs import Worker
from app.telegram import TelegramBot


def _migrate_profile() -> None:
    from app import profile
    from app.db import SessionLocal

    with SessionLocal() as db:
        profile.migrate(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _migrate_profile()
    threads = [Worker(), TelegramBot()] if WORKER_ENABLED else []
    for thread in threads:
        thread.start()
    yield
    for thread in threads:
        thread.stop()


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
app.include_router(settings_web.router)
app.include_router(stages_web.router)
app.include_router(jarvis_web.router)
app.include_router(analytics_web.router)
app.include_router(learning_web.router)


@app.exception_handler(auth.LoginRequired)
def _login_required(*_):
    return RedirectResponse("/entrar", status_code=303)


@app.get("/salud")
def health() -> dict:
    return {"ok": True}
