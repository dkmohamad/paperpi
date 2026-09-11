"""The filename contract, tested from both ends.

Writing a scan and finding one again are two halves of a single rule, and the
failure mode when they disagree is silent: a scan under the wrong name still
serves, and its QR still resolves, but retention never sees it and the drive
fills up with documents nobody asked to keep. Nothing raises, so only a test
across the seam catches it.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

from paperpi.retention import expired
from paperpi.scans import ID, id_from, identify, scans_in, write_scan

_STARTED = datetime(2026, 9, 11, 14, 23)


def _write(scan_dir: Path, data: bytes, at: datetime = _STARTED):
    return write_scan(
        data=data,
        scan_dir=scan_dir,
        started_at=at,
        pages=4,
        duration=timedelta(seconds=30),
    )


def test_a_written_scan_should_be_found_by_the_listing(scan_dir: Path):
    """The round trip the whole contract exists for."""
    finished = _write(scan_dir, b"%PDF-1.4 pretend")
    listed = scans_in(scan_dir)
    assert [scan.scan_id for scan in listed] == [finished.scan_id]
    assert listed[0].path == finished.path


def test_a_written_scan_should_reach_retention(scan_dir: Path):
    """The chain that actually matters: written here, swept there.

    Retention only deletes what the listing returns, so a naming change that
    broke this would leave every real scan on the drive forever, reported by
    nothing.
    """
    finished = _write(scan_dir, b"%PDF-1.4 old document")
    much_later = _STARTED + timedelta(days=365)
    doomed = expired(scans_in(scan_dir), older_than=timedelta(days=90), now=much_later)
    assert [scan.scan_id for scan in doomed] == [finished.scan_id]


def test_the_id_in_the_name_should_be_servable(scan_dir: Path):
    """A written file must carry an id the URL route will accept.

    The route and the filename share one pattern precisely so this holds; if
    they were spelled separately, every fresh scan's QR would 404.
    """
    finished = _write(scan_dir, b"%PDF-1.4 linkable")
    assert re.fullmatch(ID, finished.scan_id)
    assert id_from(finished.path) == finished.scan_id


def test_identical_documents_should_get_identical_ids(scan_dir: Path):
    """Content-addressed means the handle follows the bytes, not the clock."""
    first = _write(scan_dir, b"%PDF-1.4 same", at=_STARTED)
    second = _write(scan_dir, b"%PDF-1.4 same", at=_STARTED + timedelta(hours=3))
    assert first.scan_id == second.scan_id
    # Different timestamps, so both files exist and neither overwrote the other.
    assert first.path != second.path


def test_different_documents_should_get_different_ids():
    """The obverse, without which the id would identify nothing."""
    assert identify(b"one") != identify(b"two")


def test_a_file_we_did_not_write_should_be_invisible(scan_dir: Path):
    """The safety property retention leans on.

    Anything on the drive that this application did not produce must not appear
    in the listing, because everything in that listing is a deletion candidate.
    """
    (scan_dir / "holiday-photos.pdf").write_bytes(b"%PDF-1.4 not ours")
    (scan_dir / "notes.txt").write_bytes(b"shopping list")
    _write(scan_dir, b"%PDF-1.4 ours")

    listed = scans_in(scan_dir)
    assert len(listed) == 1
    assert id_from(scan_dir / "holiday-photos.pdf") is None
