"""Turning application state into pixels.

Nothing in here touches hardware. A screen is handed a `Canvas`, draws on it,
and the result is an ordinary image -- which is why the same screen code can
render to the panel over SPI, to a desktop window, or to a PNG in a test.
"""

from .canvas import Canvas, Fonts
from .qr import qr_image

__all__ = ["Canvas", "Fonts", "qr_image"]
