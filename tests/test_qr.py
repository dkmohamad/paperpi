"""The QR renderer, checked against the matrix it is meant to reproduce."""

import pytest
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from paperpi.models import Rgb
from paperpi.render.qr import qr_image

_DARK = Rgb(0, 0, 0)
_LIGHT = Rgb(255, 255, 255)


def test_qr_image_should_reproduce_every_module_of_the_encoded_matrix():
    """Sample the rendered image at each module's centre and compare.

    The encoding is the library's job; the rendering is ours, and this is where
    an off-by-one scale, a swapped colour or a lost quiet zone would appear. A
    QR that is wrong by one module is one a phone silently never resolves, so
    eyeballing the image is not enough.
    """
    url = "http://192.168.1.246:8080/s/a1b2c3d4"
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=2)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()

    image = qr_image(url, 116, _DARK, _LIGHT)
    scale = image.width // len(matrix)

    for y, row in enumerate(matrix):
        for x, expected_dark in enumerate(row):
            centre = (x * scale + scale // 2, y * scale + scale // 2)
            pixel = image.getpixel(centre)
            actual_dark = pixel == _DARK.as_tuple()
            assert actual_dark is expected_dark, f"module {x},{y} differs"


def test_qr_image_should_fit_within_the_requested_size():
    """The code must not overflow the box the Done screen reserves for it."""
    image = qr_image("http://192.168.1.246:8080/s/a1b2c3d4", 116, _DARK, _LIGHT)
    assert image.width <= 116
    assert image.height <= 116
    assert image.width == image.height


def test_qr_image_should_refuse_a_size_too_small_for_whole_modules():
    """Below one pixel per module the code is unscannable, so it raises.

    Silently rounding to zero would produce a blank square that looks like a
    rendering bug rather than a size mistake.
    """
    with pytest.raises(ValueError, match="too small"):
        qr_image("http://192.168.1.246:8080/s/a1b2c3d4", 8, _DARK, _LIGHT)
