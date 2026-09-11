"""What a finished scan is called, and how one is found again.

The filename is a contract rather than a convention. `write_scan` puts a hash
of the document's own bytes into the stem, `id_from` reads it back out, and
`scans_in` returns only the files that match. Retention is built on that list,
which is what stops it deleting anything this application did not write.

That also makes the naming load-bearing in a way worth stating plainly: a scan
written under a slightly different name would serve correctly and resolve its
QR correctly, while never being swept -- and nothing would report it. So the
writing half and the reading half live in one module, where a second writer
cannot drift from the reader.
"""

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path

from .models import Scan, ScanFinished, ScanId

__all__ = ["ID", "id_from", "identify", "scans_in", "write_scan"]

# What a scan id looks like. Shared with the URL route in `serve`, because the
# id in a link and the id in a filename are the same thing: spelled twice they
# drift, and the failure is every link silently 404ing.
ID = r"[0-9a-f]{4,32}"

_ID_PATTERN = re.compile(rf"^{ID}$")

# Long enough that two different documents colliding is not a practical
# concern, short enough that the QR stays sparse and scans from across a desk.
_ID_LENGTH = 8


def identify(data: bytes) -> ScanId:
    """Derive a scan's handle from its own content.

    Content-addressed rather than sequential or random, so the handle is stable
    across runs and cannot name a document that no longer matches it.

    Args:
        data: The finished PDF's bytes.

    Returns:
        A short lowercase hex id.
    """
    return ScanId(hashlib.sha256(data).hexdigest()[:_ID_LENGTH])


def write_scan(
    *,
    data: bytes,
    scan_dir: Path,
    started_at: datetime,
    pages: int,
    duration: timedelta,
) -> ScanFinished:
    """Write a finished PDF under the name the rest of the system expects.

    The single place a scan file is created. Both the real scanner and the
    stand-in call it, so neither can invent a name the reader does not know.

    Args:
        data: The finished PDF's bytes.
        scan_dir: Where scans are written.
        started_at: When the run began; this dates the file.
        pages: How many pages the run produced.
        duration: How long it took.

    Returns:
        The event describing the written document.
    """
    scan_id = identify(data)
    # The timestamp is for a human reading a directory listing; the id is what
    # anything else matches on, which is why it comes last in the stem.
    path = scan_dir / f"{started_at:%Y-%m-%d-%H%M}-{scan_id}.pdf"
    scan_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return ScanFinished(
        scan_id=scan_id,
        path=path,
        pages=pages,
        size_bytes=len(data),
        duration=duration,
    )


def id_from(path: Path) -> ScanId | None:
    """Recover a scan's id from its filename, or None if it carries none."""
    candidate = path.stem.rsplit("-", 1)[-1]
    return ScanId(candidate) if _ID_PATTERN.match(candidate) else None


def scans_in(directory: Path) -> list[Scan]:
    """List the documents this application produced, newest first.

    Only files matching the naming above -- a `.pdf` whose stem ends in a valid
    content-hash id -- are returned. Anything else on the drive is invisible
    here, which is what lets retention delete from this list without risk of
    taking a file somebody put there by hand.

    Args:
        directory: Where scans are written.

    Returns:
        Possibly empty. Files that vanish mid-listing are skipped rather than
        raising: this is removable media and can be pulled at any moment.
    """
    scans: list[Scan] = []
    for path in directory.glob("*.pdf"):
        scan_id = id_from(path)
        if scan_id is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        scans.append(
            Scan(
                scan_id=scan_id,
                path=path,
                size_bytes=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime),
            )
        )
    return sorted(scans, key=lambda scan: scan.modified, reverse=True)
