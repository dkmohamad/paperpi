"""The contract a screen implements.

A screen owns one view and the transitions out of it. Returning the next screen
from an input handler -- rather than mutating a shared mode flag -- keeps each
transition explicit and testable: a test can press a button on a screen and
assert on the type it hands back, with no display and no clock.
"""

from datetime import datetime
from typing import Protocol

from .models import Button, Rgb
from .render.canvas import Canvas

__all__ = ["Screen"]


class Screen(Protocol):
    """One view, and the ways out of it."""

    @property
    def led(self) -> Rgb:
        """The status lamp colour while this screen is showing."""
        ...

    def render(self, canvas: Canvas) -> None:
        """Draw this screen.

        Args:
            canvas: Cleared before the call; owned by the caller afterwards.
        """
        ...

    def on_button(self, button: Button) -> "Screen | None":
        """Handle a press.

        Args:
            button: The button pressed.

        Returns:
            The screen to show next, or None to stay on this one.
        """
        ...

    def on_tick(self, now: datetime) -> "Screen | None":
        """Advance anything time-driven, such as elapsed counters or timeouts.

        Args:
            now: Current time, injected so tests need no real clock.

        Returns:
            The screen to show next, or None to stay on this one.
        """
        ...
