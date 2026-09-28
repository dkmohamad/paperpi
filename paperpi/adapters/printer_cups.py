# pyright: reportMissingImports=false
# pycups is imported lazily inside `__call__`, so there is nothing for pyright
# to resolve on a machine without the `cups` extra -- which includes every
# development machine, and this module is imported there by its own tests.
# Scoped to this file so the rule stays on everywhere it can be enforced.
"""What the print server says about its own queues.

Asked over the CUPS domain socket rather than by running `lpstat`. Two reasons.
`lpstat` prints prose that is translated and has changed wording between
releases, so reading it means parsing English; IPP answers with an integer
state and standardised keywords, which can be matched on and will not drift.
And a local IPP round trip costs a fraction of the process spawn shelling out
would -- measured on this Pi, a trivial spawn is 1.4 ms and a real linked
binary 10.8 ms -- which matters because this is sampled from inside the render
loop.

Everything IPP-shaped stops here. Callers get the domain vocabulary, so the URI
schemes and the integer states stay in the one module that speaks to CUPS.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ..models import (
    FaultSeverity,
    PrintQueue,
    QueueConnection,
    QueueFault,
    QueueState,
)

__all__ = ["CupsQueues"]

logger = logging.getLogger(__name__)


class _CupsConnection(Protocol):
    """The one part of a pycups Connection this adapter may use.

    Only `getPrinters`, so a call to the leaking `getPrinterAttributes` (see
    `CupsQueues`) is a type error rather than something a test has to catch.
    """

    def getPrinters(self) -> dict[str, dict[str, Any]]: ...  # noqa: N802


# How to open a connection to the print server. Injected so the failure paths
# below -- which are the ones that must never reach the render loop -- can be
# exercised without a print server, per the repo's inject-never-patch rule.
type Connect = Callable[[], _CupsConnection]


class CupsQueues:
    """The configured print queues, sampled over the CUPS local socket.

    A fresh connection per call. Holding one open would save a fraction of a
    millisecond every couple of seconds and would leave a dead handle every
    time cupsd restarts -- and cupsd does restart on its own, because it
    idle-exits when nothing is shared. The cheap thing is also the correct one.

    Everything comes from the one `getPrinters()` reply, which carries every
    field the display reads. `getPrinterAttributes()` must not be called here:
    pycups 2.0.4 leaks each reply it returns, about 26 KB a call measured on
    this Pi, which at this poll rate is over a gigabyte a day -- enough to
    starve the box into a hang within three days.
    """

    def __init__(self, *, connect: Connect | None = None):
        self._connect = connect
        # Only the first of a run of identical failures is logged. A cupsd
        # outage is worth knowing about, but this is called every couple of
        # seconds and a repeating warning would bury everything else in the
        # journal.
        self._reported: str | None = None

    def __call__(self) -> Sequence[PrintQueue]:
        """List the queues the print server has configured.

        Returns:
            One entry per queue, ordered by name. Empty when the print server
            is absent or unreachable -- from the display's point of view that
            is the same as having no queue, and is never a reason to stop
            drawing a frame.
        """
        connect = self._connect or _pycups_connection()
        if connect is None:
            # A development machine drives no printer, so no queue is the
            # truthful answer rather than an error to report.
            logger.debug("pycups is not installed; reporting no queues")
            return ()

        try:
            printers: dict[str, dict[str, Any]] = connect().getPrinters()
        except Exception as failure:  # noqa: BLE001
            # Deliberately broad: this runs inside the render loop, and every
            # way of failing to reach the print server means the same thing to
            # the display. A panel that stops drawing because cupsd hiccupped
            # tells the room less than one reporting no queue for two seconds.
            return self._unavailable(f"{type(failure).__name__}: {failure}")

        self._reported = None
        return tuple(
            _queue(name, attributes) for name, attributes in sorted(printers.items())
        )

    def _unavailable(self, reason: str) -> tuple[PrintQueue, ...]:
        """Report no queues, saying why the first time it happens."""
        if reason != self._reported:
            logger.warning("cannot read print queues (%s); reporting none", reason)
            self._reported = reason
        return ()


# --- private ---------------------------------------------------------------

# IPP reports printer-state as an integer. Anything unrecognised is read as
# stopped: an unknown state is not one to claim is fine.
# Source: IANA IPP registry, printer-state -- https://www.iana.org/assignments/ipp-registrations
_STATES = {3: QueueState.IDLE, 4: QueueState.PRINTING, 5: QueueState.STOPPED}

# CUPS names the transport in the device URI's scheme. Only the first matters
# to the display; the rest are grouped so a queue is never mistaken for local.
_LOCAL_SCHEMES = ("usb:", "hp:", "hpfax:", "parallel:", "serial:")
_NETWORK_SCHEMES = (
    "ipp:",
    "ipps:",
    "http:",
    "https:",
    "socket:",
    "lpd:",
    "dnssd:",
    "smb:",
)

# Every IPP state reason ends in exactly one of these. The suffix is per-reason,
# so a queue can report a warning and an error at the same time.
_SEVERITIES = {
    "-error": FaultSeverity.ERROR,
    "-warning": FaultSeverity.WARNING,
    "-report": FaultSeverity.REPORT,
}

# IPP's way of saying there is nothing to report, rather than a fault called
# "none".
_NOTHING_TO_REPORT = "none"

# pycups' getPrinters() does not request printer-is-accepting-jobs; CUPS also
# folds it into the printer-type bitmask, which getPrinters() does request.
# Source: CUPS_PRINTER_REJECTING in cups_ptype_e,
# https://github.com/OpenPrinting/cups/blob/v2.4.10/cups/cups.h
_CUPS_PRINTER_REJECTING = 0x80000


def _pycups_connection() -> Connect | None:
    """The real connection factory, or None where pycups is not installed."""
    try:
        import cups
    except ImportError:
        return None
    return cups.Connection


def _queue(name: str, attributes: dict[str, Any]) -> PrintQueue:
    """Build one queue from the attributes the server returned for it.

    Missing attributes are read by one rule: absent evidence never manufactures
    a specific accusation. So an unreadable state is stopped -- claiming a
    queue is fine on no evidence is the lie this display exists to avoid -- but
    an absent printer-type reads as accepting, because "not accepting jobs"
    is a definite charge and getting it wrong pins the row red forever, which
    is how a status display stops being read at all.

    That is the one place in this package where missing evidence can contribute
    to a READY row, and it is narrow: the state and the USB presence must both
    independently agree. In practice printer-type is always present: pycups'
    getPrinters() always requests it.
    """
    return PrintQueue(
        name=name,
        connection=_connection(str(attributes.get("device-uri", ""))),
        state=_state(attributes.get("printer-state")),
        accepting=_accepting(attributes.get("printer-type")),
        faults=_faults(attributes.get("printer-state-reasons")),
    )


def _accepting(printer_type: object) -> bool:
    """Read CUPS's rejecting bit, defaulting to accepting."""
    if not isinstance(printer_type, int):
        return True
    return not printer_type & _CUPS_PRINTER_REJECTING


def _state(raw: object) -> QueueState:
    """Read IPP's integer printer-state, defaulting to stopped."""
    if not isinstance(raw, int):
        return QueueState.STOPPED
    return _STATES.get(raw, QueueState.STOPPED)


def _connection(device_uri: str) -> QueueConnection:
    """Classify a queue by the scheme of the device it prints to."""
    if device_uri.startswith(_LOCAL_SCHEMES):
        return QueueConnection.USB
    if device_uri.startswith(_NETWORK_SCHEMES):
        return QueueConnection.NETWORK
    return QueueConnection.OTHER


def _faults(raw: object) -> tuple[QueueFault, ...]:
    """Turn printer-state-reasons into faults that keep their severity.

    pycups gives a list for several reasons and a bare string for one, so both
    shapes arrive here. "none" is dropped, so an untroubled queue reports
    nothing rather than a fault named after the absence of one.
    """
    values = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    faults: list[QueueFault] = []
    for value in values:
        if not isinstance(value, str) or value == _NOTHING_TO_REPORT:
            continue
        faults.append(_fault(value))
    return tuple(faults)


def _fault(reason: str) -> QueueFault:
    """Split one state reason into its keyword and its severity.

    Exactly one suffix applies: IPP defines the severity as a suffix on the
    keyword, and no registered keyword itself ends in one. An unsuffixed reason
    is treated as a report, which is IPP's own default reading.
    """
    for suffix, severity in _SEVERITIES.items():
        if reason.endswith(suffix):
            return QueueFault(keyword=reason.removesuffix(suffix), severity=severity)
    return QueueFault(keyword=reason, severity=FaultSeverity.REPORT)
