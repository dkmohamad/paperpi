"""Retention, and the property that makes it safe to run unattended."""

import os
from datetime import datetime, timedelta
from pathlib import Path

from paperpi.models import Scan, ScanId
from paperpi.retention import expired
from paperpi.scans import scans_in

_NOW = datetime(2026, 9, 10, 12, 0)


def _write(directory: Path, name: str, age_days: float = 0) -> Path:
    path = directory / name
    path.write_bytes(b"%PDF-1.4\n" if name.endswith(".pdf") else b"hello\n")
    when = (_NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (when, when))
    return path


def _scan(scan_id: str, age_days: float) -> Scan:
    return Scan(
        scan_id=ScanId(scan_id),
        path=Path(f"2026-01-01-0000-{scan_id}.pdf"),
        size_bytes=100,
        modified=_NOW - timedelta(days=age_days),
    )


def test_listing_should_ignore_every_file_this_application_did_not_write(
    scan_dir: Path,
):
    """Only `.pdf` files whose name ends in a valid content id are visible.

    This is the whole safety argument for automated deletion. The drive is
    removable, so anyone can put a file on it, and the retention job runs
    unattended on a timer. A `find /mnt/scans -mtime +90 -delete` would take
    every one of the files below; going through this listing means retention
    can only ever remove documents the application itself produced.
    """
    keep = _write(scan_dir, "2026-09-10-1423-a1b2c3d4.pdf")
    _write(scan_dir, "holiday-photos.pdf")
    _write(scan_dir, "tax-return.pdf")
    _write(scan_dir, "README-test.txt")
    _write(scan_dir, "2026-09-10-1423-NOTHEXX.pdf")
    _write(scan_dir, "notes.PDF")

    listed = scans_in(scan_dir)
    assert [scan.path for scan in listed] == [keep]


def test_listing_should_return_newest_first(scan_dir: Path):
    """The index and the retention log both depend on this order."""
    _write(scan_dir, "2026-01-01-0000-aaaaaaaa.pdf", age_days=10)
    _write(scan_dir, "2026-01-01-0000-bbbbbbbb.pdf", age_days=1)
    _write(scan_dir, "2026-01-01-0000-cccccccc.pdf", age_days=5)
    assert [s.scan_id for s in scans_in(scan_dir)] == [
        "bbbbbbbb",
        "cccccccc",
        "aaaaaaaa",
    ]


def test_listing_an_absent_directory_should_be_empty_not_an_error(tmp_path: Path):
    """An unplugged drive yields nothing rather than raising.

    The index is served from the same listing, so a pulled drive should show an
    empty page, not a 500.
    """
    assert scans_in(tmp_path / "not-mounted") == []


def test_expiry_should_take_only_what_is_past_the_window():
    """Strictly older than the cutoff goes; anything younger stays."""
    stale = _scan("aaaaaaaa", age_days=120)
    fresh = _scan("bbbbbbbb", age_days=3)
    assert expired([stale, fresh], timedelta(days=90), _NOW) == [stale]


def test_a_scan_exactly_at_the_window_should_be_kept():
    """The boundary is inclusive of keeping.

    Asserted explicitly because an off-by-one here silently deletes a day of
    documents earlier than intended, and nothing would report it.
    """
    boundary = _scan("aaaaaaaa", age_days=90)
    assert expired([boundary], timedelta(days=90), _NOW) == []

    just_over = _scan("bbbbbbbb", age_days=90.001)
    assert expired([just_over], timedelta(days=90), _NOW) == [just_over]


def test_expiry_should_report_oldest_first():
    """So the journal reads chronologically when a batch is removed."""
    old = _scan("aaaaaaaa", age_days=300)
    older = _scan("bbbbbbbb", age_days=500)
    middle = _scan("cccccccc", age_days=100)
    result = expired([old, older, middle], timedelta(days=90), _NOW)
    assert [s.scan_id for s in result] == ["bbbbbbbb", "aaaaaaaa", "cccccccc"]


def test_nothing_expires_when_everything_is_recent():
    """A drive of fresh scans is left completely alone."""
    scans = [_scan("aaaaaaaa", 1), _scan("bbbbbbbb", 2)]
    assert expired(scans, timedelta(days=90), _NOW) == []
