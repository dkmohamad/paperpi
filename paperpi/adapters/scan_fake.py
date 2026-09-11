"""A scanner that produces a real document without any hardware.

This exists so every path downstream of a scan is exercised before the physical
scanner arrives: a genuine multi-page PDF is written to the scan directory, is
served over HTTP, and its QR code resolves on a phone. Only the pages'
contents are invented.

The timeline is computed from the clock rather than run on a thread, so a test
can drive a whole scan by handing it the times it wants.
"""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from ..models import (
    PageScanned,
    ScanEvent,
    ScanFailed,
    ScanFinished,
    ScanStarted,
    Side,
)
from ..scans import write_scan

__all__ = ["FakeScanner"]

_PAGE_INTERVAL = timedelta(milliseconds=700)
_PAGE_SIZE = (620, 877)  # A4 at roughly 75 dpi -- small, but a believable shape


class FakeScanner:
    """Emits a plausible scan and writes a real PDF at the end of it."""

    def __init__(
        self,
        *,
        scan_dir: Path,
        now: Callable[[], datetime],
        pages: int = 12,
    ):
        if pages < 1:
            raise ValueError(f"a scan must produce at least one page, got {pages}")
        self._scan_dir = scan_dir
        self._now = now
        self._pages = pages

    def start(self) -> "_FakeScanHandle":
        """Begin a scan.

        Returns:
            A handle whose events unfold as the clock advances.
        """
        return _FakeScanHandle(
            scan_dir=self._scan_dir,
            now=self._now,
            pages=self._pages,
            started_at=self._now(),
        )


class _FakeScanHandle:
    """One run of the fake scanner."""

    def __init__(
        self,
        *,
        scan_dir: Path,
        now: Callable[[], datetime],
        pages: int,
        started_at: datetime,
    ):
        self._scan_dir = scan_dir
        self._now = now
        self._pages = pages
        self._started_at = started_at
        self._emitted = 0
        self._started = False
        self._terminal = False
        self._cancelled = False

    def poll(self) -> Sequence[ScanEvent]:
        """Return whatever the elapsed time says has happened since last asked."""
        if self._terminal:
            return ()

        events: list[ScanEvent] = []
        if not self._started:
            self._started = True
            events.append(ScanStarted(at=self._started_at))

        if self._cancelled:
            self._terminal = True
            events.append(ScanFailed(message="cancelled at the panel"))
            return events

        elapsed = self._now() - self._started_at
        due = min(int(elapsed / _PAGE_INTERVAL), self._pages)
        while self._emitted < due:
            self._emitted += 1
            events.append(
                PageScanned(
                    page=self._emitted,
                    side=Side.FRONT if self._emitted % 2 else Side.BACK,
                )
            )

        if self._emitted >= self._pages:
            self._terminal = True
            events.append(self._write(elapsed))
        return events

    def cancel(self) -> None:
        """Stop the run; the next poll reports the failure."""
        self._cancelled = True

    def _write(self, elapsed: timedelta) -> ScanFinished:
        """Render the pages to a PDF and hand it to the shared writer.

        Naming is deliberately not done here. It is a contract the reader and
        retention both depend on, so it lives in one place that every producer
        calls -- see `paperpi.scans`.
        """
        pages = [self._page(number) for number in range(1, self._pages + 1)]
        buffer = BytesIO()
        pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:])
        return write_scan(
            data=buffer.getvalue(),
            scan_dir=self._scan_dir,
            started_at=self._started_at,
            pages=self._pages,
            duration=elapsed,
        )

    def _page(self, number: int) -> Image.Image:
        """Draw one placeholder page, obviously not a real document."""
        image = Image.new("RGB", _PAGE_SIZE, (255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (28, 28, _PAGE_SIZE[0] - 28, _PAGE_SIZE[1] - 28), outline=(0, 0, 0)
        )
        draw.text((60, 70), "paperpi test page", fill=(0, 0, 0))
        draw.text((60, 96), f"page {number} of {self._pages}", fill=(0, 0, 0))
        draw.text(
            (60, 122),
            f"generated {self._started_at:%Y-%m-%d %H:%M:%S}",
            fill=(90, 90, 90),
        )
        draw.text(
            (60, 168),
            "This document was produced by the mock scanner.",
            fill=(90, 90, 90),
        )
        for offset in range(0, 380, 26):
            width = 300 + (number * 37 + offset) % 220
            draw.line(
                (60, 220 + offset, 60 + width, 220 + offset), fill=(180, 180, 180)
            )
        return image
