"""The resting view: what is attached, and how to start a scan.

This is what the box shows almost all of the time, so it answers the two
questions worth answering from across a room -- can it be reached, and is
anything wrong -- with colour rather than text.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from .. import config
from ..models import Button, Rgb, ScanFinished, SystemStatus
from ..ports import StartScan, StatusSource
from ..protocols import Screen
from ..render.canvas import Canvas
from ..render.format import format_size
from .scanning import ScanningScreen

__all__ = ["StatusScreen"]

# Peripheral state changes on a human timescale; polling faster would spend the
# render loop's budget shelling out to lpstat for no visible benefit.
_REFRESH = timedelta(seconds=2)


class StatusScreen:
    """Shows peripheral readiness and network reachability."""

    def __init__(
        self,
        *,
        status: StatusSource,
        start_scan: StartScan,
        link_for: Callable[[ScanFinished], str],
        hostname: str,
        web_address: str,
        now: datetime,
    ):
        self._status_source = status
        self._start_scan = start_scan
        self._link_for = link_for
        self._hostname = hostname
        self._web_address = web_address
        self._status = status()
        self._sampled_at = now
        self._now = now

    @property
    def led(self) -> Rgb:
        """Mirror the worst peripheral state, so a fault is visible unlit-side."""
        return config.READINESS_COLOURS[self._status.peripherals.worst]

    @property
    def status(self) -> SystemStatus:
        """The most recent sample."""
        return self._status

    def render(self, canvas: Canvas) -> None:
        """Draw the peripheral rows, a system line, and the scan hint."""
        # The header carries the address to type; the system line below carries
        # the raw IP for when mDNS does not resolve, which on Android is often.
        # Showing the IP in both places said one thing twice and the useful
        # thing not at all.
        canvas.title(self._hostname, self._web_address)

        for index, peripheral in enumerate(self._status.peripherals):
            canvas.row(
                index,
                config.READINESS_COLOURS[peripheral.readiness],
                peripheral.kind.label,
                peripheral.detail,
            )

        canvas.centred(
            config.DISPLAY_HEIGHT - 62,
            self._system_line(),
            canvas.fonts.detail,
            config.MUTED,
        )
        canvas.footer("press any button to scan")

    def on_button(self, button: Button) -> Screen | None:
        """Start a scan. Every button does this until the scanner arrives."""
        del button
        return ScanningScreen(
            handle=self._start_scan(),
            home=self._return_home,
            started_at=self._now,
            link_for=self._link_for,
        )

    def on_tick(self, now: datetime) -> Screen | None:
        """Re-sample the system if the last reading has gone stale."""
        self._now = now
        if now - self._sampled_at >= _REFRESH:
            self._status = self._status_source()
            self._sampled_at = now
        return None

    def _return_home(self) -> Screen:
        return self

    def _system_line(self) -> str:
        parts = [str(self._status.network)]
        if self._status.temperature_c is not None:
            parts.append(f"{self._status.temperature_c:.0f}\N{DEGREE SIGN}C")
        if self._status.storage.free_bytes is not None:
            parts.append(f"{format_size(self._status.storage.free_bytes)} free")
        return "  \N{MIDDLE DOT}  ".join(parts)
