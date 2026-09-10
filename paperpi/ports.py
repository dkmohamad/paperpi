"""Contracts for everything outside the process.

Each port has two implementations in `adapters`: one that talks to the Pi's
hardware and one that stands in for it on a development machine. Logic imports
only what is here, so the pair is chosen once, in `__main__`.

Single-operation ports are `Callable` aliases; only ports with several methods
earn a `Protocol`.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from PIL.Image import Image

from .models import Button, Rgb, ScanEvent, SystemStatus

__all__ = [
    "Buttons",
    "Display",
    "ScanHandle",
    "StartScan",
    "StatusSource",
]

# Sampling the system's state is one operation with no lifecycle of its own.
type StatusSource = Callable[[], SystemStatus]


class ScanHandle(Protocol):
    """A scan already in progress.

    Polling rather than iteration keeps the render loop responsive: the loop
    must keep drawing while the scanner works, so it cannot block on the next
    event.
    """

    def poll(self) -> Sequence[ScanEvent]:
        """Return events produced since the last call, oldest first.

        Returns:
            Possibly empty. A ScanFinished or ScanFailed is terminal; nothing
            follows it.
        """
        ...

    def cancel(self) -> None:
        """Ask the scan to stop. A ScanFailed follows unless it had finished."""
        ...


# Starting a scan is one operation; the returned handle carries the rest.
type StartScan = Callable[[], ScanHandle]


class Display(Protocol):
    """Somewhere to put a frame, and a lamp to signal overall state."""

    def show(self, image: Image) -> None:
        """Present one complete frame.

        Args:
            image: RGB image matching the configured display size.
        """
        ...

    def set_led(self, colour: Rgb) -> None:
        """Set the status lamp.

        Args:
            colour: Shown at the configured brightness, not full duty.
        """
        ...

    def close(self) -> None:
        """Release the device. Safe to call twice."""
        ...


class Buttons(Protocol):
    """A source of button presses that never blocks."""

    def pressed(self) -> Sequence[Button]:
        """Return presses since the last call, oldest first, and clear them.

        Returns:
            Possibly empty. Releases are not reported -- only presses.
        """
        ...

    def close(self) -> None:
        """Release the device. Safe to call twice."""
        ...
