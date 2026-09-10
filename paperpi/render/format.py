"""Turning quantities into the short strings a small panel can hold."""

from datetime import timedelta

__all__ = ["format_duration", "format_size"]


def format_duration(elapsed: timedelta) -> str:
    """Render a duration as m:ss, or h:mm:ss once it runs past an hour.

    Args:
        elapsed: The duration.

    Returns:
        A compact string with no leading zero on the first field.
    """
    total = int(elapsed.total_seconds())
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_size(size_bytes: int) -> str:
    """Render a byte count in the largest unit that keeps it under 1000.

    Args:
        size_bytes: The count.

    Returns:
        A string such as `2.4 MB`. Bytes and kilobytes are shown whole, since a
        fractional byte reads as noise.
    """
    if size_bytes < 1000:
        return f"{size_bytes} B"
    if size_bytes < 1000 * 1000:
        return f"{size_bytes / 1000:.0f} kB"
    if size_bytes < 1000 * 1000 * 1000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    return f"{size_bytes / 1_000_000_000:.1f} GB"
