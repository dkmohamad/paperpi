"""Text fitting, which is measured against the font rather than counted."""

from PIL import ImageChops

from paperpi import config
from paperpi.models import Rgb
from paperpi.render.canvas import _ROW_HEIGHT, _ROW_TOP, Canvas, Fonts

_ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"


def _width(canvas: Canvas, text: str, fonts: Fonts) -> float:
    return canvas._draw.textlength(text, font=fonts.detail)


def test_truncated_should_leave_text_that_already_fits_alone(fonts: Fonts):
    """Short text is returned unchanged, with no ellipsis added."""
    canvas = Canvas.blank(fonts)
    assert canvas.truncated("short.pdf", fonts.detail, 300) == "short.pdf"


def test_truncated_should_drop_the_middle_and_keep_both_ends(fonts: Fonts):
    """A filename keeps its date and its id; the middle is what goes.

    This is what makes the Done screen useful: the scan is identified by when
    it was made and by the content hash in its name, and losing either end
    would leave a label that names nothing.
    """
    canvas = Canvas.blank(fonts)
    result = canvas.truncated("2026-09-10-1423-a1b2c3d4.pdf", fonts.detail, 120)
    assert _ELLIPSIS in result
    assert result.startswith("2026")
    assert result.endswith(".pdf")
    assert _width(canvas, result, fonts) <= 120


def test_elided_should_drop_the_tail_and_mark_it(fonts: Fonts):
    """Prose keeps its beginning, and says that there was more.

    The opposite end from `truncated`, deliberately: a reader following a
    sentence needs the start, and the mark at the end is the only signal that
    something was cut.
    """
    canvas = Canvas.blank(fonts)
    result = canvas.elided("the scanner reported a paper jam", fonts.detail, 100)
    assert result.startswith("the")
    assert result.endswith(_ELLIPSIS)
    assert _width(canvas, result, fonts) <= 100


def test_wrapped_should_fill_lines_to_the_measured_width(fonts: Fonts):
    """Every produced line fits the space it will be drawn in.

    Measured rather than counted: at 14px DejaVu Sans, "IIIIIIIIII" and
    "MMMMMMMMMM" are the same ten characters and nearly three times different
    in width, so a character budget would overflow on one and waste space on
    the other.
    """
    canvas = Canvas.blank(fonts)
    message = " ".join(["word"] * 40)
    lines = canvas.wrapped(message, fonts.detail, 200, 3)
    assert 1 < len(lines) <= 3
    for line in lines:
        assert _width(canvas, line, fonts) <= 200


def test_wrapped_should_mark_a_message_it_had_to_cut(fonts: Fonts):
    """Running out of lines is signalled, not silent.

    On the error screen the message is the entire content, so dropping the
    tail without a mark leaves the reader believing they have the whole story.
    """
    canvas = Canvas.blank(fonts)
    lines = canvas.wrapped(
        " ".join(f"word{n}" for n in range(80)), fonts.detail, 200, 3
    )
    assert len(lines) == 3
    assert lines[-1].endswith(_ELLIPSIS)


def test_wrapped_should_not_mark_a_message_that_fits(fonts: Fonts):
    """A short message is shown whole, with nothing implying it was cut."""
    canvas = Canvas.blank(fonts)
    lines = canvas.wrapped("paper jam", fonts.detail, 200, 3)
    assert lines == ["paper jam"]


def test_wrapped_should_always_return_at_least_one_line(fonts: Fonts):
    """An empty message still renders, rather than indexing into nothing.

    The error screen loops over the result; returning an empty list would turn
    a blank message into a screen showing no explanation at all.
    """
    canvas = Canvas.blank(fonts)
    assert canvas.wrapped("", fonts.detail, 200, 3) == [""]


def test_a_long_row_detail_should_not_overprint_the_label(fonts: Fonts):
    """The label is left-aligned and the detail right-aligned on one line.

    Nothing stops them meeting in the middle, and when they do the row is
    unreadable rather than merely ugly -- which matters most in the state it
    happens in, a fault, where the row is the only thing reporting it.

    The oracle is the rendered pixels, not the arithmetic: the label is drawn
    once alone to find where it actually ends, then again beside an absurd
    detail. If the detail encroached, those pixels would differ.
    """
    dot = Rgb(255, 0, 0)
    band = (0, _ROW_TOP, config.DISPLAY_WIDTH, _ROW_TOP + _ROW_HEIGHT)
    # Against the background rather than against black: the panel's ground is
    # a dark blue, so getbbox() alone would call every pixel occupied.
    empty = Canvas.blank(fonts).image

    alone = Canvas.blank(fonts)
    alone.row(0, dot, "PRINTER", "")
    drawn = ImageChops.difference(alone.image, empty).crop(band).getbbox()
    assert drawn is not None, "the label drew nothing, so this proves nothing"
    label_end = drawn[2]

    crowded = Canvas.blank(fonts)
    crowded.row(
        0,
        dot,
        "PRINTER",
        "a device with an implausibly long product string \N{MIDDLE DOT} out of paper",
    )

    label_region = (0, _ROW_TOP, label_end, _ROW_TOP + _ROW_HEIGHT)
    assert alone.image.crop(label_region).tobytes() == (
        crowded.image.crop(label_region).tobytes()
    )
