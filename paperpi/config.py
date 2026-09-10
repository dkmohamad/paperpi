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
    "PRINTER_INTERFACE_CLASS",
    "READINESS_COLOURS",
    "SCANNER_USB_VENDORS",
    "SCAN_DIR",
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
