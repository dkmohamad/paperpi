"""Every value that is a choice rather than a consequence.

Pin numbers, palette, layout metrics and paths live here once and are imported.
The pin constants are the Display HAT Mini's fixed wiring, transcribed from
Pimoroni's own library so we can drive the panel and buttons directly rather
than depending on a package that has not been released since 2022.
"""

from pathlib import Path

from .models import Button, LedChannel, Readiness, Rgb

__all__ = [
    "ACCENT",
    "BACKGROUND",
    "BIND_ADDRESS",
    "BUTTON_PINS",
    "DIM",
    "DISPLAY_HEIGHT",
    "DISPLAY_WIDTH",
    "DONE_SCREEN_SECONDS",
    "FONT_DIR",
    "HTTP_PORT",
    "LED_BRIGHTNESS",
    "LED_PINS",
    "MARGIN",
    "MUTED",
    "PRINTER_FAULTS",
    "PRINTER_INTERFACE_CLASS",
    "READINESS_COLOURS",
    "SANE_CONFIG_DIR",
    "SCANNER_BACKEND",
    "SCANNER_END_OF_FEED",
    "SCANNER_FAULTS",
    "SCANNER_USB_VENDORS",
    "SCAN_DIR",
    "SCAN_MODE",
    "SCAN_PAGE_HEIGHT_MM",
    "SCAN_PAGE_WIDTH_MM",
    "SCAN_RESOLUTION_DPI",
    "SCAN_ROTATION_DEGREES",
    "SCAN_SOURCE",
    "SPI_BACKLIGHT",
    "SPI_CS",
    "SPI_DC",
    "SPI_PORT",
    "SPI_ROTATION",
    "SPI_SPEED_HZ",
    "TEXT",
]

DISPLAY_WIDTH = 320
DISPLAY_HEIGHT = 240

# ST7789 wiring for the Display HAT Mini. The panel is on SPI0 CE1, and BCM 9 --
# normally SPI0 MISO -- is repurposed as the data/command line, so SPI0 is
# write-only while this HAT is fitted.
SPI_PORT = 0
SPI_CS = 1
SPI_DC = 9
SPI_BACKLIGHT = 13
SPI_SPEED_HZ = 60_000_000
SPI_ROTATION = 180

# Buttons are active-low with pull-ups; the LED is common-anode, so its channels
# are inverted by the adapter rather than here. Transcribed from Pimoroni's
# library, which is the only published source for this board's wiring:
# https://github.com/pimoroni/displayhatmini-python/blob/main/library/displayhatmini/__init__.py
# Keyed by the domain types, not by strings: a typo is then a type error rather
# than a ValueError raised deep inside the adapter at start-up.
BUTTON_PINS = {Button.A: 5, Button.B: 6, Button.X: 16, Button.Y: 24}
LED_PINS = {LedChannel.RED: 17, LedChannel.GREEN: 27, LedChannel.BLUE: 22}

# The LED is startlingly bright at full duty in a dim room.
LED_BRIGHTNESS = 0.06

FONT_DIR = Path(__file__).parent / "fonts"
SCAN_DIR = Path.home() / "scans"
HTTP_PORT = 8080
# All interfaces: the whole point is that a phone on the LAN can reach it.
BIND_ADDRESS = "0.0.0.0"  # noqa: S104

MARGIN = 10
DONE_SCREEN_SECONDS = 45

# USB interface class 07 is "printer" and is reported by any conforming device,
# so the printer is detected structurally rather than by model.
# Source: USB-IF Defined Class Codes, https://www.usb.org/defined-class-codes
PRINTER_INTERFACE_CLASS = "07"

# The one scan profile. There is deliberately no way to change these from the
# panel: a settings surface is a thing to get wrong, and the box exists to make
# scanning a document a single button press.
#
# Verified against `scanimage -A` on the fi-6130 itself, which is the only
# authority on the spellings -- the backend rejects anything else.
SCAN_SOURCE: str = "ADF Duplex"
SCAN_MODE = "Lineart"
SCAN_RESOLUTION_DPI = 300

# A4, in millimetres. NOT optional: the backend's own defaults are US Letter
# (215.9 x 279.4), and 279.4 mm is 17.6 mm shorter than A4 -- so left alone it
# quietly cuts the bottom off every page.
SCAN_PAGE_WIDTH_MM = 210
SCAN_PAGE_HEIGHT_MM = 297

# A SANE config directory holding only the backend we use. Debian enables 77
# by default and loads every one to enumerate devices, which measured 8.7
# seconds on this Pi against 0.03 with just this backend -- far too slow to sit
# in front of a scan. The trailing colon is load-bearing: it appends the
# default path, so the backend's own config is still found. A missing directory
# degrades to the default rather than failing, which is what makes this safe on
# a development machine.
SANE_CONFIG_DIR = "/etc/paperpi/sane:"

# This scanner hands back every page upside down, so each one is turned before
# it goes into the PDF. Measured, not assumed: a sheet with TOP written across
# it came back with the writing in the bottom fifth of the image, loaded the way
# the operator's guide says to load it.
#
# Page *order* deliberately has no such correction, and it is worth saying why
# so nobody adds one. The feeder takes from the bottom of the stack, and the
# guide says to load face-down -- which means flipping the document over, which
# puts page one at the bottom, which is exactly where the feeder starts. The two
# cancel out. An earlier version of this file reversed the pages in software and
# was wrong for anyone following the manual.
#
# If a different scanner replaces this one, re-measure rather than assume: write
# TOP on a sheet, number a second, scan them, and look at where the ink lands.
SCAN_ROTATION_DEGREES: int = 180

# Which backend drives the scanner. The full SANE device name carries a serial
# that changes with the unit, so the adapter finds the device by this prefix
# rather than pinning one machine's name into the source.
SCANNER_BACKEND = "fujitsu"

# SANE reports failures through a fixed set of status strings. These are the
# ones worth saying differently to someone standing at the machine; anything
# else reaches the display as SANE's own wording rather than being swallowed.
# Source: sane_strstatus(), sane-backends.
# How SANE says the feeder is empty. Named because it is not only a fault: it
# is also how every successful batch ends, so the adapter has to compare
# against it. Spelled once so the two readings cannot drift apart.
SCANNER_END_OF_FEED = "Document feeder out of documents"

SCANNER_FAULTS = {
    "Access to resource has been denied": "no permission for the scanner",
    "Device busy": "scanner is busy",
    "Document feeder jammed": "paper jam or double feed",
    SCANNER_END_OF_FEED: "no paper in the feeder",
    "Error during device I/O": "lost contact with the scanner",
    "Invalid argument": "the scanner refused these settings",
    "Operation was cancelled": "cancelled",
    "Out of memory": "out of memory",
    "Scanner cover is open": "cover open",
}
# IPP reports faults as standardised keywords, which is what makes them worth
# matching on -- but "media-empty" is not what someone standing at the machine
# calls it. Anything unmapped reaches the display as its raw keyword rather
# than being swallowed: an unnamed fault still needs to be visible.
# Source: IANA IPP registry, printer-state-reasons keywords --
# https://www.iana.org/assignments/ipp-registrations
# The registry rather than RFC 8011: several of these, `offline` among them,
# are registered additions the RFC's own enumeration does not carry.
PRINTER_FAULTS = {
    "connecting-to-device": "connecting",
    "cover-open": "cover open",
    "door-open": "door open",
    "marker-supply-empty": "out of ink",
    "marker-supply-low": "ink low",
    "media-empty": "out of paper",
    "media-jam": "paper jam",
    "media-needed": "out of paper",
    "offline": "offline",
    "paused": "paused",
    "shutdown": "powered off",
    "timed-out": "not responding",
    "toner-empty": "out of ink",
    "toner-low": "ink low",
}

# Scanners have no equivalent class -- most report vendor-specific -- so they
# are matched on vendor id. 04c5 is Fujitsu, who make the fi-6130.
# Source: USB-IF vendor ID registry, https://www.usb.org/sites/default/files/vendor_ids.pdf
SCANNER_USB_VENDORS = {"04c5": "Fujitsu"}

BACKGROUND = Rgb.from_hex("#0b0f14")
TEXT = Rgb.from_hex("#e6edf3")
MUTED = Rgb.from_hex("#8b98a5")
DIM = Rgb.from_hex("#232b35")
ACCENT = Rgb.from_hex("#58a6ff")

READINESS_COLOURS = {
    Readiness.READY: Rgb.from_hex("#3fb950"),
    Readiness.BUSY: Rgb.from_hex("#58a6ff"),
    Readiness.ABSENT: Rgb.from_hex("#6e7681"),
    Readiness.UNCONFIGURED: Rgb.from_hex("#d29922"),
    Readiness.ERROR: Rgb.from_hex("#f85149"),
}
