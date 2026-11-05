"""Comprobaciones con servicios reales (se ejecuta en GitHub Actions, que tiene internet).

- Todas las voces de Microsoft del catálogo existen y graban audio de verdad.
- El actualizador descarga el repositorio público y lo reconoce.
"""

import sys
import tempfile
from pathlib import Path

from app import updater
from app.providers.voice import VOICES, MicrosoftVoices, wav_seconds


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no es UTF-8
    failures = []

    print("1-2) Voces de Microsoft del catálogo (grabación real)")
    from app.providers.ai import ProviderError

    microsoft = MicrosoftVoices()
    for voice in VOICES:
        try:
            audio = microsoft.synthesize(
                "Hola, esta es una prueba de la voz de Faceless Studio.", voice.id, "Normal"
            )
            seconds = wav_seconds(audio)
            print(f"   {voice.id}: {seconds} s de audio")
            if seconds < 1:
                failures.append(f"La voz {voice.id} generó un audio demasiado corto")
        except ProviderError as exc:
            failures.append(f"La voz {voice.id} falló: {exc} {exc.detail}")

    print("3) Actualizador (repositorio público)")
    with tempfile.TemporaryDirectory() as tmp:
        source = updater.extract(updater.download(), Path(tmp))
        version = updater.read_version((source / "app" / "config.py").read_text("utf-8"))
        print(f"   Versión publicada: {version}")

    print("4) Montaje de vídeo real con FFmpeg")
    with tempfile.TemporaryDirectory(prefix="prueba d'apostrofo ") as tmp:
        folder = Path(tmp)
        from PIL import Image

        from app.pipeline.render import render_video
        from app.providers.voice import join_wavs

        Image.new("RGB", (640, 360), (90, 40, 30)).save(folder / "foto.jpg")
        clips = [microsoft.synthesize(t, VOICES[0].id, "Normal") for t in ("Uno.", "Dos.")]
        (folder / "narracion.wav").write_bytes(join_wavs(clips))
        scenes = [
            {
                "number": 1,
                "paragraph_id": "a",
                "narration": "Uno.",
                "motion": "zoom lento",
                "transition": "fundido",
                "on_screen_text": "2001",
            },
            {
                "number": 2,
                "paragraph_id": "b",
                "narration": "Dos.",
                "motion": "",
                "transition": "corte",
                "on_screen_text": "63.000 MILLONES",
                "chart": {  # gráfico animado (dibujado con PIL y codificado por tubería)
                    "kind": "bars",
                    "title": "Cuota de mercado",
                    "unit": "%",
                    "points": [{"label": "2007", "value": 49.4}, {"label": "2013", "value": 3}],
                },
            },
        ]
        takes = {"a": wav_seconds(clips[0]), "b": wav_seconds(clips[1])}
        from app.pipeline.render import run_ffmpeg

        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=110:duration=4",
                "-ac",
                "2",
                str(folder / "musica.mp3"),
            ]
        )
        # Todo activado: subtítulos animados (libass), acabado de cine y música.
        out = render_video(
            scenes,
            {"a": {"path": folder / "foto.jpg", "kind": "image"}},
            takes,
            folder / "narracion.wav",
            folder / "video",
            "preview",
            False,
            lambda p, m: None,
            style={"subtitles": True, "film_look": True, "music_volume": "media"},
            music=folder / "musica.mp3",
        )
        size = (folder / "video" / out["file"].removeprefix("video/")).stat().st_size
        print(f"   {out['file']}: {out['seconds']} s, {size} bytes")
        if size < 1000:
            failures.append("El vídeo montado está vacío")

    from app.providers.ai import ProviderError

    print("6) Telegram responde (con un token falso debe decir que no es válido)")
    from app.telegram import TelegramAPI

    try:
        TelegramAPI("123456:token-falso").get_me()
        failures.append("Telegram aceptó un token falso")
    except ProviderError as exc:
        print(f"   {exc}")
        if "token" not in str(exc):
            failures.append(f"Telegram no respondió como se esperaba: {exc} {exc.detail}")

    print("7) Voz de JARVIS (voz neuronal de Microsoft + efecto)")
    from app import jarvis_voice

    with tempfile.TemporaryDirectory() as tmp:
        jarvis_voice.CACHE_DIR = Path(tmp)
        for voice in ("es-ES-AlvaroNeural", "es-CO-GonzaloNeural"):
            try:
                path = jarvis_voice.speak(
                    "Buenos días, señor. Todos los sistemas funcionan.", voice=voice
                )
                print(f"   {voice}: {path.stat().st_size} bytes")
            except ProviderError as exc:
                failures.append(f"La voz de JARVIS falló con {voice}: {exc} {exc.detail}")

    print("8) Información de JARVIS (servicios gratuitos; solo avisos)")
    from app import info, profile

    handle = profile.ORIGINAL["handle"]  # un canal real para comprobar la lectura

    class FakeDB:  # sin base de datos: valores por defecto
        def get(self, *args):
            return None

        def scalar(self, *args):
            return None

    db = FakeDB()
    news = info.news(db)
    print(f"   Noticias: {len(news)} -> {news[0]['title'] if news else 'AVISO: ninguna'}")
    radar = info.brand_radar(db)
    print(f"   Radar de marcas: {len(radar)} -> {radar[0]['title'] if radar else 'AVISO: ninguno'}")
    print(f"   Dólar: {info.dollar(db) or 'AVISO: sin datos'}")
    from app import references

    try:
        ref = references.channel("@MagnatesMedia", None)
        best = ref["videos"][0] if ref["videos"] else None
        print(
            f"   Canal de referencia @MagnatesMedia: {len(ref['videos'])} vídeos"
            + (f", el que más destaca: ×{best['ratio']} «{best['title']}»" if best else "")
        )
    except Exception as exc:  # noqa: BLE001 — solo aviso
        print(f"   AVISO referencias: {exc}")
    from app import demand

    found = demand.check("historia de Nokia")
    print(f"   Demanda en YouTube («historia de Nokia»): {found['level']} {found['searches']}")
    try:
        print(f"   Pronóstico Medellín: {info.fetch_forecast('Medellín')}")
    except Exception as exc:  # noqa: BLE001
        print(f"   AVISO pronóstico: {exc}")
    try:
        page = info._get("https://www.youtube.com/" + handle, hl="es").text
        print(f"   Página del canal: {info.parse_channel_page(page)}")
        import re as _re

        hints = _re.findall(r".{0,90}(?:suscriptor|subscriber).{0,40}", page)[:3]
        print(f"   Pistas de suscriptores en la página ({len(page)} letras): {hints}")
        if "consent.youtube.com" in page or "before you continue" in page.lower():
            print("   AVISO: YouTube mostró la página de consentimiento de cookies")
        channel = info.fetch_youtube_public(handle)
        print(
            f"   Canal: {channel['name']} · {channel['subscribers']} suscriptores · "
            f"{len(channel['latest'])} vídeos en el RSS"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   AVISO canal: {exc}")

    print("9) Script para buscar los datos (sintaxis de PowerShell)")
    if sys.platform == "win32":
        import subprocess

        script = Path(__file__).with_name("buscar_datos.ps1")
        check = (
            "$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
            f"'{script}', [ref]$null, [ref]$e) | Out-Null; $e.Count"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", check], capture_output=True, text=True
        ).stdout.strip()
        print(f"   errores de sintaxis: {out}")
        if out != "0":
            failures.append(f"buscar_datos.ps1 tiene errores de sintaxis: {out}")

    if failures:
        print("\nFALLOS:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
