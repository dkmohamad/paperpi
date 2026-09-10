"""The view after a successful scan.

The QR is the point of this screen. A scan that lands on a share nobody opens
is a scan you have to go and find later, so the finished document offers itself
as a link a phone camera resolves in one motion.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from .. import config
from ..models import Button, Readiness, Rgb, ScanFinished
from ..protocols import Screen
from ..render.canvas import Canvas
from ..render.format import format_duration, format_size
from ..render.qr import qr_image

__all__ = ["DoneScreen"]

_QR_SIZE = 116
_QR_LEFT = 14
_QR_TOP = 48
_TEXT_LEFT = _QR_LEFT + _QR_SIZE + 16


class DoneScreen:
    """Shows what was produced, and a QR code that opens it."""

    def __init__(
        self,
        *,
        finished: ScanFinished,
        home: Callable[[], Screen],
        link: str,
        linger: timedelta | None = None,
    ):
        self._finished = finished
        self._home = home
        self._link = link
        # `linger or ...` would treat an explicit timedelta(0) as "not given".
        self._linger = (
            timedelta(seconds=config.DONE_SCREEN_SECONDS) if linger is None else linger
        )
        self._shown_at: datetime | None = None
        # Rendered once: the code cannot change while this screen is showing,
        # and re-encoding it every frame would be pure waste.
        self._qr = qr_image(link, _QR_SIZE, config.BACKGROUND, config.TEXT)

    @property
    def led(self) -> Rgb:
        """Green -- the job finished and the file exists."""
        return config.READINESS_COLOURS[Readiness.READY]

    def render(self, canvas: Canvas) -> None:
        """Draw the QR beside the document's name, size and duration."""
        summary = (
            f"{self._finished.pages} pages  {format_duration(self._finished.duration)}"
        )
        canvas.title("DONE", summary)
        canvas.paste(self._qr, (_QR_LEFT, _QR_TOP))

        canvas.text(
            (_TEXT_LEFT, _QR_TOP + 8),
            canvas.truncated(
                self._finished.path.name,
                canvas.fonts.detail,
                config.DISPLAY_WIDTH - _TEXT_LEFT - config.MARGIN,
            ),
            canvas.fonts.detail,
            config.TEXT,
        )
        canvas.text(
            (_TEXT_LEFT, _QR_TOP + 34),
            format_size(self._finished.size_bytes),
            canvas.fonts.detail,
            config.MUTED,
        )
        canvas.text(
            (_TEXT_LEFT, _QR_TOP + 76),
            "scan to open",
            canvas.fonts.label,
            config.ACCENT,
        )
        canvas.footer("any button to return")

    def on_button(self, button: Button) -> Screen | None:
        """Return to the resting screen."""
        del button
        return self._home()

    def on_tick(self, now: datetime) -> Screen | None:
        """Return home unattended, so the panel does not sit on a stale result."""
        if self._shown_at is None:
            self._shown_at = now
            return None
        if now - self._shown_at >= self._linger:
            return self._home()
        return None
