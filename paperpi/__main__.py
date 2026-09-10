"""Where the real and the stand-in implementations are chosen.

Every other module names only the ports; this one decides which pair is behind
them. Three modes: the Pi with the HAT attached, a preview window on a desktop,
and a screenshot pass that writes each screen to a PNG and exits.
"""

import argparse
import logging
import socket
from datetime import datetime, timedelta
from pathlib import Path

from . import app, config
from .adapters.printer_cups import CupsQueues
from .adapters.scan_fake import FakeScanner
from .adapters.status_linux import LinuxStatus, current_address
from .models import PageScanned, ScanEvent, ScanFinished, ScanId, ScanStarted, Side
from .ports import Buttons, Display
from .protocols import Screen
from .render.canvas import Canvas, Fonts
from .screens import DoneScreen, ErrorScreen, ScanningScreen, StatusScreen
from .serve import ScanLibrary, serve_in_background

__all__ = ["main"]

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the display application."""
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger(__package__).setLevel(
        logging.DEBUG if args.verbose else logging.INFO
    )

    scan_dir: Path = args.scan_dir
    scan_dir.mkdir(parents=True, exist_ok=True)
    fonts = Fonts.load()
    status = LinuxStatus(scan_dir=scan_dir, queues=CupsQueues())
    hostname = socket.gethostname()

    # The address is asked for per link rather than sampled once: a lease can
    # change while the service runs, and a QR encoding the old one is a link
    # that looks right and is not.
    library = ScanLibrary(
        directory=scan_dir,
        address=current_address,
        port=args.port,
        hostname=f"{hostname}.local",
    )

    if args.screenshot is not None:
        _write_screenshots(args.screenshot, fonts, library, hostname)
        return

    serve_in_background(library)
    display, buttons, running = _devices(args)
    home = StatusScreen(
        status=status,
        start_scan=FakeScanner(scan_dir=scan_dir, now=datetime.now).start,
        link_for=lambda finished: library.url_for(finished.scan_id),
        hostname=hostname,
        web_address=f"{hostname}.local:{args.port}",
        now=datetime.now(),
    )
    try:
        app.run(
            display=display,
            buttons=buttons,
            screen=home,
            fonts=fonts,
            now=datetime.now,
            running=running,
        )
    finally:
        display.close()
        buttons.close()


# --- private ---------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="paperpi", description=__doc__)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="render to a desktop window instead of the HAT; a/b/x/y are the buttons",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="magnification of the preview window (default: 2)",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        metavar="DIR",
        help="write one PNG per screen to DIR and exit",
    )
    parser.add_argument(
        "--scan-dir",
        type=Path,
        default=config.SCAN_DIR,
        help=f"where scans are written (default: {config.SCAN_DIR})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.HTTP_PORT,
        help=f"port to serve scans on (default: {config.HTTP_PORT})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args()


def _devices(args: argparse.Namespace):
    """Build the display and button pair for the requested mode."""
    if args.preview:
        from .adapters.preview import PreviewDevice

        device = PreviewDevice(scale=args.scale)
        return device, device, lambda: device.is_open

    from .adapters.hat import HatButtons, HatDisplay

    display: Display = HatDisplay()
    buttons: Buttons = HatButtons()
    return display, buttons, None


def _write_screenshots(
    directory: Path, fonts: Fonts, library: ScanLibrary, hostname: str
) -> None:
    """Render every screen once, so layout can be judged without hardware."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, screen in _sample_screens(library, hostname).items():
        canvas = Canvas.blank(fonts)
        screen.render(canvas)
        path = directory / f"{name}.png"
        canvas.image.save(path)
        logger.info("wrote %s", path)


def _sample_screens(library: ScanLibrary, hostname: str) -> dict[str, Screen]:
    """Build one of each screen with representative state."""
    moment = datetime(2026, 9, 10, 14, 23, 0)
    finished = ScanFinished(
        scan_id=ScanId("a1b2c3d4"),
        path=Path("2026-09-10-1423-a1b2c3d4.pdf"),
        pages=12,
        size_bytes=2_411_000,
        duration=timedelta(seconds=48),
    )

    # No queue source for a screenshot pass: it renders layouts, and reaching
    # for a live print server to do it would make the output depend on the
    # machine it ran on.
    status = LinuxStatus(scan_dir=library.directory, queues=lambda: ())
    home = StatusScreen(
        status=status,
        start_scan=_unavailable,
        link_for=lambda done: library.url_for(done.scan_id),
        hostname=hostname,
        web_address=f"{hostname}.local:{library.port}",
        now=moment,
    )
    # Driven through the real event path rather than by setting attributes, so
    # the screenshot shows a state the screen can genuinely reach.
    scanning = ScanningScreen(
        handle=_ScriptedScan(
            [
                ScanStarted(at=moment),
                PageScanned(page=7, side=Side.BACK),
            ]
        ),
        home=lambda: home,
        started_at=moment,
        link_for=lambda done: library.url_for(done.scan_id),
    )
    scanning.on_tick(moment + timedelta(seconds=14))

    return {
        "status": home,
        "scanning": scanning,
        "done": DoneScreen(
            finished=finished, home=lambda: home, link=library.url_for(finished.scan_id)
        ),
        "error": ErrorScreen(
            message="scanner reported a paper jam in the feeder",
            home=lambda: home,
        ),
    }


class _ScriptedScan:
    """A handle that yields a fixed list of events once, then nothing."""

    def __init__(self, events: list[ScanEvent]):
        self._events = events

    def poll(self) -> list[ScanEvent]:
        drained, self._events = self._events, []
        return drained

    def cancel(self) -> None:
        return None


def _unavailable():
    raise RuntimeError("scanning is not available while taking screenshots")


if __name__ == "__main__":
    main()
