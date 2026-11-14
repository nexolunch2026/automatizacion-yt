"""Revisión de salud del 14/11/2026: el filtro de imágenes repetidas de Flow tiraba
imágenes nuevas porque todos los monigotes sobre blanco «se parecían» en 8x8."""

import io

from PIL import Image, ImageDraw

from app.stages_web import _fingerprint, _seen


def stickman(x, y, color="black"):
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((x - 30, y - 30, x + 30, y + 30), outline=color, width=6)
    draw.line((x, y + 30, x, y + 160), fill=color, width=6)
    draw.line((x - 60, y + 80, x + 60, y + 80), fill=color, width=6)
    draw.line((x, y + 160, x - 50, y + 260), fill=color, width=6)
    draw.line((x, y + 160, x + 50, y + 260), fill=color, width=6)
    return image


def save(image, kind="PNG", size=None, quality=70):
    if size:
        image = image.resize(size)
    out = io.BytesIO()
    image.save(out, kind, **({"quality": quality} if kind == "JPEG" else {}))
    return out.getvalue()


def test_different_stickmen_are_not_repeats():
    first = _fingerprint(save(stickman(300, 200)))
    assert not _seen(_fingerprint(save(stickman(800, 300))), [first])  # otro sitio
    assert not _seen(_fingerprint(save(stickman(500, 100, "blue"))), [first])  # otro color


def test_same_image_saved_again_is_a_repeat():
    image = stickman(300, 200)
    first = _fingerprint(save(image))
    assert _seen(_fingerprint(save(image, "JPEG")), [first])
    assert _seen(_fingerprint(save(image, "JPEG", (640, 360), 60)), [first])
    assert not _seen([], [first]) and not _seen(first, [[]])
