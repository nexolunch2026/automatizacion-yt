from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("user", getattr(request.state, "user", None))
    return templates.TemplateResponse(request, name, context, status_code=status_code)
