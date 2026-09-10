"""The render loop.

Holds one screen at a time and asks it three things each frame: has time moved
you on, has a press moved you on, and what do you look like. Every collaborator
is injected, including the clock and the sleep, so a test can run a whole
session in a few microseconds with no display attached.
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime

from .models import Rgb
from .ports import Buttons, Display
from .protocols import Screen
from .render.canvas import Canvas, Fonts

__all__ = ["run"]

logger = logging.getLogger(__name__)

# 20 fps while anything is moving -- the elapsed readout and the activity
# indicator want to look smooth.
_FRAME_SECONDS = 1 / 20

# ...but back off to this when the frame stops changing. Measured on a Pi 4, a
# full status render costs about 10 ms, so redrawing a resting screen twenty
# times a second burns roughly a quarter of a core to produce identical pixels.
# Presses are queued by the button adapter rather than polled, so backing off
# delays noticing one by at most this long and never loses it.
_IDLE_SECONDS = 0.15


def run(
    *,
    display: Display,
    buttons: Buttons,
    screen: Screen,
    fonts: Fonts,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
    running: Callable[[], bool] | None = None,
    frame_seconds: float = _FRAME_SECONDS,
    idle_seconds: float = _IDLE_SECONDS,
    max_frames: int | None = None,
) -> Screen:
    """Drive the display until asked to stop.

    Args:
        display: Where frames and the lamp colour go.
        buttons: Where presses come from.
        screen: The screen to start on.
        fonts: Faces to render with.
        now: The clock. Injected so tests need no real time.
        sleep: How to wait between frames.
        running: Asked each frame; the loop stops when it returns False.
        frame_seconds: Target time per frame while the display is changing.
        idle_seconds: Longest gap between frames once it stops changing.
        max_frames: Stop after this many frames. Used by tests; None runs until
            `running` says otherwise.

    Returns:
        The screen that was showing when the loop stopped, so a caller or test
        can assert on where it ended up.
    """
    keep_going = running if running is not None else _forever
    canvas = Canvas.blank(fonts)
    frames = 0
    shown: bytes | None = None
    lit: Rgb | None = None
    interval = frame_seconds

    while keep_going():
        if max_frames is not None and frames >= max_frames:
            break
        started = time.monotonic()
        moment = now()

        screen = _advance(screen, screen.on_tick(moment))
        for button in buttons.pressed():
            following = screen.on_button(button)
            if following is not None:
                screen = following
                # A press that changes screen is consumed by that change; the
                # next screen should not also receive it.
                break

        canvas.clear()
        screen.render(canvas)

        # Measured on a Pi 4: rendering a frame costs about 4 ms, pushing one
        # over SPI costs 38 ms, and comparing two costs 0.2 ms. A resting
        # status screen is identical frame to frame, so pushing it twenty times
        # a second spends most of a core redrawing something nobody changed.
        current = canvas.image.tobytes()
        if current != shown:
            display.show(canvas.image)
            shown = current
            interval = frame_seconds
        else:
            interval = min(interval * 2, idle_seconds)
        if screen.led != lit:
            display.set_led(screen.led)
            lit = screen.led

        frames += 1
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            sleep(remaining)

    return screen


# --- private ---------------------------------------------------------------


def _forever() -> bool:
    return True


def _advance(current: Screen, following: Screen | None) -> Screen:
    if following is None:
        return current
    logger.debug("screen %s -> %s", type(current).__name__, type(following).__name__)
    return following
