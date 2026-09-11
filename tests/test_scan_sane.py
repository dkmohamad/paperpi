"""Driving the scanner, with a scripted `scanimage` instead of one.

The stderr wording here is copied from real runs on the fi-6130, not invented:
the empty-feeder transcript is verbatim. That matters because the whole risk in
this adapter is misreading how a batch ends -- an ADF batch always finishes by
running out of paper, so the message that means "done" and the message that
means "you forgot the paper" are the same sentence, told apart only by the page
count.
"""

import re
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from paperpi.adapters.scan_sane import (
    SaneScanner,
    ScanProcess,
    _batch_total,
    _command,
    _page_scanned,
    _sane_error,
    _straighten,
    _wording,
    find_device,
    make_scanner_probe,
)
from paperpi.models import (
    PageScanned,
    ScanFailed,
    ScanFinished,
    ScannerLookup,
    ScanStarted,
    Side,
)

_STARTED = datetime(2026, 9, 11, 15, 30)

# Verbatim from the scanner, feeder empty.
_EMPTY_FEEDER = [
    "scanimage: rounded value of page-width from 210 to 210.01\n",
    "scanimage: rounded value of page-height from 297 to 296.994\n",
    "Scanning infinity pages, incrementing by 1, numbering from 1\n",
    "Scanning page 1\n",
    "scanimage: sane_start: Document feeder out of documents\n",
    "Batch terminated, 0 pages scanned\n",
]


def _batch(pages: int, ending: str = "Document feeder out of documents") -> list[str]:
    """A run that produced `pages` sides and then stopped for `ending`."""
    lines = [
        "scanimage: rounded value of page-width from 210 to 210.01\n",
        "Scanning infinity pages, incrementing by 1, numbering from 1\n",
    ]
    for page in range(1, pages + 1):
        lines.append(f"Scanning page {page}\n")
        lines.append(f"Scanned page {page}. (scanner status = 5)\n")
    lines.append(f"Scanning page {pages + 1}\n")
    lines.append(f"scanimage: sane_start: {ending}\n")
    lines.append(f"Batch terminated, {pages} pages scanned\n")
    return lines


# A4 at the scan resolution. Used where the page's real size is the point;
# elsewhere the fixtures are tiny, because most tests do not care.
_A4_PIXELS = (2480, 3508)


class _FakeProcess:
    """A `scanimage` that says what it was told to and writes the pages."""

    def __init__(
        self,
        command: Sequence[str],
        stderr: Iterable[str],
        write_pages: int,
        size: tuple[int, int] = (40, 56),
    ):
        self._stderr = iter(stderr)
        self.terminated = False
        self._returncode = 0
        for argument in command:
            if argument.startswith("--batch="):
                self._write(argument.removeprefix("--batch="), write_pages, size)

    @staticmethod
    def _write(pattern: str, pages: int, size: tuple[int, int]) -> None:
        for page in range(1, pages + 1):
            # Tiny by default, but a real 1-bit TIFF, so Pillow does real work.
            Image.new("1", size, 1).save(pattern % page, format="TIFF")

    @property
    def stderr(self) -> Iterable[str] | None:
        return self._stderr

    def wait(self) -> int:
        return self._returncode

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True


def _spawning(
    stderr: Iterable[str], write_pages: int, size: tuple[int, int] = (40, 56)
):
    """A spawn that always produces the same scripted run.

    Annotated as returning `ScanProcess` on purpose: that is what makes pyright
    check the double against the contract it stands in for, the way
    `tests/conftest.py` does for the other ports.
    """

    def spawn(command: Sequence[str]) -> ScanProcess:
        return _FakeProcess(command, stderr, write_pages, size)

    return spawn


def _drain(handle: Any, limit: float = 5.0) -> list[Any]:
    """Collect events until a terminal one arrives.

    Fails loudly on a timeout rather than returning what it has. A scan that
    never reaches a terminal event is this adapter's worst failure -- the panel
    sits on the scanning screen forever -- so it should be named by the test,
    not left to surface as an IndexError somewhere downstream.
    """
    events: list[Any] = []
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        events.extend(handle.poll())
        if any(isinstance(e, ScanFinished | ScanFailed) for e in events):
            return events
        time.sleep(0.01)
    pytest.fail(f"no terminal event within {limit}s; got {events!r}")


# --- the parsing, which is where the risk lives ----------------------------


def test_only_a_finished_page_should_count():
    """`Scanning page N` is printed before the attempt, not after it.

    The empty-feeder transcript proves why this matters: it says "Scanning
    page 1" and then produces nothing at all. Counting that line would report
    a page that does not exist.
    """
    assert _page_scanned("Scanned page 3. (scanner status = 5)") == 3
    assert _page_scanned("Scanning page 3") is None


def test_the_batch_total_should_be_read_from_the_summary():
    """The authoritative count, and the thing that separates done from empty."""
    assert _batch_total("Batch terminated, 6 pages scanned") == 6
    assert _batch_total("Batch terminated, 0 pages scanned") == 0
    assert _batch_total("Batch terminated, 1 page scanned") == 1


def test_the_page_size_rounding_notice_is_not_a_failure():
    """The backend rounds to its own step and says so on every single run.

    Treated as an error it would fail every scan, which is the most expensive
    possible reading of a line that means nothing.
    """
    assert (
        _sane_error("scanimage: rounded value of page-width from 210 to 210.01") is None
    )


def test_a_real_diagnostic_should_yield_its_sane_status():
    """The call prefix is stripped; the status text is what gets translated."""
    assert (
        _sane_error("scanimage: sane_start: Document feeder jammed")
        == "Document feeder jammed"
    )


def test_an_unmapped_status_should_reach_the_display_unchanged():
    """SANE's own wording beats a vague catch-all, and beats silence."""
    assert _wording("Document feeder jammed") == "paper jam or double feed"
    assert _wording("Some new SANE status") == "Some new SANE status"


def test_the_command_should_pin_a4_and_the_device():
    """Two things that fail quietly if wrong.

    The backend's own page-size defaults are US Letter, and 279.4 mm is 17.6 mm
    shorter than A4 -- so an unset page height silently cuts the bottom off
    every page. And an unpinned device lets SANE choose, which on this box
    could mean the printer's flatbed.
    """
    command = _command("fujitsu:fi-6130dj:000000", "/tmp/p%04d.tif")
    assert "-d" in command
    assert "fujitsu:fi-6130dj:000000" in command
    assert command[command.index("--page-height") + 1] == "297"
    assert command[command.index("--page-width") + 1] == "210"
    assert command[command.index("--source") + 1] == "ADF Duplex"


# --- the run as a whole ----------------------------------------------------


def test_a_normal_batch_should_finish_with_a_written_pdf(scan_dir: Path):
    """Six sides in, one PDF out, named the way the reader expects."""
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(6), write_pages=6),
    )
    events = _drain(scanner.start())

    assert isinstance(events[0], ScanStarted)
    assert [e.page for e in events if isinstance(e, PageScanned)] == [1, 2, 3, 4, 5, 6]
    finished = events[-1]
    assert isinstance(finished, ScanFinished)
    assert finished.pages == 6
    assert finished.path.exists()
    assert finished.path.suffix == ".pdf"


def test_duplex_sides_should_alternate(scan_dir: Path):
    """Odd sides are fronts and even ones backs, which is what the panel shows."""
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(4), write_pages=4),
    )
    sides = [e.side for e in _drain(scanner.start()) if isinstance(e, PageScanned)]
    assert sides == [Side.FRONT, Side.BACK, Side.FRONT, Side.BACK]


def test_an_empty_feeder_should_fail_and_write_nothing(scan_dir: Path):
    """Same closing message as a successful scan, zero pages, so: a failure."""
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_EMPTY_FEEDER, write_pages=0),
    )
    events = _drain(scanner.start())

    assert isinstance(events[-1], ScanFailed)
    assert events[-1].message == "no paper in the feeder"
    assert list(scan_dir.glob("*.pdf")) == []


def test_a_jam_should_discard_the_partial_document(scan_dir: Path):
    """A jam mid-batch leaves pages already scanned, and they are thrown away.

    A truncated PDF that looks complete is worse than no PDF: nobody re-feeds
    a document they believe was captured.
    """
    # The backend reports a double feed as a jam too, which is why the wording
    # covers both: two sheets through the rollers at once loses a page as
    # surely as a jam does, and the person has to go and look either way.
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(2, ending="Document feeder jammed"), write_pages=2),
    )
    events = _drain(scanner.start())

    assert isinstance(events[-1], ScanFailed)
    assert events[-1].message == "paper jam or double feed"
    assert not any(isinstance(e, ScanFinished) for e in events)
    assert list(scan_dir.glob("*.pdf")) == []


def test_poll_should_return_immediately(scan_dir: Path):
    """It is called from the render loop, so it may never wait on the scanner."""
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(3), write_pages=3),
    )
    handle = scanner.start()
    began = time.monotonic()
    handle.poll()
    assert time.monotonic() - began < 0.05


def test_find_device_should_pick_the_scanner_not_the_printer():
    """Both are SANE devices on this box; only one is the document scanner.

    The printer's flatbed answers SANE too, and on a real listing it can come
    first -- so taking the first device would quietly scan on the wrong
    machine.
    """
    listing = (
        "epsonds:libusb:001:003\nfujitsu:fi-6130dj:000000\nepson2:net:192.168.1.199\n"
    )
    assert find_device(listing=lambda: listing).device == "fujitsu:fi-6130dj:000000"


def test_find_device_should_report_nothing_rather_than_raise():
    """No scanner is a state the display shows, not an error to handle."""

    def refuse() -> str:
        raise OSError("scanimage is not installed")

    found = find_device(listing=refuse)
    assert found.device == ""
    assert found.installed is True


def test_find_device_should_report_nothing_when_only_others_are_present():
    """An empty answer and a wrong-backend answer mean the same thing here."""
    assert find_device(listing=lambda: "epsonds:libusb:001:003\n").device == ""
    assert find_device(listing=lambda: "").device == ""


def test_the_pdf_should_be_a4_not_whatever_the_pixels_imply(scan_dir: Path):
    """The page size has to survive the trip from scanner to document.

    A PDF has no idea what a pixel is: page size comes from the image size
    divided by the resolution written alongside it. Omit the resolution and
    every page is assembled at 72 dpi, which makes an A4 scan come out roughly
    four times too large -- readable, printable onto the wrong paper, and
    wrong in a way nothing else in the system would notice.
    """
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(2), write_pages=2, size=_A4_PIXELS),
    )
    finished = _drain(scanner.start())[-1]
    assert isinstance(finished, ScanFinished)

    # A4 is 595.28 x 841.89 points. Pillow rounds, so allow a point either way.
    boxes = re.findall(rb"/MediaBox\s*\[([^\]]+)\]", finished.path.read_bytes())
    assert boxes, "the PDF declares no page size at all"
    for box in boxes:
        _, _, width, height = (float(value) for value in box.split())
        assert abs(width - 595.28) < 1.5, f"width {width} is not A4"
        assert abs(height - 841.89) < 1.5, f"height {height} is not A4"


class _BlockingStderr:
    """Stderr that stalls mid-scan until the test lets it continue."""

    def __init__(self, before: list[str], after: list[str]):
        self.reached = threading.Event()
        self.release = threading.Event()
        self._before = before
        self._after = after

    def __iter__(self) -> Iterator[str]:
        yield from self._before
        self.reached.set()
        self.release.wait(timeout=5)
        yield from self._after


def test_poll_should_not_wait_for_the_scanner(scan_dir: Path):
    """The render loop calls this; it may never wait on a subprocess.

    The scan is genuinely stalled when `poll()` is called here, which is what
    makes the assertion mean anything -- a double whose output is a list can
    never block, so a test using one proves nothing about this property.
    """
    stderr = _BlockingStderr(
        before=["Scanning page 1\n", "Scanned page 1. (scanner status = 5)\n"],
        after=[
            "scanimage: sane_start: Document feeder out of documents\n",
            "Batch terminated, 1 pages scanned\n",
        ],
    )
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(stderr, write_pages=1),
    )
    handle = scanner.start()
    assert stderr.reached.wait(timeout=5), "the worker never started scanning"

    began = time.monotonic()
    handle.poll()
    waited = time.monotonic() - began

    stderr.release.set()
    _drain(handle)
    assert waited < 0.05, f"poll() blocked for {waited:.3f}s while a scan was running"


def test_cancel_should_end_the_run_as_a_failure(scan_dir: Path):
    """Cancelling takes the same path as any other failure, and terminates it."""
    stderr = _BlockingStderr(before=["Scanning page 1\n"], after=[])
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(stderr, write_pages=0),
    )
    handle = scanner.start()
    assert stderr.reached.wait(timeout=5)

    handle.cancel()
    stderr.release.set()
    events = _drain(handle)

    assert isinstance(events[-1], ScanFailed)
    assert events[-1].message == "cancelled at the panel"
    assert not any(isinstance(e, ScanFinished) for e in events)
    assert list(scan_dir.glob("*.pdf")) == []


def test_nothing_should_follow_a_terminal_event(scan_dir: Path):
    """The contract says a terminal event is final, so poll drains empty after."""
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(2), write_pages=2),
    )
    handle = scanner.start()
    _drain(handle)
    time.sleep(0.1)
    assert list(handle.poll()) == []


def test_the_page_count_should_describe_the_document_not_the_transcript(scan_dir: Path):
    """Three things could supply this number, and they can disagree.

    The scanner's summary counts a page it started; the files on disk are what
    actually became a document. Telling someone "6 pages" over a 5-page PDF is
    the kind of small lie that makes the rest untrustworthy.
    """
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        # The transcript claims six; only five pages ever reached the disk.
        spawn=_spawning(_batch(6), write_pages=5),
    )
    finished = _drain(scanner.start())[-1]
    assert isinstance(finished, ScanFinished)
    assert finished.pages == 5


def test_an_unrecognised_advisory_should_not_cost_us_the_document(scan_dir: Path):
    """Paper already through the machine is not thrown away on a guess.

    A future release adding a harmless closing diagnostic must not turn a good
    scan into a failure; only a status we recognise as a fault does that.
    """
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(
            _batch(4, ending="Some advisory nobody has seen before"), write_pages=4
        ),
    )
    finished = _drain(scanner.start())[-1]
    assert isinstance(finished, ScanFinished)
    assert finished.pages == 4


def test_the_probe_should_answer_at_once_and_look_behind_itself():
    """The status row asks this twice a second; it must never wait.

    The first answer is nothing, because nothing is known yet. What matters is
    that asking is free and the answer arrives without anyone blocking on it.
    """
    looking = threading.Event()

    def slow() -> ScannerLookup:
        looking.wait(timeout=5)
        return ScannerLookup(installed=True, device="fujitsu:fi-6130dj:000000")

    probe = make_scanner_probe(find=slow)
    began = time.monotonic()
    assert probe().device == ""
    assert time.monotonic() - began < 0.05

    looking.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not probe().device:
        time.sleep(0.01)
    assert probe().device == "fujitsu:fi-6130dj:000000"


def test_a_failed_look_should_be_retried_not_remembered():
    """Access to a scanner is granted asynchronously when it is plugged in.

    So "on the bus, not yet reachable" is the ordinary state at boot. Caching
    that first `None` forever would leave the row reading "no driver" until
    somebody restarted the service.
    """
    answers = iter(["", "fujitsu:fi-6130dj:000000"])
    probe = make_scanner_probe(
        find=lambda: ScannerLookup(installed=True, device=next(answers, "")),
        retry_after=0.0,
    )

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not probe().device:
        time.sleep(0.01)
    assert probe().device == "fujitsu:fi-6130dj:000000"


def test_a_page_should_be_turned_the_right_way_up(tmp_path: Path):
    """The scanner's paper path inverts every page, so the adapter turns it back.

    Measured rather than asserted against a flag: ink written into the top of
    the image must end up in the bottom of the file.
    """
    page = tmp_path / "p0001.tif"
    image = Image.new("1", (100, 200), 1)
    for y in range(0, 40):
        for x in range(10, 90):
            image.putpixel((x, y), 0)  # a dark band across the top
    image.save(page, format="TIFF")

    _straighten(page)

    with Image.open(page) as turned:
        grey = turned.convert("L")
        top = sum(grey.crop((0, 0, 100, 40)).histogram()[:128])
        bottom = sum(grey.crop((0, 160, 100, 200)).histogram()[:128])
    assert bottom > top, "the page was not turned the right way up"


def test_pages_should_keep_the_order_the_scanner_fed_them(scan_dir: Path):
    """No reordering, and that is a decision rather than an omission.

    The feeder takes from the bottom of the stack and the operator's guide says
    to load face-down -- which flips the document, putting page one at the
    bottom, which is where the feeder starts. The two cancel. Reversing in
    software looks right for a stack loaded face-up and is wrong for anyone
    following the manual, which is how it was got wrong the first time.
    """
    scanner = SaneScanner(
        scan_dir=scan_dir,
        now=lambda: _STARTED,
        device="fujitsu:x",
        spawn=_spawning(_batch(4), write_pages=4),
    )
    events = _drain(scanner.start())
    assert [e.page for e in events if isinstance(e, PageScanned)] == [1, 2, 3, 4]
    finished = events[-1]
    assert isinstance(finished, ScanFinished)
    assert finished.pages == 4


def test_a_failed_look_should_not_be_retried_on_every_call():
    """Asking wakes the scanner, so asking too often is a hardware cost.

    Listing SANE devices issues a driver command, which the operator's guide
    lists among the things that bring the scanner out of power save. A probe
    that retried on every call would hold the scanning lamp lit for as long as
    the box was running -- and that lamp is a cold-cathode tube with a finite
    life, no counter, and no place in the manual's consumables table.

    The calls here are spaced rather than tight. A tight loop proves nothing:
    the in-flight guard alone blocks re-entry, so the test passes with the
    backoff removed. Only elapsed time between calls exercises it -- which is
    also what the real caller does, sampling every couple of seconds.
    """
    calls = 0

    def count() -> ScannerLookup:
        nonlocal calls
        calls += 1
        return ScannerLookup(installed=True)

    probe = make_scanner_probe(find=count, retry_after=60.0)
    probe()

    deadline = time.monotonic() + 5
    while calls == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls == 1, "the first look never happened"

    for _ in range(10):
        probe()
        time.sleep(0.05)
    assert calls == 1, (
        f"the probe asked {calls} times in half a second; at that rate it would "
        f"hold the scanning lamp lit indefinitely"
    )
