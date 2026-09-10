"""The view while a scan runs.

Deliberately shows a count and not a percentage. A sheet feeder does not know
how many pages it holds until the hopper empties, so the honest readout is how
many sides have been captured so far and which face the current one was.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from .. import config
from ..models import (
    Button,
    PageScanned,
    Rgb,
    ScanEvent,
    ScanFailed,
    ScanFinished,
    ScanStarted,
    Side,
)
from ..ports import ScanHandle
from ..protocols import Screen
from ..render.canvas import Canvas
from ..render.format import format_duration
from .done import DoneScreen
from .error import ErrorScreen

__all__ = ["ScanningScreen"]

# A single press is easy to make by accident while the scanner is feeding, so
# cancelling asks twice. The arming lapses rather than persisting, so a stray
# press does not leave the next one destructive.
_CANCEL_ARM_WINDOW = timedelta(seconds=4)


class ScanningScreen:
    """Reports a running scan and offers a two-press cancel."""

    def __init__(
        self,
        *,
        handle: ScanHandle,
        home: Callable[[], Screen],
        started_at: datetime,
        link_for: Callable[[ScanFinished], str],
    ):
        self._handle = handle
        self._home = home
        self._started_at = started_at
        self._link_for = link_for
        self._now = started_at
        self._pages = 0
        self._side: Side | None = None
        self._cancel_armed_at: datetime | None = None

    @property
    def led(self) -> Rgb:
        """Blue throughout, so a running job is distinct from a resting one."""
        return config.ACCENT

    def render(self, canvas: Canvas) -> None:
        """Draw the page count, the current side, and an activity indicator."""
        elapsed = self._now - self._started_at
        canvas.title("SCANNING", format_duration(elapsed))

        if self._pages:
            canvas.centred(96, f"page {self._pages}", canvas.fonts.big, config.TEXT)
            side = "" if self._side is None else f"{self._side} side"
            canvas.centred(128, side, canvas.fonts.detail, config.MUTED)
        else:
            canvas.centred(96, "starting", canvas.fonts.big, config.TEXT)
            canvas.centred(128, "warming up", canvas.fonts.detail, config.MUTED)

        canvas.activity(170, int(elapsed.total_seconds() * 4))
        canvas.footer(
            "press again to cancel" if self._cancel_pending else "any button cancels"
        )

    def on_button(self, button: Button) -> Screen | None:
        """Arm the cancel on the first press; act on the second."""
        del button
        if self._cancel_pending:
            self._handle.cancel()
            self._cancel_armed_at = None
        else:
            self._cancel_armed_at = self._now
        return None

    def on_tick(self, now: datetime) -> Screen | None:
        """Drain the scan's events and move on once one of them is terminal."""
        self._now = now
        for event in self._handle.poll():
            finished = self._apply(event)
            if finished is not None:
                return finished
        return None

    @property
    def _cancel_pending(self) -> bool:
        if self._cancel_armed_at is None:
            return False
        return self._now - self._cancel_armed_at < _CANCEL_ARM_WINDOW

    def _apply(self, event: ScanEvent) -> Screen | None:
        """Fold one event in, returning a screen only for a terminal one."""
        match event:
            case ScanStarted(at=at):
                self._started_at = at
            case PageScanned(page=page, side=side):
                self._pages = page
                self._side = side
            case ScanFinished():
                return DoneScreen(
                    finished=event,
                    home=self._home,
                    link=self._link_for(event),
                )
            case ScanFailed(message=message):
                return ErrorScreen(message=message, home=self._home)
        return None
