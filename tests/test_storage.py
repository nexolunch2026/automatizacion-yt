import sqlite3
import zipfile
from datetime import datetime, timedelta

from app import storage


def make_data(folder, text="MIS PROYECTOS"):
    folder.mkdir(parents=True)
    with sqlite3.connect(folder / "faceless.db") as conn:
        conn.execute("CREATE TABLE t (x TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (text,))
    (folder / "encryption.key").write_text("clave", encoding="utf-8")
    (folder / "proyectos" / "1" / "video").mkdir(parents=True)
    (folder / "proyectos" / "1" / "video" / "video.mp4").write_bytes(b"0" * 100)


def read(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT x FROM t").fetchone()[0]


def test_old_data_is_copied_to_the_fixed_folder(tmp_path):
    old, new = tmp_path / "programa" / "datos", tmp_path / "FacelessStudio" / "datos"
    make_data(old)
    assert storage.migrate_legacy(old, new)
    assert read(new / "faceless.db") == "MIS PROYECTOS"
    assert (new / "proyectos" / "1" / "video" / "video.mp4").exists()
    assert (new / "encryption.key").read_text(encoding="utf-8") == "clave"
    moved = tmp_path / "programa" / storage.MOVED_NAME
    assert not old.exists() and (moved / "LEEME - tus datos se movieron.txt").exists()
    assert str(new) in (moved / "LEEME - tus datos se movieron.txt").read_text(encoding="utf-8")


def test_migration_never_overwrites_existing_data(tmp_path):
    old, new = tmp_path / "viejo", tmp_path / "nuevo"
    make_data(old, "VIEJO")
    make_data(new, "NUEVO")
    assert not storage.migrate_legacy(old, new)
    assert read(new / "faceless.db") == "NUEVO" and old.exists()
    assert not storage.migrate_legacy(tmp_path / "no-existe", tmp_path / "otro")


def test_migration_replaces_an_empty_new_folder(tmp_path):
    old, new = tmp_path / "viejo", tmp_path / "nuevo"
    make_data(old)
    new.mkdir()  # creada vacía por una ejecución anterior
    assert storage.migrate_legacy(old, new)
    assert read(new / "faceless.db") == "MIS PROYECTOS"


def test_daily_backup_is_small_and_keeps_two_weeks(tmp_path):
    data = tmp_path / "datos"
    make_data(data)
    target = tmp_path / "nube"
    day = datetime(2026, 10, 1)
    for i in range(16):
        out = storage.daily_backup(data, day + timedelta(days=i), target)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "datos/faceless.db" in names and "datos/encryption.key" in names
        assert "COMO RESTAURAR.txt" in names
        assert not any("proyectos" in n for n in names)  # sin vídeos
        zf.extract("datos/faceless.db", tmp_path / "restaurado")
    assert read(tmp_path / "restaurado" / "datos" / "faceless.db") == "MIS PROYECTOS"
    assert len(list(target.glob("faceless-*.zip"))) == storage.DAILY_TO_KEEP


def test_backups_go_to_onedrive_when_available(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path))
    assert storage.backup_folder(tmp_path / "x" / "datos") == tmp_path / "FacelessStudio-copias"
    monkeypatch.delenv("OneDrive")
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    local = storage.backup_folder(tmp_path / "x" / "datos")
    assert local == tmp_path / "x" / "copias_de_seguridad" / "diarias"


def test_settings_page_shows_where_the_data_is(logged_in):
    page = logged_in.get("/configuracion").text
    assert "Dónde están tus datos" in page and "Copias de seguridad diarias" in page
