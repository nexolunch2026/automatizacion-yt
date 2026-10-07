import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.providers import piper_safe
from app.providers.ai import ProviderError


@pytest.fixture(autouse=True)
def fresh_checks(monkeypatch):
    monkeypatch.setattr(piper_safe, "_checked", {})


def make_data(folder):
    folder.mkdir(parents=True)
    (folder / "phontab").write_bytes(b"x" * 50)
    (folder / "es_dict").write_bytes(b"dic")
    return folder


def test_simple_paths():
    assert piper_safe.simple(piper_safe.Path("C:/Users/simon/FacelessStudio"))
    assert not piper_safe.simple(piper_safe.Path("C:/Users/Simón/programa"))
    assert not piper_safe.simple(piper_safe.Path("C:/Users/simon/OneDrive/Escritorio"))


def test_windows_copies_the_data_to_a_simple_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(piper_safe.sys, "platform", "win32")
    source = make_data(tmp_path / "Simón" / "espeak-ng-data")
    target = tmp_path / "simple" / "espeak-ng-data"
    assert piper_safe.data_dir(source, [target]) == target
    assert (target / "es_dict").read_bytes() == b"dic"
    assert piper_safe.data_dir(source, [target]) == target  # ya copiada: no se repite


def test_simple_or_other_systems_keep_the_original(tmp_path, monkeypatch):
    source = make_data(tmp_path / "Simón" / "espeak-ng-data")
    monkeypatch.setattr(piper_safe.sys, "platform", "linux")
    assert piper_safe.data_dir(source, [tmp_path / "x"]) == source
    monkeypatch.setattr(piper_safe.sys, "platform", "win32")
    plain = make_data(tmp_path / "plain" / "espeak-ng-data")
    assert piper_safe.data_dir(plain, [tmp_path / "x"]) == plain


def test_a_crashing_espeak_only_fails_the_voice(tmp_path):
    calls = []

    def crash(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1)

    with pytest.raises(ProviderError, match="no funciona en este ordenador"):
        piper_safe.check(tmp_path, run=crash)
    with pytest.raises(ProviderError):
        piper_safe.check(tmp_path, run=crash)
    assert len(calls) == 1 and calls[0][0] == sys.executable


def test_a_working_espeak_is_checked_once(tmp_path):
    calls = []

    def ok(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    piper_safe.check(tmp_path, run=ok)
    piper_safe.check(tmp_path, run=ok)
    assert len(calls) == 1


def test_a_hanging_check_counts_as_failure(tmp_path):
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 120)

    with pytest.raises(ProviderError):
        piper_safe.check(tmp_path, run=hang)


def test_the_real_check_runs_espeak(tmp_path):
    pytest.importorskip("piper")
    from piper.phonemize_espeak import ESPEAK_DATA_DIR

    piper_safe.check(ESPEAK_DATA_DIR)  # con los datos buenos funciona
    with pytest.raises(ProviderError):
        piper_safe.check(tmp_path / "no-existe")  # sin datos, falla sin cerrar las pruebas


def test_a_slow_first_check_is_retried_next_time(tmp_path):
    calls = []

    def run(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:  # el antivirus tarda la primera vez
            raise subprocess.TimeoutExpired(args[0], 120)
        return SimpleNamespace(returncode=0, stderr="")

    with pytest.raises(ProviderError, match="tardó"):
        piper_safe.check(tmp_path, run=run)
    piper_safe.check(tmp_path, run=run)  # la segunda vez funciona
    assert len(calls) == 2
