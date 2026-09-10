"""The view after something failed.

Kept separate from the resting screen so a failure cannot be missed by someone
glancing at the panel: the message stays until it is dismissed, and the lamp
stays red the whole time.
"""

from collections.abc import Callable
from datetime import datetime

from .. import config
from ..models import Button, Readiness, Rgb
from ..protocols import Screen
from ..render.canvas import Canvas

__all__ = ["ErrorScreen"]


class ErrorScreen:
    """Shows why something failed, until acknowledged."""

    def __init__(
        self,
        *,
        message: str,
        home: Callable[[], Screen],
        headline: str = "scan failed",
    ):
        self._message = message
        self._home = home
        self._headline = headline

    @property
    def led(self) -> Rgb:
        """Red, and it stays red until the screen is dismissed."""
        return config.READINESS_COLOURS[Readiness.ERROR]

    def render(self, canvas: Canvas) -> None:
        """Draw the failure and how to clear it."""
        canvas.title("PROBLEM")
        canvas.centred(
            80,
            self._headline,
            canvas.fonts.big,
            config.READINESS_COLOURS[Readiness.ERROR],
        )
        lines = canvas.wrapped(
            self._message,
            canvas.fonts.detail,
            config.DISPLAY_WIDTH - 2 * config.MARGIN,
            _MAX_LINES,
        )
        for index, line in enumerate(lines):
            canvas.centred(120 + index * 20, line, canvas.fonts.detail, config.MUTED)
        canvas.footer("any button to dismiss")

    def on_button(self, button: Button) -> Screen | None:
        """Dismiss and return to the resting screen."""
        del button
        return self._home()

    def on_tick(self, now: datetime) -> Screen | None:
        """Stay put. A failure waits to be seen rather than timing out."""
        del now
        return None


# --- private ---------------------------------------------------------------

_MAX_LINES = 3
