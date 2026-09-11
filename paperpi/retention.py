"""Deleting scans once they are old enough to be clutter.

Built on `scans.scans_in`, and that is the whole safety argument. That function
only returns files this application wrote -- a `.pdf` whose name ends in a valid
content-hash id -- so nothing else on the drive is even visible here. A plain
`find /mnt/scans -mtime +90 -delete` would have taken anything anyone had put
there, which on removable media is a real prospect.

Run from a systemd timer rather than in the application, so retention still
happens on a box where the display has crashed, and so a run is visible in
`systemctl list-timers` and its outcome in the journal.
"""

import argparse
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from . import config
from .models import Scan
from .scans import scans_in

__all__ = ["expired", "main"]

logger = logging.getLogger(__name__)

_DEFAULT_DAYS = 90


def expired(scans: Sequence[Scan], older_than: timedelta, now: datetime) -> list[Scan]:
    """Select the scans old enough to remove.

    Args:
        scans: Candidates.
        older_than: Maximum age to keep.
        now: Current time, injected so the boundary is testable.

    Returns:
        Those strictly older than the cutoff, oldest first so a log of the
        deletions reads chronologically.
    """
    cutoff = now - older_than
    return sorted(
        (scan for scan in scans if scan.modified < cutoff),
        key=lambda scan: scan.modified,
    )


def main() -> None:
    """Delete scans past the retention window."""
    parser = argparse.ArgumentParser(
        prog="paperpi.retention", description="Remove scans older than N days."
    )
    parser.add_argument(
        "--scan-dir", type=Path, default=config.SCAN_DIR, help="where scans live"
    )
    parser.add_argument(
        "--days", type=int, default=_DEFAULT_DAYS, help="how long to keep a scan"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be removed, and remove nothing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if args.days < 1:
        raise ValueError(f"retention must be at least a day, got {args.days}")

    scans = scans_in(args.scan_dir)
    stale = expired(scans, timedelta(days=args.days), datetime.now())

    if not stale:
        logger.info(
            "nothing to remove: %d scan(s) in %s, none older than %d days",
            len(scans),
            args.scan_dir,
            args.days,
        )
        return

    freed = 0
    for scan in stale:
        if args.dry_run:
            logger.info("would remove %s (%s)", scan.path.name, scan.modified.date())
            freed += scan.size_bytes
            continue
        try:
            scan.path.unlink()
        except OSError:
            # One unreadable file should not stop the rest being tidied.
            logger.exception("could not remove %s", scan.path)
            continue
        logger.info("removed %s (%s)", scan.path.name, scan.modified.date())
        freed += scan.size_bytes

    verb = "would free" if args.dry_run else "freed"
    logger.info("%s %d bytes across %d scan(s)", verb, freed, len(stale))


if __name__ == "__main__":
    main()
