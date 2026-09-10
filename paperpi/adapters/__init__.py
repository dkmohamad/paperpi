"""Concrete implementations of the ports.

Only the adapters that need nothing beyond the package's own dependencies are
re-exported here. `preview` (pygame) and `hat` (st7789, gpiozero) are imported
directly by the composition root instead: each needs a dependency the other
machine does not have, so importing this package must not pull either in.
"""

from .printer_cups import CupsQueues
from .scan_fake import FakeScanner
from .status_linux import LinuxStatus

__all__ = ["CupsQueues", "FakeScanner", "LinuxStatus"]
