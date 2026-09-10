"""Peripheral detection, driven against a synthetic sysfs tree.

The adapter takes its sysfs roots as parameters precisely so they can be
pointed at a fixture, which is what makes the USB matching testable on a
machine with none of the hardware attached.
"""

from pathlib import Path

from paperpi.adapters.status_linux import LinuxStatus
from paperpi.models import PeripheralKind, Readiness


def _usb_device(
    root: Path, name: str, vendor: str, product: str, label: str, classes: list[str]
) -> None:
    """Lay out one device the way sysfs presents it."""
    device = root / name
    device.mkdir(parents=True)
    (device / "idVendor").write_text(f"{vendor}\n")
    (device / "idProduct").write_text(f"{product}\n")
    (device / "product").write_text(f"{label}\n")
    for index, interface_class in enumerate(classes):
        interface = device / f"{name}:1.{index}"
        interface.mkdir()
        (interface / "bInterfaceClass").write_text(f"{interface_class}\n")


def _status(tmp_path: Path, scan_dir: Path) -> LinuxStatus:
    usb = tmp_path / "usb"
    net = tmp_path / "net"
    usb.mkdir(exist_ok=True)
    net.mkdir(exist_ok=True)
    (net / "eth0").mkdir(exist_ok=True)
    (net / "eth0" / "operstate").write_text("up\n")
    thermal = tmp_path / "temp"
    thermal.write_text("47200\n")
    return LinuxStatus(scan_dir=scan_dir, sys_usb=usb, sys_net=net, thermal=thermal)


def _peripheral(status: LinuxStatus, kind: PeripheralKind):
    return next(p for p in status().peripherals if p.kind is kind)


def test_scanner_should_be_absent_when_no_matching_vendor_is_attached(
    tmp_path: Path, scan_dir: Path
):
    """An empty bus reports absent, not error.

    Nothing being plugged in is the expected resting state of this box until
    the scanner arrives, and colouring it as a fault would make the lamp cry
    wolf for weeks.
    """
    status = _status(tmp_path, scan_dir)
    scanner = _peripheral(status, PeripheralKind.SCANNER)
    assert scanner.readiness is Readiness.ABSENT


def test_scanner_should_be_unconfigured_when_attached_without_a_driver(
    tmp_path: Path, scan_dir: Path
):
    """A Fujitsu device present but undriveable is unconfigured, not ready.

    Claiming READY on USB presence alone would be a lie the first scan
    disproves; UNCONFIGURED says attached-but-not-usable, which is the actual
    state until SANE is installed.
    """
    status = _status(tmp_path, scan_dir)
    # 04c5 is Fujitsu's USB-IF vendor id, per the registry cited in config.
    _usb_device(tmp_path / "usb", "1-1", "04c5", "132e", "fi-6130", ["ff"])
    scanner = _peripheral(status, PeripheralKind.SCANNER)
    assert scanner.readiness is Readiness.UNCONFIGURED
    assert "fi-6130" in scanner.detail


def test_printer_should_be_detected_by_its_usb_interface_class(
    tmp_path: Path, scan_dir: Path
):
    """Any conforming printer is found structurally, not by model.

    USB-IF class 07 is "printer", so this works for the Epson without anyone
    transcribing its vendor id -- and would keep working if it were replaced.
    """
    status = _status(tmp_path, scan_dir)
    _usb_device(tmp_path / "usb", "1-2", "04b8", "1111", "EPSON XP", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.UNCONFIGURED
    assert "EPSON XP" in printer.detail


def test_a_non_printer_device_should_not_be_mistaken_for_a_printer(
    tmp_path: Path, scan_dir: Path
):
    """A mass-storage device must not satisfy the printer match.

    Class 08 is storage. Without this, any USB stick would light the printer
    row green-ish and the display would be confidently wrong.
    """
    status = _status(tmp_path, scan_dir)
    _usb_device(tmp_path / "usb", "1-3", "0781", "5583", "USB DISK", ["08"])
    assert _peripheral(status, PeripheralKind.PRINTER).readiness is Readiness.ABSENT


def test_temperature_should_convert_from_millidegrees(tmp_path: Path, scan_dir: Path):
    """sysfs reports thousandths of a degree; the display shows degrees."""
    assert _status(tmp_path, scan_dir)().temperature_c == 47.2


def test_temperature_should_be_none_when_unreadable(tmp_path: Path, scan_dir: Path):
    """A missing thermal zone is not a reason for the display to fail.

    The whole sample is best-effort: an unreadable field is reported as unknown
    rather than raising, because a status screen that crashes tells you less
    than one showing a blank temperature.
    """
    status = LinuxStatus(
        scan_dir=scan_dir,
        sys_usb=tmp_path / "usb",
        sys_net=tmp_path / "net",
        thermal=tmp_path / "absent",
    )
    assert status().temperature_c is None


def test_network_should_name_the_first_interface_that_is_up(
    tmp_path: Path, scan_dir: Path
):
    """A down interface is skipped, and loopback never counts.

    Otherwise the panel would advertise `lo` as the way to reach the box.
    """
    net = tmp_path / "net"
    net.mkdir(exist_ok=True)
    for name, state in (("lo", "up"), ("eth0", "down"), ("wlan0", "up")):
        (net / name).mkdir(exist_ok=True)
        (net / name / "operstate").write_text(f"{state}\n")
    status = LinuxStatus(
        scan_dir=scan_dir,
        sys_usb=tmp_path / "usb",
        sys_net=net,
        thermal=tmp_path / "absent",
    )
    assert status().network.interface == "wlan0"


def test_storage_should_be_absent_when_the_scan_directory_is_missing(tmp_path: Path):
    """Scans have nowhere to go, so the row says so rather than showing free space."""
    status = LinuxStatus(
        scan_dir=tmp_path / "nowhere",
        sys_usb=tmp_path / "usb",
        sys_net=tmp_path / "net",
        thermal=tmp_path / "absent",
    )
    storage = _peripheral(status, PeripheralKind.STORAGE)
    assert storage.readiness is Readiness.ABSENT
