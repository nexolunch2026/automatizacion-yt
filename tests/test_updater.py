import io
import zipfile

import pytest

from app import updater


def make_zip(files: dict[str, str], top="automatizacion-yt-claude-hola-5p4ttp") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"{top}/{name}", content)
    return buffer.getvalue()


NEW_RELEASE = {
    "Iniciar.bat": "nuevo iniciar",
    "Actualizar.bat": "nuevo actualizar",
    "app/config.py": 'VERSION = "9.9"\n',
    "app/nuevo.py": "print('nuevo')",
    "datos/faceless.db": "NO DEBE COPIARSE",
}


@pytest.fixture
def install_dir(tmp_path):
    root = tmp_path / "programa"
    (root / "app").mkdir(parents=True)
    (root / "app" / "config.py").write_text('VERSION = "0.1"\n', encoding="utf-8")
    (root / "Iniciar.bat").write_text("viejo", encoding="utf-8")
    data = root / "datos"
    data.mkdir()
    (data / "faceless.db").write_text("MIS PROYECTOS", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "marker").write_text("entorno", encoding="utf-8")
    return root


def test_update_replaces_code_and_keeps_data(install_dir):
    version = updater.update(
        root=install_dir, data_dir=install_dir / "datos", fetch=lambda: make_zip(NEW_RELEASE)
    )
    assert version == "9.9"
    assert (install_dir / "Iniciar.bat").read_text(encoding="utf-8") == "nuevo iniciar"
    assert (install_dir / "app" / "nuevo.py").exists()
    # Los datos y el entorno no se tocan…
    assert (install_dir / "datos" / "faceless.db").read_text(encoding="utf-8") == "MIS PROYECTOS"
    assert (install_dir / ".venv" / "marker").exists()
    # …y además se guarda una copia de seguridad.
    backups = list((install_dir / "copias_de_seguridad").glob("datos-*"))
    assert len(backups) == 1
    assert (backups[0] / "faceless.db").read_text(encoding="utf-8") == "MIS PROYECTOS"


def test_old_backups_are_pruned(install_dir):
    backups = install_dir / "copias_de_seguridad"
    for i in range(7):
        (backups / f"datos-2026010{i}-000000").mkdir(parents=True)
    updater.backup_data(install_dir, install_dir / "datos")
    assert len(list(backups.glob("datos-*"))) == updater.BACKUPS_TO_KEEP


def test_broken_download_changes_nothing(install_dir):
    with pytest.raises(updater.UpdateError):
        updater.update(root=install_dir, data_dir=install_dir / "datos", fetch=lambda: b"basura")
    assert (install_dir / "Iniciar.bat").read_text(encoding="utf-8") == "viejo"


def test_zip_without_program_is_rejected(install_dir):
    with pytest.raises(updater.UpdateError):
        updater.update(
            root=install_dir,
            data_dir=install_dir / "datos",
            fetch=lambda: make_zip({"README.md": "hola"}),
        )


def test_read_version():
    assert updater.read_version('X = 1\nVERSION = "0.3.4"\n') == "0.3.4"
    assert updater.read_version("nada") == "?"


def transport(status, seen):
    import httpx

    def handler(request):
        seen.append(request)
        return httpx.Response(status, content=b"zip-bytes")

    return httpx.MockTransport(handler)


def test_download_public_without_token():
    seen = []
    assert updater.download(None, transport(200, seen)) == b"zip-bytes"
    assert str(seen[0].url) == updater.PUBLIC_URL
    assert "Authorization" not in seen[0].headers


def test_download_private_repo_needs_token():
    with pytest.raises(updater.UpdateError) as info:
        updater.download(None, transport(404, []))
    assert "privado" in str(info.value)


def test_download_with_token_uses_api():
    seen = []
    updater.download("github_pat_abc", transport(200, seen))
    assert str(seen[0].url) == updater.API_URL
    assert seen[0].headers["Authorization"] == "Bearer github_pat_abc"


def test_download_with_rejected_token():
    with pytest.raises(updater.UpdateError) as info:
        updater.download("github_pat_malo", transport(401, []))
    assert "rechazó el token" in str(info.value)
