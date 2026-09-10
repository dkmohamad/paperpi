"""The index page: what it says, and what it does not reach for."""

from datetime import datetime, timedelta
from pathlib import Path

from paperpi.models import Scan, ScanId
from paperpi.web import render_index

_NOW = datetime(2026, 9, 10, 16, 30)


def _scan(scan_id: str, when: datetime, size: int = 1000) -> Scan:
    return Scan(
        scan_id=ScanId(scan_id),
        path=Path(f"2026-09-10-1423-{scan_id}.pdf"),
        size_bytes=size,
        modified=when,
    )


def _path_for(scan_id: ScanId) -> str:
    return f"/s/{scan_id}"


def test_the_page_should_not_reference_anything_it_does_not_serve():
    """No webfont, no CDN, no external image, no script.

    The person opening this is usually standing beside the scanner on the house
    wifi, which is exactly where a phone may have no route to the internet. A
    page that waits on a remote asset hangs precisely when it is needed most, so
    self-containment is a requirement rather than a preference.
    """
    page = render_index([_scan("a1b2c3d4", _NOW)], _path_for, _NOW)
    assert "http://" not in page
    assert "https://" not in page
    assert "<script" not in page.lower()


def test_the_page_should_render_scans_in_the_order_given():
    """Ordering is the caller's, so the newest-first policy lives in one place.

    Re-sorting here would be a second copy of that policy, and the two would
    disagree the first time either changed.
    """
    scans = [
        _scan("aaaaaaaa", _NOW),
        _scan("bbbbbbbb", _NOW - timedelta(days=1)),
        _scan("cccccccc", _NOW - timedelta(days=2)),
    ]
    page = render_index(scans, _path_for, _NOW)
    positions = [page.index(f"/s/{s.scan_id}") for s in scans]
    assert positions == sorted(positions)


def test_the_page_should_say_so_when_there_is_nothing():
    """An empty drive gets a sentence, not an empty list.

    A bare page reads as a broken one, and the first time anyone opens this it
    will be empty.
    """
    page = render_index([], _path_for, _NOW)
    assert "No scans yet" in page
    assert "<li>" not in page


def test_the_page_should_escape_anything_that_came_off_the_disk():
    """A filename is attacker-influenced input once the drive is removable.

    Anyone can write a file to a USB stick and plug it in. The id is pattern-
    constrained, but escaping is asserted rather than assumed because the cost
    of being wrong is script injection into a page opened on a phone.
    """
    hostile = ScanId("a1b2c3d4")
    page = render_index(
        [_scan("a1b2c3d4", _NOW)],
        lambda _: '/s/"><script>alert(1)</script>',
        _NOW,
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    del hostile


def test_recent_scans_should_be_dated_the_way_someone_looking_for_one_thinks():
    """Today and Yesterday, then a date, then a year once it is not this one.

    A scan is usually retrieved minutes after it was made, so the common case
    should not make the reader parse a date to recognise it.
    """
    cases = {
        _NOW - timedelta(hours=2): "Today",
        _NOW - timedelta(days=1): "Yesterday",
        _NOW - timedelta(days=39): "2 Aug",
        _NOW - timedelta(days=283): "1 Dec 2025",
    }
    for when, expected in cases.items():
        page = render_index([_scan("a1b2c3d4", when)], _path_for, _NOW)
        assert expected in page, f"{when} should render as {expected!r}"


def test_a_single_scan_should_not_be_described_in_the_plural():
    """One document, not "1 documents"."""
    page = render_index([_scan("a1b2c3d4", _NOW)], _path_for, _NOW)
    assert "1 document<" in page or "1 document</p>" in page
    assert "1 documents" not in page
