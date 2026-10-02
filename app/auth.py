from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import MAX_USERS
from app.db import get_db
from app.models import User
from app.security import hash_password, verify_password
from app.templating import render

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]


class LoginRequired(Exception):
    """Se lanza cuando una página necesita sesión; main.py redirige a /entrar."""


def current_user(request: Request, db: DB) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise LoginRequired
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def _registration_open(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(User)) < MAX_USERS


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


@router.get("/entrar")
def login_page(request: Request, db: DB):
    return render(request, "login.html", registration_open=_registration_open(db))


@router.post("/entrar")
def login(
    request: Request,
    db: DB,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not verify_password(user.password_hash, password):
        return render(
            request,
            "login.html",
            status_code=400,
            error="Usuario o contraseña incorrectos.",
            registration_open=_registration_open(db),
        )
    request.session.clear()
    request.session["user_id"] = user.id
    return _redirect("/")


@router.post("/salir")
def logout(request: Request):
    request.session.clear()
    return _redirect("/entrar")


@router.get("/registro")
def register_page(request: Request, db: DB):
    if not _registration_open(db):
        return render(request, "register_closed.html", status_code=403)
    return render(request, "register.html")


@router.post("/registro")
def register(
    request: Request,
    db: DB,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
):
    if not _registration_open(db):
        return render(request, "register_closed.html", status_code=403)

    username = username.strip().lower()
    error = None
    if not (3 <= len(username) <= 50) or not username.isalnum():
        error = "El usuario debe tener entre 3 y 50 letras o números, sin espacios."
    elif len(password) < 8:
        error = "La contraseña debe tener al menos 8 caracteres."
    elif password != password_confirm:
        error = "Las contraseñas no coinciden."
    elif db.scalar(select(User).where(User.username == username)):
        error = "Ese usuario ya existe."
    if error:
        return render(request, "register.html", status_code=400, error=error, username=username)

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    return _redirect("/")
