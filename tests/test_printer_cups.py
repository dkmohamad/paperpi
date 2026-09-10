"""Translating what IPP says into the vocabulary the display speaks.

The mapping is the whole of this adapter's logic and it is pure, so it is
tested directly rather than through a print server. Nothing here needs pycups
installed -- which is the point: this is what would silently rot if CUPS
changed its wording, and it is the reason IPP's keywords were chosen over
parsing `lpstat`.

The connection factory is injected for the same reason it is injected in the
adapter: the three failure paths are the ones that must never reach the render
loop, and a path nobody has watched engage is a path nobody knows works.
"""

from typing import Any

from paperpi.adapters.printer_cups import (
    CupsQueues,
    _connection,
    _faults,
    _queue,
    _state,
)
from paperpi.models import FaultSeverity, QueueConnection, QueueState

_USB = "usb://EPSON/ET-2810%20Series?serial=0123456789ABCDEF"


class _FakeConnection:
    """Stands in for a pycups Connection, including its ways of failing."""

    def __init__(self, printers: dict[str, dict[str, Any]], vanishing: str = ""):
        self._printers = printers
        self._vanishing = vanishing

    def getPrinters(self) -> dict[str, dict[str, Any]]:  # noqa: N802
        return self._printers

    def getPrinterAttributes(self, name: str) -> dict[str, Any]:  # noqa: N802
        if name == self._vanishing:
            raise RuntimeError("client-error-not-found")
        return self._printers[name]


def test_state_should_map_the_three_ipp_values():
    """IPP numbers these 3, 4 and 5; nothing else is standardised."""
    assert _state(3) is QueueState.IDLE
    assert _state(4) is QueueState.PRINTING
    assert _state(5) is QueueState.STOPPED


def test_an_unknown_state_should_be_read_as_stopped():
    """A state we cannot name is not one to report as fine.

    Defaulting to idle would paint the row green on the strength of a number
    nobody has interpreted, which is the failure honest detection exists to
    prevent.
    """
    assert _state(99) is QueueState.STOPPED
    assert _state(None) is QueueState.STOPPED
    assert _state("idle") is QueueState.STOPPED


def test_faults_should_drop_ipps_word_for_nothing_wrong():
    """IPP says "none" rather than sending an empty list.

    Passed through, it would reach the display as a fault called "none".
    """
    assert _faults("none") == ()
    assert _faults(["none"]) == ()


def test_faults_should_keep_the_severity_the_suffix_carries():
    """The suffix is per-reason, so it cannot be recovered from the state.

    Discarding it leaves the faults unordered, and whatever picks one then
    picks by list position -- which is how "ink low" ends up on the display
    while the printer is jammed.
    """
    warning, error = _faults(["marker-supply-low-warning", "media-jam-error"])
    assert (warning.keyword, warning.severity) == (
        "marker-supply-low",
        FaultSeverity.WARNING,
    )
    assert (error.keyword, error.severity) == ("media-jam", FaultSeverity.ERROR)


def test_an_unsuffixed_reason_should_be_read_as_a_report():
    """IPP's own default reading, and the quietest of the three."""
    (fault,) = _faults("com.example-vendor-thing")
    assert fault.severity is FaultSeverity.REPORT
    assert fault.keyword == "com.example-vendor-thing"


def test_faults_should_accept_both_shapes_pycups_returns():
    """pycups gives a bare string for one reason and a list for several.

    Handling only the list would lose exactly the single-fault case, which is
    the common one.
    """
    assert [f.keyword for f in _faults("cover-open-error")] == ["cover-open"]
    assert [f.keyword for f in _faults(["cover-open", "media-empty"])] == [
        "cover-open",
        "media-empty",
    ]


def test_faults_should_be_empty_when_the_attribute_is_missing():
    """An absent attribute is not a fault, and must not raise mid-render."""
    assert _faults(None) == ()
    assert _faults(42) == ()


def test_connection_should_classify_by_the_device_uri_scheme():
    """The scheme is CUPS vocabulary and stops here.

    Callers ask whether a queue drives the attached printer; they should never
    have to know what a device URI looks like to find out.
    """
    assert _connection(_USB) is QueueConnection.USB
    assert _connection("ipp://192.168.1.199/ipp/print") is QueueConnection.NETWORK
    assert _connection("ipps://elsewhere/ipp/print") is QueueConnection.NETWORK
    assert _connection("") is QueueConnection.OTHER
    assert _connection("cups-pdf:/") is QueueConnection.OTHER


def test_a_present_accepting_flag_should_be_coerced_from_ipps_integer():
    """IPP booleans arrive as 0/1, and the row branches on this being a bool."""
    assert _queue("q", {"printer-is-accepting-jobs": 1}).accepting is True
    assert _queue("q", {"printer-is-accepting-jobs": 0}).accepting is False


def test_a_queue_should_survive_a_server_that_omits_attributes():
    """A queue missing fields is reported without raising.

    The two defaults deliberately differ. An unreadable state is stopped,
    because claiming a queue is fine on no evidence is the lie the display
    exists to avoid. A missing accepting flag reads as accepting, because
    "not accepting jobs" is a definite accusation and getting it wrong pins
    the row red forever -- which is how a status display stops being read.
    """
    queue = _queue("sparse", {})
    assert queue.connection is QueueConnection.OTHER
    assert queue.state is QueueState.STOPPED
    assert queue.accepting is True
    assert queue.faults == ()


def test_queues_should_be_read_through_the_injected_connection():
    """The happy path, with no print server anywhere near it."""
    connection = _FakeConnection(
        {
            "paperpi": {
                "device-uri": _USB,
                "printer-state": 3,
                "printer-is-accepting-jobs": 1,
                "printer-state-reasons": "none",
            }
        }
    )
    (queue,) = CupsQueues(connect=lambda: connection)()
    assert queue.name == "paperpi"
    assert queue.connection is QueueConnection.USB
    assert queue.state is QueueState.IDLE


def test_an_unreachable_server_should_report_no_queues_rather_than_raise():
    """This is called from inside the render loop.

    A panel that stops drawing because cupsd was restarting tells the room
    less than one reporting no queue for two seconds.
    """

    def refuse() -> Any:
        raise RuntimeError("failed to connect to server")

    assert CupsQueues(connect=refuse)() == ()


def test_a_queue_deleted_mid_read_should_be_skipped_not_fatal():
    """Listing and reading are two round trips, so a queue can vanish between.

    The one that went away is no longer there to report on; the other still
    is, and losing it too would blank the row for no reason.
    """
    connection = _FakeConnection(
        {
            "going": {"device-uri": _USB, "printer-state": 3},
            "staying": {"device-uri": _USB, "printer-state": 3},
        },
        vanishing="going",
    )
    queues = CupsQueues(connect=lambda: connection)()
    assert [q.name for q in queues] == ["staying"]
