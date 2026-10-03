from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import DATA_DIR, ROOT, VERSION
from app.storage import home_dir

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["version"] = VERSION
templates.env.globals["root_dir"] = str(ROOT)
templates.env.globals["data_dir"] = str(DATA_DIR)
templates.env.globals["in_onedrive"] = "onedrive" in str(DATA_DIR).lower()
# El sitio fijo del programa (lo crea scripts/instalar.ps1, al lado de los datos).
templates.env.globals["program_in_place"] = ROOT == home_dir() / "programa"
templates.env.globals["installer_command"] = (
    'powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/'
    'nexolunch2026/automatizacion-yt/claude/hola-5p4ttp/scripts/instalar.ps1 | iex"'
)


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("user", getattr(request.state, "user", None))
    return templates.TemplateResponse(request, name, context, status_code=status_code)
