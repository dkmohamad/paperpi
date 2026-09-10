"""A drawing surface with the display's shared furniture built in.

The title bar, footer and status rows appear on more than one screen, so they
live here rather than being re-measured in each. Screens deal in rows and
labels; only this module knows pixel coordinates.

Sizes are chosen for a 2-inch panel at arm's length, where the usual desktop
instinct produces text that cannot be read.
"""

from dataclasses import dataclass
from typing import Self

from PIL import Image, ImageDraw, ImageFont

from .. import config
from ..models import Rgb

__all__ = ["Canvas", "Fonts"]

_TITLE_HEIGHT = 30
_FOOTER_HEIGHT = 26
_ROW_HEIGHT = 34
_ROW_TOP = _TITLE_HEIGHT + 12
_DOT_RADIUS = 5


@dataclass(frozen=True, slots=True)
class Fonts:
    """The faces used across the display, loaded once.

    Attributes:
        title: Title bar.
        label: Row labels and other emphasis.
        detail: Secondary text beside a label.
        big: The single large readout on the scanning screen.
        footer: The hint strip along the bottom.
    """

    title: ImageFont.FreeTypeFont
    label: ImageFont.FreeTypeFont
    detail: ImageFont.FreeTypeFont
    big: ImageFont.FreeTypeFont
    footer: ImageFont.FreeTypeFont

    @classmethod
    def load(cls) -> Self:
        """Load the bundled faces.

        The font ships inside the package rather than coming from the system, so
        the preview on a development machine renders identically to the Pi --
        which has no fonts installed at all.

        Returns:
            The loaded faces.
        """
        regular = str(config.FONT_DIR / "DejaVuSans.ttf")
        bold = str(config.FONT_DIR / "DejaVuSans-Bold.ttf")
        return cls(
            title=ImageFont.truetype(bold, 15),
            label=ImageFont.truetype(bold, 15),
            detail=ImageFont.truetype(regular, 14),
            big=ImageFont.truetype(bold, 30),
            footer=ImageFont.truetype(regular, 12),
        )


class Canvas:
    """One frame being drawn.

    Wraps a Pillow image and the fonts, and offers the furniture the screens
    share. Screens never compute coordinates themselves.
    """

    def __init__(self, image: Image.Image, fonts: Fonts):
        self._image = image
        self._fonts = fonts
        self._draw = ImageDraw.Draw(image)

    @classmethod
    def blank(cls, fonts: Fonts) -> Self:
        """Build a canvas of the configured display size, filled with the ground.

        Args:
            fonts: Faces to draw with.

        Returns:
            A cleared canvas.
        """
        image = Image.new(
            "RGB",
            (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT),
            config.BACKGROUND.as_tuple(),
        )
        return cls(image, fonts)

    @property
    def image(self) -> Image.Image:
        """The frame drawn so far."""
        return self._image

    @property
    def fonts(self) -> Fonts:
        """The faces this canvas draws with."""
        return self._fonts

    def clear(self) -> None:
        """Reset to the background colour, discarding everything drawn."""
        self._draw.rectangle(
            (0, 0, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT),
            fill=config.BACKGROUND.as_tuple(),
        )

    def title(self, left: str, right: str = "") -> None:
        """Draw the title strip.

        Args:
            left: Primary label, drawn at the left.
            right: Secondary label, drawn right-aligned. Often an address or a
                running total.
        """
        self._draw.rectangle(
            (0, 0, config.DISPLAY_WIDTH, _TITLE_HEIGHT), fill=config.DIM.as_tuple()
        )
        self._draw.text(
            (config.MARGIN, _TITLE_HEIGHT // 2),
            left,
            font=self._fonts.title,
            fill=config.TEXT.as_tuple(),
            anchor="lm",
        )
        if right:
            self._draw.text(
                (config.DISPLAY_WIDTH - config.MARGIN, _TITLE_HEIGHT // 2),
                right,
                font=self._fonts.title,
                fill=config.MUTED.as_tuple(),
                anchor="rm",
            )

    def footer(self, text: str) -> None:
        """Draw the hint strip along the bottom.

        Args:
            text: What the buttons currently do.
        """
        top = config.DISPLAY_HEIGHT - _FOOTER_HEIGHT
        self._draw.rectangle(
            (0, top, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT),
            fill=config.DIM.as_tuple(),
        )
        self._draw.text(
            (config.DISPLAY_WIDTH // 2, top + _FOOTER_HEIGHT // 2),
            text,
            font=self._fonts.footer,
            fill=config.MUTED.as_tuple(),
            anchor="mm",
        )

    def row(self, index: int, dot: Rgb, label: str, detail: str) -> None:
        """Draw one status line: a coloured dot, a label, and evidence.

        Args:
            index: 0-based row position under the title bar.
            dot: Colour of the state indicator.
            label: Short uppercase name.
            detail: Secondary text, right of the label.
        """
        middle = _ROW_TOP + index * _ROW_HEIGHT + _ROW_HEIGHT // 2
        centre_x = config.MARGIN + _DOT_RADIUS
        self._draw.ellipse(
            (
                centre_x - _DOT_RADIUS,
                middle - _DOT_RADIUS,
                centre_x + _DOT_RADIUS,
                middle + _DOT_RADIUS,
            ),
            fill=dot.as_tuple(),
        )
        self._draw.text(
            (centre_x + _DOT_RADIUS + 10, middle),
            label,
            font=self._fonts.label,
            fill=config.TEXT.as_tuple(),
            anchor="lm",
        )
        self._draw.text(
            (config.DISPLAY_WIDTH - config.MARGIN, middle),
            detail,
            font=self._fonts.detail,
            fill=config.MUTED.as_tuple(),
            anchor="rm",
        )

    def centred(self, y: int, text: str, font: ImageFont.FreeTypeFont, colour: Rgb):
        """Draw text centred horizontally.

        Args:
            y: Vertical middle of the text.
            text: What to draw.
            font: Face to draw it in.
            colour: Ink colour.
        """
        self._draw.text(
            (config.DISPLAY_WIDTH // 2, y),
            text,
            font=font,
            fill=colour.as_tuple(),
            anchor="mm",
        )

    def text(
        self,
        xy: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        colour: Rgb,
        anchor: str = "la",
    ) -> None:
        """Draw text at an exact position.

        Args:
            xy: Anchor point.
            text: What to draw.
            font: Face to draw it in.
            colour: Ink colour.
            anchor: Pillow anchor code.
        """
        self._draw.text(xy, text, font=font, fill=colour.as_tuple(), anchor=anchor)

    def activity(self, y: int, phase: int, count: int = 6) -> None:
        """Draw a row of pips with one travelling along it.

        An indeterminate indicator on purpose: a sheet feeder does not know how
        many pages remain, so a proportional bar would be invented.

        Args:
            y: Vertical middle of the row.
            phase: Which pip is lit, taken modulo `count`.
            count: How many pips to draw.
        """
        gap = 16
        width = (count - 1) * gap
        start = config.DISPLAY_WIDTH // 2 - width // 2
        for index in range(count):
            lit = index == phase % count
            colour = config.ACCENT if lit else config.DIM
            radius = 4 if lit else 3
            x = start + index * gap
            self._draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=colour.as_tuple(),
            )

    def truncated(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        """Shorten text from the middle until it fits.

        Measured against the font rather than counted in characters, because a
        proportional face makes a character budget meaningless. The middle is
        dropped rather than the tail so a filename keeps both the part that
        dates it and the part that identifies it.

        Args:
            text: The full string.
            font: The face it will be drawn in.
            max_width: Space available, in pixels.

        Returns:
            The original if it fits, otherwise a shortened form with an
            ellipsis in place of the dropped middle.
        """
        if self._draw.textlength(text, font=font) <= max_width:
            return text
        ellipsis = "\N{HORIZONTAL ELLIPSIS}"
        keep = len(text)
        while keep > 2:
            keep -= 1
            head = (keep + 1) // 2
            tail = keep - head
            candidate = text[:head] + ellipsis + (text[-tail:] if tail else "")
            if self._draw.textlength(candidate, font=font) <= max_width:
                return candidate
        return ellipsis

    def elided(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        """Shorten text from the end until it fits.

        The counterpart to `truncated`, and the difference matters. A filename
        keeps its middle dropped so the date and the id both survive; prose
        keeps its beginning, because the reader is following a sentence and the
        mark at the end is what tells them there was more.

        Args:
            text: The full string.
            font: The face it will be drawn in.
            max_width: Space available, in pixels.

        Returns:
            The original if it fits, otherwise a shortened form ending in an
            ellipsis.
        """
        if self._draw.textlength(text, font=font) <= max_width:
            return text
        ellipsis = "\N{HORIZONTAL ELLIPSIS}"
        for keep in range(len(text) - 1, 0, -1):
            candidate = text[:keep].rstrip() + ellipsis
            if self._draw.textlength(candidate, font=font) <= max_width:
                return candidate
        return ellipsis

    def wrapped(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
        max_lines: int,
    ) -> list[str]:
        """Break text into lines that fit, measuring rather than counting.

        The same reasoning as `truncated`: a character budget means nothing in
        a proportional face. If the text needs more than `max_lines`, the last
        line is shortened with an ellipsis so the reader can see something was
        dropped -- silently losing the tail is worst on the one screen whose
        job is explaining a failure.

        Args:
            text: The full message.
            font: The face it will be drawn in.
            max_width: Space available per line, in pixels.
            max_lines: Most lines to return.

        Returns:
            Between one and `max_lines` lines.
        """
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and self._draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = word
                if len(lines) == max_lines:
                    break
            else:
                current = candidate

        if len(lines) < max_lines and current:
            lines.append(current)
        elif len(lines) == max_lines and current:
            lines[-1] = self.elided(f"{lines[-1]} {current}", font, max_width)
        return lines or [""]

    def paste(self, image: Image.Image, xy: tuple[int, int]) -> None:
        """Place another image onto this frame.

        Args:
            image: What to place.
            xy: Top-left corner.
        """
        self._image.paste(image, xy)
