"""The mock scanner: does it behave like a scan, and produce a real document."""

from datetime import datetime
from pathlib import Path

import pytest

from paperpi.adapters.scan_fake import FakeScanner
from paperpi.models import (
    PageScanned,
    ScanFailed,
    ScanFinished,
    ScanStarted,
    Side,
)

from .conftest import FakeClock

_START = datetime(2026, 9, 10, 14, 23, 0)


def test_scan_should_report_started_before_any_page(scan_dir: Path):
    """The first thing a run emits is that it began.

    The scanning screen shows "warming up" until a page arrives, so a run that
    reported a page first would skip that state entirely.
    """
    clock = FakeClock(_START)
    handle = FakeScanner(scan_dir=scan_dir, now=clock, pages=4).start()
    assert handle.poll() == [ScanStarted(at=_START)]


def test_scan_should_alternate_sides_as_pages_arrive(scan_dir: Path):
    """A duplex pass captures front then back, in that order.

    The screen shows which face is being captured, so the alternation is
    behaviour the display depends on rather than an implementation detail.
    """
    clock = FakeClock(_START)
    handle = FakeScanner(scan_dir=scan_dir, now=clock, pages=4).start()
    handle.poll()

    clock.advance(2.1)
    pages = [event for event in handle.poll() if isinstance(event, PageScanned)]
    assert [page.page for page in pages] == [1, 2, 3]
    assert [page.side for page in pages] == [Side.FRONT, Side.BACK, Side.FRONT]


def test_scan_should_write_a_real_pdf_named_after_its_own_content(scan_dir: Path):
    """The run ends with a document on disk whose name carries its id.

    The id is a content hash, so the filename cannot name a document that no
    longer matches it -- which is what lets the HTTP server resolve a link by
    globbing the directory instead of keeping an index that could drift.
    """
    clock = FakeClock(_START)
    handle = FakeScanner(scan_dir=scan_dir, now=clock, pages=3).start()
    handle.poll()
    clock.advance(10)

    finished = [e for e in handle.poll() if isinstance(e, ScanFinished)]
    assert len(finished) == 1
    result = finished[0]

    assert result.path.exists()
    assert result.path.read_bytes().startswith(b"%PDF")
    assert result.path.name.endswith(f"-{result.scan_id}.pdf")
    assert result.size_bytes == result.path.stat().st_size
    assert result.pages == 3


def test_scan_should_produce_nothing_further_once_finished(scan_dir: Path):
    """A terminal event is terminal; polling past it yields nothing.

    The screen transitions away on the terminal event, so a late duplicate
    would try to move a screen that is no longer showing.
    """
    clock = FakeClock(_START)
    handle = FakeScanner(scan_dir=scan_dir, now=clock, pages=2).start()
    handle.poll()
    clock.advance(10)
    handle.poll()
    assert handle.poll() == ()


def test_cancel_should_end_the_run_as_a_failure(scan_dir: Path):
    """Cancelling stops the run and reports why, rather than finishing quietly.

    A cancelled scan writes no document, so it must not reach the Done screen
    and offer a link to a file that was never created.
    """
    clock = FakeClock(_START)
    handle = FakeScanner(scan_dir=scan_dir, now=clock, pages=8).start()
    handle.poll()
    handle.cancel()
    clock.advance(1)

    events = handle.poll()
    assert any(isinstance(event, ScanFailed) for event in events)
    assert not list(scan_dir.iterdir())


def test_scanner_should_refuse_a_page_count_below_one(scan_dir: Path):
    """A scan of zero pages is a configuration mistake, not a valid run."""
    with pytest.raises(ValueError, match="at least one page"):
        FakeScanner(scan_dir=scan_dir, now=FakeClock(_START), pages=0)
