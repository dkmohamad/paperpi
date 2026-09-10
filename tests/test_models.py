"""The vocabulary types: validation, aggregates and formatting."""

from datetime import timedelta

import pytest

from paperpi.models import (
    FaultSeverity,
    Peripheral,
    PeripheralKind,
    Peripherals,
    PrintQueue,
    QueueConnection,
    QueueFault,
    QueueState,
    Readiness,
    Rgb,
)
from paperpi.render.format import format_duration, format_size


def test_rgb_should_reject_a_channel_outside_the_byte_range():
    """A colour cannot exist with an out-of-range channel.

    Validation is in the constructor so an invalid colour never reaches the
    display driver, where the failure would be a confusing hardware error
    rather than an obvious value error.
    """
    with pytest.raises(ValueError, match="red must be 0-255"):
        Rgb(red=256, green=0, blue=0)


def test_rgb_from_hex_should_accept_a_string_with_or_without_a_hash():
    """Both `#rrggbb` and `rrggbb` parse to the same colour."""
    assert Rgb.from_hex("#3fb950") == Rgb.from_hex("3fb950") == Rgb(63, 185, 80)


def test_rgb_as_fractions_should_scale_a_full_channel_to_one():
    """The LED takes 0.0-1.0, so 255 must map exactly to 1.0.

    Guards the boundary the hardware library validates: gpiozero raises if a
    PWM value exceeds 1.0, so an off-by-a-rounding here would fail at runtime
    on the Pi and nowhere else.
    """
    assert Rgb(255, 0, 128).as_fractions() == (1.0, 0.0, 128 / 255)


def test_peripherals_worst_should_pick_the_most_severe_wherever_it_sits():
    """The lamp shows the worst state regardless of its position in the list.

    Deliberately not ordered worst-last: with the severe entry at the end,
    "the worst", "the last" and "the maximum by position" are indistinguishable
    and the test would pass for three different implementations, only one of
    which is right.
    """

    def peripherals(*states: Readiness) -> Peripherals:
        kinds = (
            PeripheralKind.SCANNER,
            PeripheralKind.PRINTER,
            PeripheralKind.STORAGE,
        )
        return Peripherals(
            Peripheral(kind, state, "detail")
            for kind, state in zip(kinds, states, strict=True)
        )

    first = peripherals(Readiness.ERROR, Readiness.READY, Readiness.READY)
    middle = peripherals(Readiness.READY, Readiness.ERROR, Readiness.READY)
    last = peripherals(Readiness.READY, Readiness.READY, Readiness.ERROR)
    assert first.worst is Readiness.ERROR
    assert middle.worst is Readiness.ERROR
    assert last.worst is Readiness.ERROR


def test_peripherals_worst_should_rank_unconfigured_above_absent():
    """An attached-but-unusable device outranks one that is simply missing.

    Absent is the expected resting state of a box whose scanner has not
    arrived; unconfigured is a setup job someone left half done, and is the one
    that should colour the lamp.
    """
    peripherals = Peripherals(
        [
            Peripheral(PeripheralKind.SCANNER, Readiness.ABSENT, "none"),
            Peripheral(PeripheralKind.PRINTER, Readiness.UNCONFIGURED, "no queue"),
        ]
    )
    assert peripherals.worst is Readiness.UNCONFIGURED


def test_peripherals_worst_should_be_ready_when_there_are_none():
    """An empty set is not a fault, so the lamp stays green."""
    assert Peripherals().worst is Readiness.READY


def test_format_duration_should_drop_the_hour_field_under_an_hour():
    """Panel space is scarce, so a leading `0:` hour is not shown."""
    assert format_duration(timedelta(seconds=48)) == "0:48"
    assert format_duration(timedelta(minutes=3, seconds=7)) == "3:07"
    assert format_duration(timedelta(hours=1, minutes=2, seconds=3)) == "1:02:03"


def test_format_size_should_switch_unit_at_each_thousand():
    """Sizes stay under four characters of number so the row fits."""
    assert format_size(512) == "512 B"
    assert format_size(2_411_000) == "2.4 MB"
    assert format_size(3_000_000_000) == "3.0 GB"


def test_worst_fault_should_rank_by_severity_not_by_position():
    """IPP does not order state reasons, so the first is an accident.

    A jammed printer that is also low on ink reports both, and the ranking is
    what stops "ink low" being shown while paper is stuck in the rollers.
    """
    queue = PrintQueue(
        name="q",
        connection=QueueConnection.USB,
        state=QueueState.STOPPED,
        accepting=True,
        faults=(
            QueueFault(keyword="marker-supply-low", severity=FaultSeverity.WARNING),
            QueueFault(keyword="media-jam", severity=FaultSeverity.ERROR),
            QueueFault(keyword="cover-open", severity=FaultSeverity.REPORT),
        ),
    )
    worst = queue.worst_fault
    assert worst is not None
    assert worst.keyword == "media-jam"


def test_worst_fault_should_be_none_when_nothing_is_wrong():
    """An untroubled queue has no fault, rather than a fault meaning none."""
    queue = PrintQueue(
        name="q",
        connection=QueueConnection.USB,
        state=QueueState.IDLE,
        accepting=True,
        faults=(),
    )
    assert queue.worst_fault is None
