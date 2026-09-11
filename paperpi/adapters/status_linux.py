"""Reading the machine's real state, cheaply enough to poll.

Sampled every couple of seconds from inside the render loop, so nothing here
may block. USB presence and temperature are sysfs reads, which cost nothing.
The print queue is the one reading that leaves the filesystem, and it arrives
through an injected port rather than being reached for here -- so a test needs
no print server, and the composition root stays the only place that picks an
adapter. Why that port is spoken over IPP rather than by running `lpstat` is
argued where the decision was made, in `printer_cups`.

Where a layer is genuinely missing, the report says so instead of guessing.
Both peripherals are reported in two halves -- what is on the bus, and what can
actually be driven -- and neither half is taken as evidence of the other. A
scanner with no backend reports as attached-without-a-driver rather than ready,
which is a claim the first scan would disprove.
"""

import shutil
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from .. import config
from ..models import (
    Network,
    Peripheral,
    PeripheralKind,
    Peripherals,
    PrintQueue,
    QueueConnection,
    QueueState,
    Readiness,
    Storage,
    SystemStatus,
)
from ..ports import PrintQueues, ScannerDevice

__all__ = ["LinuxStatus", "current_address"]

_SYS_USB = Path("/sys/bus/usb/devices")
_SYS_NET = Path("/sys/class/net")
_THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


@dataclass(frozen=True, slots=True)
class _UsbDevice:
    """One attached USB device as sysfs describes it."""

    vendor: str
    product: str
    name: str
    interface_classes: frozenset[str]


def current_address() -> IPv4Address | None:
    """Find the address this machine would use to reach the LAN.

    Opens a datagram socket and asks the kernel which source address it would
    pick. No packet is sent, so this costs nothing and does not depend on the
    destination existing.

    Returns:
        The address, or None if there is no route out.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0)
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
            return IPv4Address(probe.getsockname()[0])
    except OSError:
        return None


class LinuxStatus:
    """Samples network, peripherals and storage from sysfs."""

    def __init__(
        self,
        *,
        scan_dir: Path,
        queues: PrintQueues,
        scanner: ScannerDevice,
        sys_usb: Path = _SYS_USB,
        sys_net: Path = _SYS_NET,
        thermal: Path = _THERMAL,
    ):
        self._scan_dir = scan_dir
        self._queues = queues
        self._probe = _ScannerProbe(scanner)
        self._sys_usb = sys_usb
        self._sys_net = sys_net
        self._thermal = thermal

    def __call__(self) -> SystemStatus:
        """Take one sample.

        Returns:
            The current state. Anything unreadable is reported as unknown
            rather than raising -- a missing thermal zone is not a reason for
            the display to stop.
        """
        devices = self._usb_devices()
        return SystemStatus(
            network=self._network(),
            peripherals=Peripherals(
                [
                    self._scanner(devices),
                    self._printer(devices),
                    self._storage_peripheral(),
                ]
            ),
            storage=self._storage(),
            temperature_c=self._temperature(),
        )

    def _network(self) -> Network:
        interface = self._primary_interface()
        return Network(interface=interface, address=current_address())

    def _primary_interface(self) -> str:
        """Name the first carrier-up interface, preferring wired over wireless."""
        try:
            names = sorted(path.name for path in self._sys_net.iterdir())
        except OSError:
            return "unknown"
        for name in names:
            if name == "lo":
                continue
            try:
                state = (self._sys_net / name / "operstate").read_text().strip()
            except OSError:
                continue
            if state == "up":
                return name
        return "no link"

    def _usb_devices(self) -> list[_UsbDevice]:
        """List attached USB devices, ignoring hubs and the root controllers."""
        devices: list[_UsbDevice] = []
        try:
            entries = sorted(self._sys_usb.iterdir())
        except OSError:
            return devices
        for entry in entries:
            vendor = _read(entry / "idVendor")
            if vendor is None:
                continue
            devices.append(
                _UsbDevice(
                    vendor=vendor,
                    product=_read(entry / "idProduct") or "",
                    name=_read(entry / "product") or "",
                    interface_classes=_interface_classes(entry),
                )
            )
        return devices

    def _scanner(self, devices: list[_UsbDevice]) -> Peripheral:
        """Compose USB presence with what the scanning backend can see.

        The same two-halves shape as the printer row, for the same reason --
        attached is not driveable -- but sampled differently. There is no cheap
        equivalent of the print server's socket: listing SANE devices spawns a
        process, so it runs only when the bus changes rather than every poll.
        """
        attached = self._attached_scanner(devices)
        device = self._probe.look(present=attached is not None)

        if attached is None:
            return _scanner_row(Readiness.ABSENT, "no device")
        if device is None:
            return _scanner_row(Readiness.UNCONFIGURED, f"{attached} · no driver")
        # Just the model: the readiness column already says "ready", and unlike
        # the printer there is no second state to distinguish here -- a running
        # scan has a screen of its own. The name comes from the backend because
        # USB has none to give; this scanner reports empty product strings.
        return _scanner_row(Readiness.READY, _model_of(device))

    def _attached_scanner(self, devices: list[_UsbDevice]) -> str | None:
        """Name the USB-attached scanner, or None if there is not one."""
        for device in devices:
            if device.vendor in config.SCANNER_USB_VENDORS:
                maker = config.SCANNER_USB_VENDORS[device.vendor]
                return _model(device.name) or f"{maker} device"
        return None

    def _printer(self, devices: list[_UsbDevice]) -> Peripheral:
        """Compose USB presence with the print queue's own view.

        Both halves are needed. The queue alone cannot tell a printer that is
        merely idle from one that has been unplugged, because CUPS does not
        notice until it tries to print; USB alone cannot tell configured from
        unconfigured. Together they cover every state the row can be in.
        """
        attached = self._attached_printer(devices)
        queue = self._usb_queue()

        if queue is None:
            if attached is None:
                return _printer_row(Readiness.ABSENT, "no device")
            return _printer_row(Readiness.UNCONFIGURED, f"{attached} · no queue")

        # The display names the hardware it is driving; the queue name is what
        # the network advertises and is shown to clients, not here.
        if attached is None:
            return _printer_row(Readiness.ERROR, "unplugged")
        # Stopped is checked before rejecting, because a queue can be both --
        # someone runs `cupsreject` on a jammed printer -- and "paper jam" is
        # the sentence that tells the room what to do about it.
        if queue.state is QueueState.STOPPED:
            return _printer_row(Readiness.ERROR, f"{attached} · {_fault(queue)}")
        if not queue.accepting:
            return _printer_row(Readiness.ERROR, f"{attached} · not accepting")
        if queue.state is QueueState.PRINTING:
            return _printer_row(Readiness.BUSY, f"{attached} · printing")
        return _printer_row(Readiness.READY, f"{attached} · idle")

    def _attached_printer(self, devices: list[_UsbDevice]) -> str | None:
        """Name the USB-attached printer, or None if there is not one."""
        for device in devices:
            if config.PRINTER_INTERFACE_CLASS in device.interface_classes:
                return _model(device.name) or "usb printer"
        return None

    def _usb_queue(self) -> PrintQueue | None:
        """The queue driving the directly-attached printer, if one exists.

        Matched on how the queue connects rather than taken as "the first
        queue", so adding a second queue for a printer in another room cannot
        make this row report on the wrong device.
        """
        for queue in self._queues():
            if queue.connection is QueueConnection.USB:
                return queue
        return None

    def _storage_peripheral(self) -> Peripheral:
        storage = self._storage()
        if not storage.path.exists():
            return Peripheral(
                kind=PeripheralKind.STORAGE,
                readiness=Readiness.ABSENT,
                detail="no scan directory",
            )
        if storage.free_bytes is None:
            return Peripheral(
                kind=PeripheralKind.STORAGE,
                readiness=Readiness.ERROR,
                detail="unreadable",
            )
        where = "removable" if storage.mounted else "on sd card"
        return Peripheral(
            kind=PeripheralKind.STORAGE,
            readiness=Readiness.READY,
            detail=where,
        )

    def _storage(self) -> Storage:
        try:
            free = shutil.disk_usage(self._scan_dir).free
        except OSError:
            free = None
        try:
            mounted = self._scan_dir.is_mount()
        except OSError:
            mounted = False
        return Storage(path=self._scan_dir, free_bytes=free, mounted=mounted)

    def _temperature(self) -> float | None:
        raw = _read(self._thermal)
        if raw is None:
            return None
        try:
            return int(raw) / 1000
        except ValueError:
            return None


# --- private ---------------------------------------------------------------


def _model(name: str) -> str:
    """Trim a USB product string down to the part that identifies the device.

    Vendors append a family word -- "ET-2810 Series", "MFC-L2710DW Series" --
    which is marketing rather than model and costs a third of the width of a
    320-pixel row. Dropping it is what lets the fault beside it stay readable
    instead of being truncated away.
    """
    return name.removesuffix(" Series").strip()


class _ScannerProbe:
    """What the scanning backend last said, asked again only when it can change.

    Listing SANE devices costs a process spawn, which is far too much for a
    loop that samples every couple of seconds -- but probing once at start-up
    would leave a scanner plugged in afterwards reading "no driver" until
    somebody restarted the service, which is exactly when a person is standing
    there watching. Presence is cheap and live; the probe follows it.
    """

    def __init__(self, find: ScannerDevice):
        self._find = find
        self._present = False
        self._device: str | None = None

    def look(self, *, present: bool) -> str | None:
        """The device name, probing only when the scanner has just appeared."""
        if not present:
            self._present = False
            self._device = None
            return None
        if not self._present:
            self._present = True
            self._device = self._find()
        return self._device


def _scanner_row(readiness: Readiness, detail: str) -> Peripheral:
    """Build a scanner peripheral, since every branch above returns one."""
    return Peripheral(kind=PeripheralKind.SCANNER, readiness=readiness, detail=detail)


def _model_of(device: str) -> str:
    """Pull the model out of a SANE device name.

    They are `backend:model:serial`, so the middle field is the part worth a
    row on the panel. Anything unexpected is shown whole rather than mangled.
    """
    parts = device.split(":")
    return parts[1] if len(parts) >= 3 else device


def _printer_row(readiness: Readiness, detail: str) -> Peripheral:
    """Build a printer peripheral, since every branch above returns one."""
    return Peripheral(kind=PeripheralKind.PRINTER, readiness=readiness, detail=detail)


def _fault(queue: PrintQueue) -> str:
    """Say why a queue is stopped, in words rather than IPP keywords.

    An unmapped keyword is shown as-is: a fault nobody has written wording for
    is still a fault, and hiding it would make the row claim less than it
    knows.
    """
    worst = queue.worst_fault
    if worst is None:
        return "stopped"
    return config.PRINTER_FAULTS.get(worst.keyword, worst.keyword)


def _read(path: Path) -> str | None:
    """Read a small sysfs file, or None if it is not there."""
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _interface_classes(device: Path) -> frozenset[str]:
    """Collect the bInterfaceClass values of a device's interfaces."""
    classes: set[str] = set()
    try:
        entries = device.iterdir()
    except OSError:
        return frozenset()
    for entry in entries:
        value = _read(entry / "bInterfaceClass")
        if value is not None:
            classes.add(value)
    return frozenset(classes)
