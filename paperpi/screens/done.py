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
from ..render.canvas import TITLE_HEIGHT, Canvas
from ..render.format import format_duration, format_size
from ..render.qr import qr_image

__all__ = ["DoneScreen"]

# The QR gets everything below the title bar. It is the only thing on this
# screen that has to work from arm's length, and a code is only as scannable as
# its smallest feature: modules are drawn at a whole number of pixels each, so
# the usable size steps rather than slides. Giving it the full panel is what
# buys a sixth pixel per module instead of a third of the space and three.
_GAP = 4
_QR_BUDGET = config.DISPLAY_HEIGHT - TITLE_HEIGHT - _GAP * 2


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
        self._qr = qr_image(link, _QR_BUDGET, config.BACKGROUND, config.TEXT)

    @property
    def led(self) -> Rgb:
        """Green -- the job finished and the file exists."""
        return config.READINESS_COLOURS[Readiness.READY]

    def render(self, canvas: Canvas) -> None:
        """Draw the summary in the title bar and give the QR everything else.

        The filename is deliberately not shown. It is a timestamp and a hash --
        nothing a person reads off a panel and does anything with -- and the
        space it took is worth more as code.
        """
        summary = (
            f"{self._finished.pages} pages  "
            f"{format_size(self._finished.size_bytes)}  "
            f"{format_duration(self._finished.duration)}"
        )
        canvas.title("DONE", summary)

        # Placed from the rendered size rather than the budget: the code lands
        # on whole modules, so it is usually a little smaller than the space it
        # was offered, and centring on the budget would sit it off to one side.
        left = (config.DISPLAY_WIDTH - self._qr.width) // 2
        body = config.DISPLAY_HEIGHT - TITLE_HEIGHT
        top = TITLE_HEIGHT + (body - self._qr.height) // 2
        canvas.paste(self._qr, (left, top))

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
