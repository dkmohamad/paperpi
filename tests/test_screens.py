"""Screen behaviour: what they draw, and where each way out leads."""

from datetime import datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path

from paperpi import config
from paperpi.models import (
    Button,
    Network,
    PageScanned,
    Peripheral,
    PeripheralKind,
    Peripherals,
    Readiness,
    Rgb,
    ScanFailed,
    ScanFinished,
    ScanId,
    ScanStarted,
    Side,
    Storage,
    SystemStatus,
)
from paperpi.render.canvas import Canvas, Fonts
from paperpi.screens import DoneScreen, ErrorScreen, ScanningScreen, StatusScreen

from .conftest import ScriptedScan

_MOMENT = datetime(2026, 9, 10, 14, 23, 0)

# Where the status screen paints each row's indicator. Derived from the layout
# constants in render.canvas; if that layout moves, these move with it.
_DOT_X = config.MARGIN + 5
_DOT_Y = (59, 93, 127)

_FINISHED = ScanFinished(
    scan_id=ScanId("a1b2c3d4"),
    path=Path("2026-09-10-1423-a1b2c3d4.pdf"),
    pages=12,
    size_bytes=2_411_000,
    duration=timedelta(seconds=48),
)


def _status(*readiness: Readiness) -> SystemStatus:
    kinds = (PeripheralKind.SCANNER, PeripheralKind.PRINTER, PeripheralKind.STORAGE)
    return SystemStatus(
        network=Network(interface="eth0", address=IPv4Address("192.168.1.246")),
        peripherals=Peripherals(
            [
                Peripheral(kind=kind, readiness=state, detail="detail")
                for kind, state in zip(kinds, readiness, strict=True)
            ]
        ),
        storage=Storage(path=Path("/scans"), free_bytes=1_000_000, mounted=False),
        temperature_c=47.2,
    )


def _link_for(finished: ScanFinished) -> str:
    return f"http://x/s/{finished.scan_id}"


def _home(**overrides: object) -> StatusScreen:
    kwargs: dict[str, object] = {
        "status": lambda: _status(Readiness.READY, Readiness.ABSENT, Readiness.ERROR),
        "start_scan": lambda: ScriptedScan(),
        "link_for": _link_for,
        "hostname": "paperpi",
        "web_address": "paperpi.local:8080",
        "now": _MOMENT,
    }
    kwargs.update(overrides)
    return StatusScreen(**kwargs)  # type: ignore[arg-type]


def test_status_should_colour_each_row_by_its_readiness(fonts: Fonts):
    """Each indicator takes the colour of the peripheral it belongs to.

    Colour is the only thing on this screen readable from across a room, so a
    row painted with the wrong state is the whole display lying. Asserted on
    the filled dot rather than on text, which varies with the font renderer.
    """
    screen = _home()
    canvas = Canvas.blank(fonts)
    screen.render(canvas)

    expected = (Readiness.READY, Readiness.ABSENT, Readiness.ERROR)
    for index, state in enumerate(expected):
        pixel = canvas.image.getpixel((_DOT_X, _DOT_Y[index]))
        assert pixel == config.READINESS_COLOURS[state].as_tuple()


def test_status_led_should_show_the_worst_peripheral_state(fonts: Fonts):
    """The lamp mirrors the worst row, so a single fault is never hidden."""
    screen = _home()
    assert screen.led == config.READINESS_COLOURS[Readiness.ERROR]


def test_status_should_start_a_scan_on_any_button(fonts: Fonts):
    """Every button triggers a scan until the scanner's own button exists.

    The Notion build splits these later (A scans, B unmounts); until then the
    panel should respond to whichever one is pressed rather than only one.
    """
    for button in Button:
        following = _home().on_button(button)
        assert isinstance(following, ScanningScreen)


def test_status_should_resample_only_after_the_refresh_interval(fonts: Fonts):
    """Polling is rate-limited so the render loop is not spent re-reading sysfs.

    The status source is called from inside the frame loop, so sampling every
    frame would multiply its cost by twenty for no visible change.
    """
    calls = {"count": 0}

    def counting_source() -> SystemStatus:
        calls["count"] += 1
        return _status(Readiness.READY, Readiness.READY, Readiness.READY)

    screen = _home(status=counting_source)
    assert calls["count"] == 1

    screen.on_tick(_MOMENT + timedelta(milliseconds=500))
    assert calls["count"] == 1

    screen.on_tick(_MOMENT + timedelta(seconds=3))
    assert calls["count"] == 2


def _scanning(handle: ScriptedScan) -> ScanningScreen:
    return ScanningScreen(
        handle=handle,
        home=_home,
        started_at=_MOMENT,
        link_for=_link_for,
    )


def test_scanning_should_move_to_done_on_a_finished_event(fonts: Fonts):
    """A completed scan hands over to the screen that offers the file."""
    screen = _scanning(ScriptedScan([[ScanStarted(at=_MOMENT)], [_FINISHED]]))
    assert screen.on_tick(_MOMENT) is None
    assert isinstance(screen.on_tick(_MOMENT + timedelta(seconds=1)), DoneScreen)


def test_scanning_should_move_to_error_on_a_failure(fonts: Fonts):
    """A failed scan must not reach Done, which would offer a missing file."""
    screen = _scanning(ScriptedScan([[ScanFailed(message="jam")]]))
    assert isinstance(screen.on_tick(_MOMENT), ErrorScreen)


def test_scanning_should_require_two_presses_to_cancel(fonts: Fonts):
    """Cancelling asks twice, because one press is easy to make by accident.

    A single-press cancel next to a running feeder loses the whole job to a
    brush of the hand, which is exactly when someone is reaching for the paper.
    """
    handle = ScriptedScan([[ScanStarted(at=_MOMENT)]])
    screen = _scanning(handle)
    screen.on_tick(_MOMENT)

    screen.on_button(Button.A)
    assert not handle.cancelled

    screen.on_button(Button.A)
    assert handle.cancelled


def test_scanning_cancel_arming_should_lapse(fonts: Fonts):
    """An armed cancel expires, so a stray press does not leave the next fatal.

    Otherwise a press now and an unrelated press a minute later would combine
    into a cancel nobody intended.
    """
    handle = ScriptedScan([[ScanStarted(at=_MOMENT)]])
    screen = _scanning(handle)
    screen.on_tick(_MOMENT)
    screen.on_button(Button.A)

    screen.on_tick(_MOMENT + timedelta(seconds=30))
    screen.on_button(Button.A)
    assert not handle.cancelled


def test_scanning_should_show_the_page_count_it_was_told(fonts: Fonts):
    """A different page count must produce different pixels.

    Asserting merely that something was drawn cannot fail -- the title bar
    alone satisfies it. Rendering two counts and requiring the readout area to
    differ is what proves the number reaches the glass rather than being held
    in a field nobody draws.
    """

    def render_with(page: int) -> bytes:
        handle = ScriptedScan(
            [[ScanStarted(at=_MOMENT), PageScanned(page=page, side=Side.BACK)]]
        )
        screen = _scanning(handle)
        screen.on_tick(_MOMENT + timedelta(seconds=5))
        canvas = Canvas.blank(fonts)
        screen.render(canvas)
        # The big readout only; excludes the title bar's elapsed clock, which
        # would differ anyway and make the comparison prove nothing.
        return canvas.image.crop((0, 70, config.DISPLAY_WIDTH, 120)).tobytes()

    assert render_with(7) != render_with(8)
    assert render_with(7) == render_with(7)


def test_done_should_return_home_on_any_button(fonts: Fonts):
    """Acknowledging the result goes back to the resting screen."""
    screen = DoneScreen(finished=_FINISHED, home=_home, link="http://x/s/a1b2c3d4")
    assert isinstance(screen.on_button(Button.X), StatusScreen)


def test_done_should_return_home_unattended(fonts: Fonts):
    """The panel must not sit on a finished job forever.

    A stale Done screen would suggest a scan just completed when it did not,
    which is worse than showing nothing.
    """
    screen = DoneScreen(
        finished=_FINISHED,
        home=_home,
        link="http://x/s/a1b2c3d4",
        linger=timedelta(seconds=10),
    )
    assert screen.on_tick(_MOMENT) is None
    assert screen.on_tick(_MOMENT + timedelta(seconds=5)) is None
    assert isinstance(screen.on_tick(_MOMENT + timedelta(seconds=11)), StatusScreen)


def test_error_should_wait_to_be_dismissed(fonts: Fonts):
    """A failure stays until acknowledged rather than timing out.

    The Notion build's requirement is that a failure is never silent; a message
    that clears itself while nobody is looking is silent.
    """
    screen = ErrorScreen(message="paper jam", home=_home)
    assert screen.on_tick(_MOMENT + timedelta(hours=1)) is None
    assert isinstance(screen.on_button(Button.Y), StatusScreen)


def test_error_led_should_be_red():
    """The lamp is red while a failure is showing.

    The expected colour is re-typed rather than read from the palette: pointing
    the assertion at the same expression the implementation uses would let a
    palette edit turn the lamp green with the test still passing, while its
    stated requirement says red.
    """
    screen = ErrorScreen(message="paper jam", home=_home)
    assert screen.led == Rgb.from_hex("#f85149")  # the error red


def test_error_should_not_silently_drop_a_long_message(fonts: Fonts):
    """An over-long failure is marked as truncated rather than just cut.

    This is the one screen whose job is explaining what went wrong, so losing
    the tail without a mark is the worst place in the application to do it.
    """
    long_message = " ".join(f"word{n}" for n in range(60))
    canvas = Canvas.blank(fonts)
    ErrorScreen(message=long_message, home=_home).render(canvas)
    lines = canvas.wrapped(
        long_message,
        canvas.fonts.detail,
        config.DISPLAY_WIDTH - 2 * config.MARGIN,
        3,
    )
    assert len(lines) == 3
    assert lines[-1].endswith("\N{HORIZONTAL ELLIPSIS}")
