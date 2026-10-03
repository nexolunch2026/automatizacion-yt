from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import DATA_DIR, ROOT, VERSION

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["version"] = VERSION
templates.env.globals["root_dir"] = str(ROOT)
templates.env.globals["data_dir"] = str(DATA_DIR)
templates.env.globals["in_onedrive"] = "onedrive" in str(DATA_DIR).lower()


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("user", getattr(request.state, "user", None))
    return templates.TemplateResponse(request, name, context, status_code=status_code)
