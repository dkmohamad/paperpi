"""Shared fixtures and the stand-in devices.

Collaborators are injected, never patched: every seam the tests need is a
constructor parameter on the thing under test.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL.Image import Image

from paperpi.models import Button, Rgb, ScanEvent
from paperpi.ports import Buttons, Display, ScanHandle
from paperpi.render.canvas import Fonts


@pytest.fixture(scope="session")
def fonts() -> Fonts:
    """The real bundled faces -- rendering tests should exercise the real ones."""
    return Fonts.load()


@pytest.fixture
def scan_dir(tmp_path: Path) -> Path:
    """A directory scans may be written into."""
    directory = tmp_path / "scans"
    directory.mkdir()
    return directory


class FakeClock:
    """A clock the test advances by hand."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class RecordingDisplay:
    """A Display that keeps what it was given instead of showing it."""

    def __init__(self):
        self.frames: list[Image] = []
        self.leds: list[Rgb] = []
        self.closed = False

    def show(self, image: Image) -> None:
        self.frames.append(image.copy())

    def set_led(self, colour: Rgb) -> None:
        self.leds.append(colour)

    def close(self) -> None:
        self.closed = True


class ScriptedButtons:
    """A Buttons that plays a fixed script, one entry per frame."""

    def __init__(self, script: Sequence[Sequence[Button]] = ()):
        self._script = list(script)

    def pressed(self) -> Sequence[Button]:
        if not self._script:
            return ()
        return self._script.pop(0)

    def close(self) -> None:
        return None


class ScriptedScan:
    """A ScanHandle that emits queued events, one batch per poll."""

    def __init__(self, batches: Sequence[Sequence[ScanEvent]] = ()):
        self._batches = [list(batch) for batch in batches]
        self.cancelled = False

    def poll(self) -> Sequence[ScanEvent]:
        if not self._batches:
            return ()
        return self._batches.pop(0)

    def cancel(self) -> None:
        self.cancelled = True


# The fakes are checked against the contracts they stand in for. Without this a
# port can gain a method, every adapter can be updated, and the doubles keep
# compiling -- so the suite would go on passing against an interface that no
# longer exists.
_display_conforms: Display = RecordingDisplay()
_buttons_conforms: Buttons = ScriptedButtons()
_handle_conforms: ScanHandle = ScriptedScan()
