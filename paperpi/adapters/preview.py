"""A desktop stand-in for the panel and its buttons.

Renders the identical frames the Pi shows, in a window, with the four buttons
mapped to the A/B/X/Y keys. It exists because the interesting half of this
application -- layout, wording, state transitions -- is pure computation, and
waiting on an rsync and a service restart to see a font change is a poor way to
spend an afternoon.

It is a stand-in, not a simulation. Colours on a backlit 2-inch panel are not
the colours on a desktop monitor, so legibility still wants checking on the
real glass before anything is called finished.
"""

from collections.abc import Sequence
from typing import Any

from PIL.Image import Image

from .. import config
from ..models import Button, Rgb

__all__ = ["PreviewDevice"]

_LED_STRIP_HEIGHT = 26

# The panel is 320x240. At 1:1 on a desktop monitor that is a postage stamp
# whose angular size bears no relation to the real thing held at arm's length,
# so the preview magnifies by default.
_DEFAULT_SCALE = 2

_KEY_NAMES = {
    "a": Button.A,
    "b": Button.B,
    "x": Button.X,
    "y": Button.Y,
}


class PreviewDevice:
    """A window that satisfies both the Display and Buttons ports."""

    def __init__(self, *, scale: int = _DEFAULT_SCALE, title: str = "paperpi"):
        # Imported here rather than at module scope so the package remains
        # importable on the Pi, where pygame is not installed.
        import pygame

        if scale < 1:
            raise ValueError(f"scale must be at least 1, got {scale}")

        self._pygame = pygame
        self._scale = scale
        self._led = Rgb(0, 0, 0)
        self._closed = False

        pygame.init()
        pygame.display.set_caption(title)
        self._surface = pygame.display.set_mode(
            (
                config.DISPLAY_WIDTH * scale,
                config.DISPLAY_HEIGHT * scale + _LED_STRIP_HEIGHT,
            )
        )

    def show(self, image: Image) -> None:
        """Blit a frame, with the status lamp drawn as a strip beneath it."""
        if self._closed:
            return
        frame = self._pygame.image.frombytes(image.tobytes(), image.size, "RGB")
        if self._scale != 1:
            frame = self._pygame.transform.scale_by(frame, self._scale)
        self._surface.blit(frame, (0, 0))
        self._draw_led()
        self._pygame.display.flip()

    def set_led(self, colour: Rgb) -> None:
        """Record the lamp colour; it is painted with the next frame."""
        self._led = colour

    def pressed(self) -> Sequence[Button]:
        """Drain keyboard events, mapping a/b/x/y to the four buttons.

        Closing the window is reported as a close, not a press, so the caller
        sees it through `is_open` rather than as a spurious button.
        """
        if self._closed:
            return ()
        presses: list[Button] = []
        for event in self._pygame.event.get():
            if event.type == self._pygame.QUIT:
                self._closed = True
            elif event.type == self._pygame.KEYDOWN:
                button = _KEY_NAMES.get(self._pygame.key.name(event.key))
                if button is not None:
                    presses.append(button)
        return presses

    @property
    def is_open(self) -> bool:
        """False once the window has been closed, so the loop can stop."""
        return not self._closed

    def close(self) -> None:
        """Tear the window down. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        self._pygame.quit()

    def _draw_led(self) -> None:
        strip: Any = self._pygame.Rect(
            0,
            config.DISPLAY_HEIGHT * self._scale,
            config.DISPLAY_WIDTH * self._scale,
            _LED_STRIP_HEIGHT,
        )
        self._pygame.draw.rect(self._surface, self._led.as_tuple(), strip)
