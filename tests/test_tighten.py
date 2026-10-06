import io
import math
import struct
import time
import wave

from app.providers.voice import tighten, wav_seconds

RATE = 22050


def wav(*pieces):
    """pieces: («tono» | «silencio», segundos)."""
    frames = b""
    for kind, seconds in pieces:
        n = int(RATE * seconds)
        if kind == "tono":
            frames += b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / RATE)))
                for i in range(n)
            )
        else:
            frames += b"\x00\x00" * n
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return out.getvalue()


def test_trims_edges_and_long_pauses():
    data = wav(
        ("silencio", 1.0), ("tono", 1.0), ("silencio", 1.2), ("tono", 1.0), ("silencio", 0.8)
    )
    tight = tighten(data)
    # 0,08 + 1 + 0,45 + 1 + 0,08 ≈ 2,6 s (antes 5 s)
    assert abs(wav_seconds(tight) - 2.61) < 0.08


def test_short_pauses_are_kept():
    data = wav(("tono", 1.0), ("silencio", 0.3), ("tono", 1.0))
    assert abs(wav_seconds(tighten(data)) - 2.3) < 0.05


def test_silence_or_odd_audio_is_left_alone():
    quiet = wav(("silencio", 1.0))
    assert tighten(quiet) == quiet
    assert tighten(b"no es un wav") == b"no es un wav"


def test_is_fast_enough():
    data = wav(("tono", 20.0), ("silencio", 2.0), ("tono", 20.0))
    start = time.time()
    tighten(data)
    assert time.time() - start < 2.0
