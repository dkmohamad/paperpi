"""The render loop: what it asks each frame, and in what order."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path

import pytest

from paperpi import app, config
from paperpi.models import (
    Button,
    Network,
    Peripheral,
    PeripheralKind,
    Peripherals,
    Readiness,
    ScanFinished,
    ScanId,
    ScanStarted,
    Storage,
    SystemStatus,
)
from paperpi.protocols import Screen
from paperpi.render.canvas import Fonts
from paperpi.screens import DoneScreen, ScanningScreen, StatusScreen

from .conftest import FakeClock, RecordingDisplay, ScriptedButtons, ScriptedScan

_MOMENT = datetime(2026, 9, 10, 14, 23, 0)


def _status() -> SystemStatus:
    return SystemStatus(
        network=Network(interface="eth0", address=IPv4Address("192.168.1.246")),
        peripherals=Peripherals(
            [Peripheral(PeripheralKind.SCANNER, Readiness.READY, "ok")]
        ),
        storage=Storage(path=Path("/scans"), free_bytes=1_000, mounted=False),
        temperature_c=40.0,
    )


def _home(handle: ScriptedScan | None = None) -> StatusScreen:
    scan = handle or ScriptedScan([[ScanStarted(at=_MOMENT)]])
    return StatusScreen(
        status=_status,
        start_scan=lambda: scan,
        link_for=lambda finished: f"http://x/s/{finished.scan_id}",
        hostname="paperpi",
        web_address="paperpi.local:8080",
        now=_MOMENT,
    )


def _run(
    *,
    script: Sequence[Sequence[Button]],
    frames: int,
    screen: Screen,
    fonts: Fonts,
    step: float = 0.05,
) -> tuple[Screen, RecordingDisplay]:
    display = RecordingDisplay()
    clock = FakeClock(_MOMENT)

    def now() -> datetime:
        clock.advance(step)
        return clock.now

    ended = app.run(
        display=display,
        buttons=ScriptedButtons(script),
        screen=screen,
        fonts=fonts,
        now=now,
        sleep=lambda _: None,
        max_frames=frames,
    )
    return ended, display


def test_loop_should_draw_the_first_frame_at_the_display_size(fonts: Fonts):
    """The first pass always paints, at the panel's exact dimensions.

    A frame of the wrong size is rejected by the ST7789 driver rather than
    scaled, so the size is part of the contract with the panel.
    """
    _, display = _run(script=[], frames=1, screen=_home(), fonts=fonts)
    assert len(display.frames) == 1
    assert display.frames[0].size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)


def test_loop_should_not_push_a_frame_that_has_not_changed(fonts: Fonts):
    """A resting screen is pushed once, not once per pass.

    Measured on a Pi 4, an SPI push costs 38 ms against 4 ms to render, so
    repainting an unchanged status screen twenty times a second spends most of
    a core on nothing. Without this the service sits at ~49% CPU while idle.
    """
    _, display = _run(script=[], frames=6, screen=_home(), fonts=fonts, step=0.0)
    assert len(display.frames) == 1


def test_loop_should_back_off_while_the_frame_is_unchanged(fonts: Fonts):
    """The gap between passes grows once the display stops changing.

    A full status render costs about 10 ms on a Pi 4, so holding 20 fps on a
    resting screen spends roughly a quarter of a core producing identical
    pixels. The back-off is capped so a press is still noticed promptly, and
    presses are queued by the adapter rather than polled, so none is lost.
    """
    waits: list[float] = []
    display = RecordingDisplay()
    clock = FakeClock(_MOMENT)
    app.run(
        display=display,
        buttons=ScriptedButtons([]),
        screen=_home(),
        fonts=fonts,
        now=lambda: clock.now,
        sleep=waits.append,
        frame_seconds=0.05,
        idle_seconds=0.2,
        max_frames=8,
    )
    # Each sleep is the interval minus however long that pass actually took,
    # so compare the trend rather than exact values.
    assert waits[0] == pytest.approx(0.05, abs=0.01)
    assert waits[-1] == pytest.approx(0.2, abs=0.01)
    assert waits[-1] > waits[0] * 3, "the interval should grow while idle"
    for earlier, later in zip(waits, waits[1:], strict=False):
        assert later >= earlier - 0.005, "the interval should not shrink while idle"


def test_loop_should_return_to_full_rate_when_the_frame_changes(fonts: Fonts):
    """Backing off must not persist into a screen that is animating.

    The scanning screen updates its elapsed counter every pass, so the loop has
    to drop straight back to the fast interval rather than staying slow.
    """
    handle = ScriptedScan([[ScanStarted(at=_MOMENT)]])
    scanning = _home(handle).on_button(Button.A)
    assert scanning is not None
    waits: list[float] = []
    clock = FakeClock(_MOMENT)

    def now() -> datetime:
        clock.advance(1.0)
        return clock.now

    app.run(
        display=RecordingDisplay(),
        buttons=ScriptedButtons([]),
        screen=scanning,
        fonts=fonts,
        now=now,
        sleep=waits.append,
        frame_seconds=0.05,
        idle_seconds=0.2,
        max_frames=5,
    )
    assert max(waits) == pytest.approx(0.05, abs=0.01)


def test_loop_should_push_again_once_the_frame_changes(fonts: Fonts):
    """Deduplication must not stall a screen that is genuinely animating.

    The scanning screen shows an elapsed counter and a moving indicator, so
    successive frames differ and each one has to reach the panel.
    """
    handle = ScriptedScan([[ScanStarted(at=_MOMENT)]])
    scanning = _home(handle).on_button(Button.A)
    assert scanning is not None
    _, display = _run(script=[], frames=6, screen=scanning, fonts=fonts, step=1.0)
    assert len(display.frames) > 1


def test_loop_should_follow_a_button_to_the_next_screen(fonts: Fonts):
    """A press on the resting screen starts a scan and the loop follows it."""
    ended, _ = _run(script=[[], [Button.A]], frames=3, screen=_home(), fonts=fonts)
    assert isinstance(ended, ScanningScreen)


def test_extra_presses_in_one_frame_should_not_reach_the_new_screen(fonts: Fonts):
    """The press that causes a transition is consumed by it.

    Proved by consequence rather than by inspection: the scanning screen needs
    two presses to cancel, so if the leftover presses from the same frame had
    leaked through, the very next press would cancel the job instead of merely
    arming it. Asserting the handle is still running is what shows they did not.
    """
    handle = ScriptedScan([[ScanStarted(at=_MOMENT)]])
    ended, _ = _run(
        script=[[Button.A, Button.B, Button.X]],
        frames=2,
        screen=_home(handle),
        fonts=fonts,
    )
    assert isinstance(ended, ScanningScreen)
    assert not handle.cancelled

    ended.on_button(Button.A)
    assert not handle.cancelled, "leftover presses armed the cancel"

    ended.on_button(Button.A)
    assert handle.cancelled, "two deliberate presses should cancel"


def test_loop_should_stop_when_running_returns_false(fonts: Fonts):
    """Closing the preview window ends the loop rather than spinning on."""
    display = RecordingDisplay()
    clock = FakeClock(_MOMENT)
    calls = {"count": 0}

    def running() -> bool:
        calls["count"] += 1
        return calls["count"] <= 2

    app.run(
        display=display,
        buttons=ScriptedButtons([]),
        screen=_home(),
        fonts=fonts,
        now=lambda: clock.now,
        sleep=lambda _: None,
        running=running,
    )
    # Consulted three times: twice permitting a pass, once refusing. Asserting
    # the predicate rather than the frame count, because an unchanged frame is
    # legitimately not pushed and would make a frame count say nothing about
    # whether the loop stopped.
    assert calls["count"] == 3
    assert display.frames, "the loop should have painted at least once"


def test_loop_should_drive_time_based_transitions(fonts: Fonts):
    """The clock the loop is given is the clock the screens see.

    Driven end to end: a Done screen with a short linger is left to time out by
    the loop alone, with no direct call to on_tick. A loop that failed to pass
    its clock through would sit on Done forever.
    """
    finished = ScanFinished(
        scan_id=ScanId("a1b2c3d4"),
        path=Path("2026-09-10-1423-a1b2c3d4.pdf"),
        pages=2,
        size_bytes=1000,
        duration=timedelta(seconds=3),
    )
    done = DoneScreen(
        finished=finished,
        home=_home,
        link="http://x/s/a1b2c3d4",
        linger=timedelta(seconds=1),
    )
    ended, _ = _run(script=[], frames=6, screen=done, fonts=fonts, step=0.4)
    assert isinstance(ended, StatusScreen)
