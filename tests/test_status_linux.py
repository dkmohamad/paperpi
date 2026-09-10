"""Peripheral detection, driven against a synthetic sysfs tree.

The adapter takes its sysfs roots and its queue source as parameters precisely
so they can be pointed at fixtures, which is what makes the USB matching and
the printer row testable on a machine with no hardware and no print server.

The queue source is a required parameter rather than something these tests
have to remember to pass. It used to default to the real CUPS adapter, which
meant a test could pass or fail depending on whether the machine running it
happened to have pycups installed; making it required moved that choice to the
composition root, where every other adapter choice already lives.
"""

from collections.abc import Sequence
from pathlib import Path

from paperpi.adapters.status_linux import LinuxStatus
from paperpi.models import (
    FaultSeverity,
    Peripheral,
    PeripheralKind,
    PrintQueue,
    QueueConnection,
    QueueFault,
    QueueState,
    Readiness,
)


def _fault(keyword: str, severity: FaultSeverity = FaultSeverity.ERROR) -> QueueFault:
    return QueueFault(keyword=keyword, severity=severity)


def _queue(
    *,
    state: QueueState = QueueState.IDLE,
    accepting: bool = True,
    faults: tuple[QueueFault, ...] = (),
    connection: QueueConnection = QueueConnection.USB,
) -> PrintQueue:
    """A configured queue, defaulting to a healthy one on the USB printer."""
    return PrintQueue(
        name="paperpi",
        connection=connection,
        state=state,
        accepting=accepting,
        faults=faults,
    )


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


def _status(
    tmp_path: Path, scan_dir: Path, queues: Sequence[PrintQueue] = ()
) -> LinuxStatus:
    usb = tmp_path / "usb"
    net = tmp_path / "net"
    usb.mkdir(exist_ok=True)
    net.mkdir(exist_ok=True)
    (net / "eth0").mkdir(exist_ok=True)
    (net / "eth0" / "operstate").write_text("up\n")
    thermal = tmp_path / "temp"
    thermal.write_text("47200\n")
    return LinuxStatus(
        scan_dir=scan_dir,
        queues=lambda: queues,
        sys_usb=usb,
        sys_net=net,
        thermal=thermal,
    )


def _peripheral(status: LinuxStatus, kind: PeripheralKind) -> Peripheral:
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
    With no queue configured the row is unconfigured, not ready: attached is
    not driveable.
    """
    status = _status(tmp_path, scan_dir)
    _usb_device(tmp_path / "usb", "1-2", "04b8", "1111", "EPSON XP", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.UNCONFIGURED
    assert "EPSON XP" in printer.detail


def test_printer_should_be_ready_when_a_usb_queue_is_idle_and_accepting(
    tmp_path: Path, scan_dir: Path
):
    """The one state that means someone can actually print.

    Both halves have to agree -- the device is on the bus and the queue will
    take work -- which is the whole reason the row composes the two.
    """
    status = _status(tmp_path, scan_dir, [_queue()])
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.READY
    # The panel names the hardware; "paperpi" is what the network advertises.
    assert "ET-2810" in printer.detail
    assert "paperpi" not in printer.detail


def test_printer_should_be_busy_while_a_job_is_printing(tmp_path: Path, scan_dir: Path):
    """Printing is not a fault, so it must not colour the lamp like one."""
    status = _status(tmp_path, scan_dir, [_queue(state=QueueState.PRINTING)])
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    assert _peripheral(status, PeripheralKind.PRINTER).readiness is Readiness.BUSY


def test_printer_should_report_a_stopped_queue_in_words(tmp_path: Path, scan_dir: Path):
    """A jam or an empty tray is the case the display exists for.

    The IPP keyword is translated, because "media-empty" is not what someone
    standing at the machine would call it.
    """
    status = _status(
        tmp_path,
        scan_dir,
        [_queue(state=QueueState.STOPPED, faults=(_fault("media-empty"),))],
    )
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.ERROR
    assert "out of paper" in printer.detail
    assert "media-empty" not in printer.detail


def test_printer_should_show_an_unmapped_fault_rather_than_hide_it(
    tmp_path: Path, scan_dir: Path
):
    """A keyword nobody has written wording for still has to reach the display.

    Falling back to silence would make the row claim less than it knows, and
    the fault would then be invisible until someone walked over to the printer.
    """
    status = _status(
        tmp_path,
        scan_dir,
        [_queue(state=QueueState.STOPPED, faults=(_fault("spool-area-full"),))],
    )
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.ERROR
    assert "spool-area-full" in printer.detail


def test_printer_should_be_an_error_when_the_queue_refuses_jobs(
    tmp_path: Path, scan_dir: Path
):
    """Idle but rejecting is a distinct fault from stopped.

    A queue in this state looks healthy to anything that only reads the state
    enum, and silently drops every job sent to it.
    """
    status = _status(tmp_path, scan_dir, [_queue(accepting=False)])
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.ERROR
    assert "not accepting" in printer.detail


def test_printer_should_be_an_error_when_the_queue_outlives_the_device(
    tmp_path: Path, scan_dir: Path
):
    """A configured queue with nothing plugged into it is a fault, not absence.

    CUPS does not notice an unplugged printer until it tries to print, so the
    queue alone would still report idle. The USB half is what catches this.
    """
    status = _status(tmp_path, scan_dir, [_queue()])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.ERROR
    assert "unplugged" in printer.detail


def test_a_network_queue_should_not_be_read_as_the_usb_printer(
    tmp_path: Path, scan_dir: Path
):
    """Adding a queue for some other printer must not light this row green.

    Matching on the device URI rather than taking the first queue is what
    stops the row reporting on a machine in another room.
    """
    status = _status(tmp_path, scan_dir, [_queue(connection=QueueConnection.NETWORK)])
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    printer = _peripheral(status, PeripheralKind.PRINTER)
    assert printer.readiness is Readiness.UNCONFIGURED
    assert "no queue" in printer.detail


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
        queues=lambda: (),
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
        queues=lambda: (),
        sys_usb=tmp_path / "usb",
        sys_net=net,
        thermal=tmp_path / "absent",
    )
    assert status().network.interface == "wlan0"


def test_storage_should_be_absent_when_the_scan_directory_is_missing(tmp_path: Path):
    """Scans have nowhere to go, so the row says so rather than showing free space."""
    status = LinuxStatus(
        scan_dir=tmp_path / "nowhere",
        queues=lambda: (),
        sys_usb=tmp_path / "usb",
        sys_net=tmp_path / "net",
        thermal=tmp_path / "absent",
    )
    storage = _peripheral(status, PeripheralKind.STORAGE)
    assert storage.readiness is Readiness.ABSENT


def test_the_family_word_should_be_trimmed_from_the_device_name(
    tmp_path: Path, scan_dir: Path
):
    """Vendors append "Series" to the product string, and it costs width.

    On a 320-pixel row that word is about a third of the space the detail has,
    which is the difference between a fault reading "out of paper" and reading
    as a truncated stub.
    """
    status = _status(tmp_path, scan_dir, [_queue()])
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    detail = _peripheral(status, PeripheralKind.PRINTER).detail
    assert detail.startswith("ET-2810 ·")
    assert "Series" not in detail


def test_the_loudest_fault_should_win_when_a_queue_reports_several(
    tmp_path: Path, scan_dir: Path
):
    """IPP does not order state reasons, so position is an accident.

    A jammed printer that is also low on ink reports both. Taking the first
    would put "ink low" on the panel while paper is stuck in the rollers --
    a true statement that hides the one worth acting on.
    """
    status = _status(
        tmp_path,
        scan_dir,
        [
            _queue(
                state=QueueState.STOPPED,
                faults=(
                    _fault("marker-supply-low", FaultSeverity.WARNING),
                    _fault("media-jam", FaultSeverity.ERROR),
                ),
            )
        ],
    )
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    detail = _peripheral(status, PeripheralKind.PRINTER).detail
    assert "paper jam" in detail
    assert "ink low" not in detail


def test_a_stopped_queue_should_outrank_a_rejecting_one(tmp_path: Path, scan_dir: Path):
    """A queue can be both, when someone rejects jobs on a jammed printer.

    "not accepting" describes the queue; "paper jam" describes what a person
    has to walk over and fix, so it is the one the row spends its width on.
    """
    status = _status(
        tmp_path,
        scan_dir,
        [
            _queue(
                state=QueueState.STOPPED,
                accepting=False,
                faults=(_fault("media-jam"),),
            )
        ],
    )
    _usb_device(tmp_path / "usb", "1-2", "04b8", "118a", "ET-2810 Series", ["07"])
    detail = _peripheral(status, PeripheralKind.PRINTER).detail
    assert "paper jam" in detail
    assert "not accepting" not in detail
