# pyright: reportMissingImports=false
# gpiozero and st7789 install only on the Pi (`uv sync --extra hat`). This
# module is never imported anywhere else, so there is nothing for pyright to
# resolve on a development machine. Scoped to this file so the rule stays on
# everywhere it can be enforced.
"""The Display HAT Mini itself.

Pimoroni's own `displayhatmini` package is not used. It has had no release
since 2022, and it drives the buttons and LED through `RPi.GPIO`, whose edge
detection raises on kernels from Bookworm onward -- this Pi runs trixie. Its
`__del__` also calls a global `GPIO.cleanup()`, which resets every GPIO the
process touched, at garbage-collection time.

Driving the parts directly costs a few dozen lines and gives one GPIO stack
(lgpio, via gpiozero) instead of two, with real debouncing and per-button
callbacks. The wiring constants it would have supplied live in `config`.
"""

from collections import deque
from collections.abc import Sequence
from functools import partial
from typing import Any

from PIL.Image import Image

from .. import config
from ..models import Button, LedChannel, Rgb

__all__ = ["HatButtons", "HatDisplay"]

# gpiozero's own debounce. The buttons are unshielded tactile switches next to
# a backlight supply, and without this a single press arrives two or three
# times.
_BOUNCE_SECONDS = 0.08


class HatDisplay:
    """The ST7789 panel and the RGB status lamp."""

    def __init__(self):
        # Imported here so the package can be imported -- and its screens
        # tested -- on a machine with no HAT and none of these installed.
        from gpiozero import PWMLED
        from st7789 import ST7789

        self._panel: Any = ST7789(
            port=config.SPI_PORT,
            cs=config.SPI_CS,
            dc=config.SPI_DC,
            backlight=config.SPI_BACKLIGHT,
            width=config.DISPLAY_WIDTH,
            height=config.DISPLAY_HEIGHT,
            rotation=config.SPI_ROTATION,
            spi_speed_hz=config.SPI_SPEED_HZ,
        )
        # Common-anode: the channels are driven against 3V3, so full duty is
        # off. active_high=False puts that inversion in one place.
        self._lamps = {
            channel: PWMLED(pin, active_high=False)
            for channel, pin in config.LED_PINS.items()
        }
        self._closed = False

    def show(self, image: Image) -> None:
        """Push a full frame to the panel."""
        if self._closed:
            return
        self._panel.display(image)

    def set_led(self, colour: Rgb) -> None:
        """Set the lamp, scaled down because it is painfully bright at full."""
        if self._closed:
            return
        # dimmed() rather than scaling each channel by hand: the brightness
        # policy then lives on the colour type, in one place.
        levels = dict(
            zip(
                LedChannel,
                colour.dimmed(config.LED_BRIGHTNESS).as_fractions(),
                strict=True,
            )
        )
        for channel, lamp in self._lamps.items():
            lamp.value = levels[channel]

    def close(self) -> None:
        """Darken the lamp and release the pins. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for lamp in self._lamps.values():
            lamp.value = 0
            lamp.close()


class HatButtons:
    """The four tactile buttons, collected as they are pressed."""

    def __init__(self):
        from gpiozero import Button as GpioButton

        self._presses: deque[Button] = deque()
        self._buttons: list[Any] = []
        self._closed = False

        for button, pin in config.BUTTON_PINS.items():
            # Active-low with a pull-up, which is how the HAT wires them.
            device: Any = GpioButton(pin, pull_up=True, bounce_time=_BOUNCE_SECONDS)
            device.when_pressed = partial(self._presses.append, button)
            self._buttons.append(device)

    def pressed(self) -> Sequence[Button]:
        """Return and clear the presses seen since the last call.

        gpiozero delivers callbacks on its own thread, so this drains a deque
        rather than reading pins: a press during a slow frame is queued, not
        lost.
        """
        drained: list[Button] = []
        while self._presses:
            drained.append(self._presses.popleft())
        return drained

    def close(self) -> None:
        """Release the pins. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for device in self._buttons:
            device.close()
