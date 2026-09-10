"""The vocabulary the rest of the package speaks.

Peripheral readiness, the events a scan emits while it runs, and the colours
that signal both. Nothing here performs IO or knows what a display is, so these
types are equally usable from a test, the preview window and the Pi.

Scan progress is modelled as a stream of event variants rather than a
percentage. A sheet feeder does not know how many pages it holds until the
hopper empties, so a completion fraction would be a guess; a page count and a
side are things we actually know.
"""

import operator
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from ipaddress import IPv4Address
from pathlib import Path
from typing import NewType, Self

__all__ = [
    "Button",
    "FaultSeverity",
    "LedChannel",
    "Network",
    "PageScanned",
    "Peripheral",
    "PeripheralKind",
    "Peripherals",
    "PrintQueue",
    "QueueConnection",
    "QueueFault",
    "QueueState",
    "Readiness",
    "Rgb",
    "Scan",
    "ScanEvent",
    "ScanFailed",
    "ScanFinished",
    "ScanId",
    "ScanStarted",
    "Side",
    "Storage",
    "SystemStatus",
]

# Short, URL-safe handle for a finished scan. Kept distinct from the filename
# because it is what goes in the QR code, where length costs legibility.
ScanId = NewType("ScanId", str)


@dataclass(frozen=True, slots=True)
class Rgb:
    """An 8-bit-per-channel colour.

    Attributes:
        red: 0-255.
        green: 0-255.
        blue: 0-255.
    """

    red: int
    green: int
    blue: int

    def __post_init__(self):
        # Named explicitly rather than via getattr on string literals: a field
        # rename should be a type error, not a runtime surprise.
        for name, value in (
            ("red", self.red),
            ("green", self.green),
            ("blue", self.blue),
        ):
            if not 0 <= value <= 255:
                raise ValueError(f"{name} must be 0-255, got {value}")

    @classmethod
    def from_hex(cls, value: str) -> Self:
        """Build a colour from a `#rrggbb` string.

        Args:
            value: Six hex digits, with or without a leading `#`.

        Returns:
            The colour.

        Raises:
            ValueError: If the string is not six hex digits.
        """
        digits = value.removeprefix("#")
        if len(digits) != 6:
            raise ValueError(f"expected #rrggbb, got {value!r}")
        return cls(
            red=int(digits[0:2], 16),
            green=int(digits[2:4], 16),
            blue=int(digits[4:6], 16),
        )

    def as_tuple(self) -> tuple[int, int, int]:
        """Return the colour in the form Pillow's drawing calls take."""
        return (self.red, self.green, self.blue)

    def as_fractions(self) -> tuple[float, float, float]:
        """Return the colour as 0.0-1.0 channels, which is what the LED takes."""
        return (self.red / 255, self.green / 255, self.blue / 255)

    def dimmed(self, factor: float) -> Self:
        """Return this colour scaled toward black.

        Args:
            factor: 0.0 gives black, 1.0 gives the colour unchanged.

        Returns:
            The scaled colour.
        """
        return type(self)(
            red=round(self.red * factor),
            green=round(self.green * factor),
            blue=round(self.blue * factor),
        )


class Button(StrEnum):
    """The four buttons along the edge of the display."""

    A = "a"
    B = "b"
    X = "x"
    Y = "y"


class LedChannel(StrEnum):
    """The three channels of the RGB status lamp."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Side(StrEnum):
    """Which face of a sheet a duplex pass just captured."""

    FRONT = "front"
    BACK = "back"


class Readiness(StrEnum):
    """How usable a peripheral is right now.

    The four non-ready states are deliberately distinct. ABSENT is an expected
    resting state -- nothing is plugged in. UNCONFIGURED means the device is
    attached but nothing can drive it yet, which is a setup task rather than a
    fault. BUSY means it is working. ERROR means it is attached and failing.
    Collapsing these would make the lamp say "something" without saying what.
    """

    READY = "ready"
    BUSY = "busy"
    ABSENT = "absent"
    UNCONFIGURED = "unconfigured"
    ERROR = "error"

    @property
    def severity(self) -> int:
        """Rank for choosing the worst state across several peripherals."""
        return _SEVERITY[self]


class PeripheralKind(StrEnum):
    """The devices the status screen reports on, in display order."""

    SCANNER = "scanner"
    PRINTER = "printer"
    STORAGE = "storage"

    @property
    def label(self) -> str:
        """Short uppercase name as shown on the display."""
        return self.value.upper()


@dataclass(frozen=True, slots=True)
class Peripheral:
    """One device's state as the status screen shows it.

    Attributes:
        kind: Which device this describes.
        readiness: How usable it is.
        detail: One short line of evidence -- a model name, or why it is not
            ready. Shown verbatim, so it must already be display-length.
    """

    kind: PeripheralKind
    readiness: Readiness
    detail: str


class Peripherals(Collection[Peripheral]):
    """The peripherals in the fixed order the status screen renders them.

    A Collection, not a Sequence: nothing indexes or slices this -- the screen
    walks it in order and the lamp wants the worst of it. Claiming Sequence
    would advertise an interface no caller uses and require overloading
    __getitem__ for slices to satisfy the type checker.
    """

    def __init__(self, items: Iterable[Peripheral] = ()):
        self._items = tuple(items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Peripheral]:
        return iter(self._items)

    def __contains__(self, item: object) -> bool:
        return item in self._items

    @property
    def worst(self) -> Readiness:
        """The most severe readiness present, for the status LED.

        Returns:
            The worst readiness, or READY when there are no peripherals.
        """
        if not self._items:
            return Readiness.READY
        return max(
            (item.readiness for item in self._items),
            key=operator.attrgetter("severity"),
        )


class QueueState(StrEnum):
    """What a print queue is doing, as IPP reports it.

    IPP models this as an integer (RFC 8011, printer-state): 3 idle,
    4 processing, 5 stopped. Naming the three here keeps that mapping inside
    the adapter that speaks IPP, rather than letting bare numbers reach the
    display.
    """

    IDLE = "idle"
    PRINTING = "printing"
    STOPPED = "stopped"


class QueueConnection(StrEnum):
    """How a queue reaches the thing it prints on.

    The distinction the display needs is whether a queue drives the printer
    plugged into this machine or something elsewhere, so that adding a second
    queue for a printer in another room cannot change what this box reports
    about its own. Naming it here means the URI scheme that decides it stays
    inside the adapter that speaks to the print server.
    """

    USB = "usb"
    NETWORK = "network"
    OTHER = "other"


class FaultSeverity(StrEnum):
    """How much a reported fault wants a human.

    IPP suffixes every state reason with one of these, and the suffix is
    per-reason: a queue can report a warning and an error at once. Discarding
    it would leave the faults unordered, and something downstream would then
    pick by list position -- which is how "ink low" gets displayed while the
    printer is jammed.
    """

    REPORT = "report"
    WARNING = "warning"
    ERROR = "error"

    @property
    def rank(self) -> int:
        """Order for choosing the fault most worth showing."""
        return _FAULT_RANK[self]


@dataclass(frozen=True, slots=True)
class QueueFault:
    """One thing a print queue is complaining about.

    Attributes:
        keyword: The bare IPP keyword -- media-empty, media-jam, cover-open.
            Standardised, so it can be matched on, unlike translated prose.
        severity: How loudly IPP was complaining about this one.
    """

    keyword: str
    severity: FaultSeverity


@dataclass(frozen=True, slots=True)
class PrintQueue:
    """A configured print queue, as the print server reports it.

    Attributes:
        name: The queue name, which is also what clients see advertised.
        connection: Whether this queue drives the locally attached printer or
            something across the network.
        state: What the queue is doing now.
        accepting: Whether it will take new jobs. A queue can be idle and
            still refuse work, which is a different fault from being stopped,
            so the two are not collapsed.
        faults: Everything it is complaining about, in the order reported.
    """

    name: str
    connection: QueueConnection
    state: QueueState
    accepting: bool
    faults: tuple[QueueFault, ...]

    @property
    def worst_fault(self) -> QueueFault | None:
        """The fault most worth a line on a display that has room for one.

        Ranked by severity rather than taken from the front of the list: IPP
        does not order state reasons by importance, so the first one is an
        accident of the server's iteration.

        Returns:
            None when nothing is wrong.
        """
        return max(self.faults, key=lambda fault: fault.severity.rank, default=None)


@dataclass(frozen=True, slots=True)
class Network:
    """The Pi's own reachability, shown so a headless box can be found.

    Attributes:
        interface: Kernel name, e.g. `eth0`.
        address: The IPv4 address, or None when the link has none.
    """

    interface: str
    address: IPv4Address | None

    @property
    def up(self) -> bool:
        """Whether the interface has an address to be reached on."""
        return self.address is not None

    def __str__(self) -> str:
        if self.address is None:
            return f"{self.interface} down"
        return f"{self.interface} {self.address}"


@dataclass(frozen=True, slots=True)
class Storage:
    """Where scans are written, and how much room is left.

    Attributes:
        path: The scan directory.
        free_bytes: Free space on its filesystem, or None if unavailable.
        mounted: Whether `path` is a mountpoint of its own rather than a
            directory on the root filesystem.
    """

    path: Path
    free_bytes: int | None
    mounted: bool


@dataclass(frozen=True, slots=True)
class SystemStatus:
    """Everything the resting screen shows, sampled at one instant.

    Attributes:
        network: The Pi's reachability.
        peripherals: Device states, in display order.
        storage: The scan destination.
        temperature_c: SoC temperature, or None if unreadable.
    """

    network: Network
    peripherals: Peripherals
    storage: Storage
    temperature_c: float | None


@dataclass(frozen=True, slots=True)
class Scan:
    """A finished document as it sits on disk.

    Distinct from ScanFinished, which describes the run that produced it: this
    is what a later reader finds by listing the directory, with no memory of
    the job.

    Attributes:
        scan_id: The handle it is served under, recovered from the filename.
        path: Where it lives.
        size_bytes: Size on disk.
        modified: Last-modified time, used for ordering and display.
    """

    scan_id: ScanId
    path: Path
    size_bytes: int
    modified: datetime


@dataclass(frozen=True, slots=True)
class ScanStarted:
    """The scanner accepted the job and is warming up.

    Attributes:
        at: When the job began, used for the elapsed-time readout.
    """

    at: datetime


@dataclass(frozen=True, slots=True)
class PageScanned:
    """One side of one sheet has been captured.

    Attributes:
        page: 1-based count of sides captured so far, not sheets.
        side: Which face of the current sheet this was.
    """

    page: int
    side: Side


@dataclass(frozen=True, slots=True)
class ScanFinished:
    """The job completed and the file is written.

    Attributes:
        scan_id: Short handle the file is served under.
        path: Where the document was written.
        pages: Total sides captured.
        size_bytes: Size of the written file.
        duration: Wall-clock time the job took.
    """

    scan_id: ScanId
    path: Path
    pages: int
    size_bytes: int
    duration: timedelta


@dataclass(frozen=True, slots=True)
class ScanFailed:
    """The job stopped without producing a document.

    Attributes:
        message: One short line to show on the error screen.
    """

    message: str


# A scan reports itself as a stream of these. The two terminal variants are
# ScanFinished and ScanFailed; anything after one of those is a bug.
type ScanEvent = ScanStarted | PageScanned | ScanFinished | ScanFailed


# --- private ---------------------------------------------------------------

# Ranked by how much they want a human. An attached-but-unusable device
# outranks an absent one: absent is the expected state of a box whose scanner
# has not arrived, whereas unconfigured is a job someone has left half done.
# Ranked so the display shows the loudest complaint when it has room for one.
_FAULT_RANK = {
    FaultSeverity.REPORT: 0,
    FaultSeverity.WARNING: 1,
    FaultSeverity.ERROR: 2,
}

_SEVERITY = {
    Readiness.READY: 0,
    Readiness.BUSY: 1,
    Readiness.ABSENT: 2,
    Readiness.UNCONFIGURED: 3,
    Readiness.ERROR: 4,
}
