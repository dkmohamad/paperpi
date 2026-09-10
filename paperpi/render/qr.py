"""QR rendering for a small panel.

The modules are drawn as plain rectangles rather than going through qrcode's
own image factory, so the code lands on an exact pixel boundary. On a 240-pixel
panel an off-by-one scale is the difference between a code a phone reads
instantly and one it never resolves.
"""

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_M

from ..models import Rgb

__all__ = ["qr_image"]


def qr_image(data: str, size: int, dark: Rgb, light: Rgb):
    """Render `data` as a QR code no larger than `size` pixels square.

    Args:
        data: Text to encode. Shorter is better -- every extra character can
            push the code to a denser version that is harder to scan.
        size: Maximum width and height in pixels. The result is the largest
            whole-module square that fits.
        dark: Colour of the set modules.
        light: Colour of the quiet zone and unset modules.

    Returns:
        An RGB image of the code.

    Raises:
        ValueError: If `size` is too small to give each module a whole pixel.
    """
    code = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,
        border=2,
    )
    code.add_data(data)
    code.make(fit=True)
    matrix = code.get_matrix()

    modules = len(matrix)
    scale = size // modules
    if scale < 1:
        raise ValueError(f"{size}px is too small for a {modules}-module code")

    side = modules * scale
    image = Image.new("RGB", (side, side), light.as_tuple())
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(matrix):
        for x, is_dark in enumerate(row):
            if is_dark:
                draw.rectangle(
                    (
                        x * scale,
                        y * scale,
                        x * scale + scale - 1,
                        y * scale + scale - 1,
                    ),
                    fill=dark.as_tuple(),
                )
    return image
