"""Prueba del instalador de Windows (scripts/instalar.ps1) con un usuario de mentira.

Se ejecuta con PowerShell si está instalado (en Windows siempre lo está, también en la
integración continua). Comprueba que no se pierde nada: los datos se copian al sitio fijo
y las copias viejas se mueven, nunca se borran."""

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "instalar.ps1"
SHELL = os.environ.get("PWSH") or shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not SHELL, reason="PowerShell no está instalado")


def fake_program(folder: Path, version: str, with_data: bool = False) -> Path:
    (folder / "app").mkdir(parents=True)
    (folder / "app" / "config.py").write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    for name in ("Iniciar.bat", "JARVIS.bat", "Actualizar.bat"):
        (folder / name).write_text("@echo off\n", encoding="utf-8")
    if with_data:
        (folder / "datos").mkdir()
        (folder / "datos" / "faceless.db").write_bytes(b"mis proyectos")
    return folder


def release_zip(path: Path, version: str, workdir: Path) -> Path:
    source = fake_program(workdir / "fuente" / "automatizacion-yt-rama", version)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for file in source.rglob("*"):
            zf.write(file, file.relative_to(source.parent))
    return path


def run(script: str) -> dict:
    command = f". '{SCRIPT}'\n{script}"
    env = {**os.environ, "FACELESS_INSTALL_TEST": "1"}
    out = subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_installs_in_one_place_and_tidies_old_copies(tmp_path):
    home = tmp_path / "usuario"
    old = fake_program(home / "Desktop" / "automatizacion-yt viejo", "0.3.0", with_data=True)
    fake_program(home / "OneDrive" / "Escritorio" / "automatizacion-yt-0.18", "0.18.0")
    fake_program(home / "AppData" / "algo" / "no-tocar", "0.1.0")  # AppData no se mira
    zip_path = release_zip(
        home / "Downloads" / "automatizacion-yt-claude-hola.zip", "0.23.0", tmp_path
    )
    startup = tmp_path / "startup"
    startup.mkdir()
    (startup / "JARVIS Faceless Studio.bat").write_text(f'start "" /min "{old}"\n')
    base = home / "FacelessStudio"
    program, data, old_dir = base / "programa", base / "datos", base / "copias_viejas"

    result = run(
        f"""
$copies = @(Find-FsCopies '{home}' '{base}')
$zips = @(Find-FsZips '{home}')
$from = Import-FsLegacyData $copies '{data}'
$version = Install-FsProgram '{zip_path}' '{program}'
$items = @($copies | ForEach-Object {{ $_.Folder }}) + @($zips | ForEach-Object {{ $_.FullName }})
$failed = @(Move-FsToOld $items '{old_dir}')
$startup = Repair-FsStartup '{startup}' '{program}'
@{{
  copies = @($copies | ForEach-Object {{ $_.Version.ToString() }})
  zips = $zips.Count; from = $from; version = $version.ToString()
  failed = $failed.Count; startup = $startup
}} | ConvertTo-Json -Compress
"""
    )
    assert result["copies"] == ["0.18.0", "0.3.0"]  # la más nueva primero, sin AppData
    assert result["zips"] == 1 and result["failed"] == 0 and result["startup"] is True
    assert result["version"] == "0.23.0"
    assert result["from"].endswith("datos")

    # El programa nuevo está en un único sitio y los datos en el suyo.
    assert 'VERSION = "0.23.0"' in (program / "app" / "config.py").read_text()
    assert (data / "faceless.db").read_bytes() == b"mis proyectos"
    # Nada se ha borrado: las copias viejas y el zip están en copias_viejas.
    moved = sorted(p.name for p in old_dir.iterdir())
    assert moved == [
        "automatizacion-yt viejo",
        "automatizacion-yt-0.18",
        "automatizacion-yt-claude-hola.zip",
    ]
    assert (old_dir / "automatizacion-yt viejo" / "datos" / "faceless.db").exists()
    assert not (home / "Desktop" / "automatizacion-yt viejo").exists()
    assert "programa" in (startup / "JARVIS Faceless Studio.bat").read_text()


def test_reinstall_keeps_python_and_existing_data(tmp_path):
    home = tmp_path / "usuario"
    base = home / "FacelessStudio"
    program, data = base / "programa", base / "datos"
    data.mkdir(parents=True)
    (data / "faceless.db").write_bytes(b"datos buenos")
    fake_program(home / "Desktop" / "copia", "0.10.0", with_data=True)  # datos viejos
    (program / ".venv").mkdir(parents=True)
    (program / ".venv" / "python.txt").write_text("no borrar")
    zip_path = release_zip(tmp_path / "descarga.zip", "0.23.0", tmp_path)

    result = run(
        f"""
$copies = @(Find-FsCopies '{home}' '{base}')
$from = Import-FsLegacyData $copies '{data}'
$version = Install-FsProgram '{zip_path}' '{program}'
$out = @{{ copies = $copies.Count; from = $from; version = $version.ToString() }}
$out | ConvertTo-Json -Compress
"""
    )
    assert result == {"copies": 1, "from": None, "version": "0.23.0"}
    assert (data / "faceless.db").read_bytes() == b"datos buenos"  # nunca se pisan
    assert (program / ".venv" / "python.txt").read_text() == "no borrar"


def test_moving_never_overwrites(tmp_path):
    old_dir = tmp_path / "copias_viejas"
    (old_dir / "copia").mkdir(parents=True)
    second = tmp_path / "otra" / "copia"
    second.mkdir(parents=True)
    (second / "x.txt").write_text("2")
    result = run(
        f"""
$failed = @(Move-FsToOld @('{second}') '{old_dir}')
@{{ failed = $failed.Count }} | ConvertTo-Json -Compress
"""
    )
    assert result["failed"] == 0
    assert (old_dir / "copia (2)" / "x.txt").read_text() == "2"


def test_script_is_plain_ascii():
    text = SCRIPT.read_text(encoding="utf-8")
    assert all(ord(ch) < 128 for ch in text)  # la consola de Windows no lía las tildes
    assert "claude/hola-5p4ttp" in text


def test_settings_explain_how_to_tidy_up(logged_in):
    page = logged_in.get("/configuracion").text
    assert "Windows + R" in page and "scripts/instalar.ps1 | iex" in page
