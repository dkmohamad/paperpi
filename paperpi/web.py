"""The page a phone opens to read a scan.

Deliberately self-contained: inline CSS, no JavaScript, no webfont, no CDN. The
person most likely to open this is standing next to the scanner on the house
wifi, which is exactly the situation where a page that waits on a remote asset
hangs. Everything needed to render is in the bytes served.

Pure -- values in, HTML out, no IO -- so the page can be tested without a
server, the same way the screens are tested without a panel.
"""

import html
from collections.abc import Callable, Sequence
from datetime import datetime

from .models import Scan, ScanId
from .render.format import format_size

__all__ = ["render_index"]

_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #14181d;
  --muted: #5f6b7a;
  --line: #e3e8ee;
  --accent: #0b5fd0;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b0f14;
    --fg: #e6edf3;
    --muted: #8b98a5;
    --line: #232b35;
    --accent: #58a6ff;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 17px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-text-size-adjust: 100%;
}
main { max-width: 34rem; margin: 0 auto; padding: 1.25rem 1rem 3rem; }
h1 { font-size: 1.4rem; margin: 0 0 .15rem; }
.count { color: var(--muted); margin: 0 0 1.25rem; font-size: .95rem; }
ul { list-style: none; margin: 0; padding: 0; }
li { border-top: 1px solid var(--line); }
li:last-child { border-bottom: 1px solid var(--line); }
a {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
  /* Generous vertical padding: this is a thumb target, not a mouse target. */
  padding: 1rem .25rem;
  text-decoration: none;
  color: inherit;
}
a:hover .when, a:focus .when { color: var(--accent); }
.when { font-weight: 600; }
.size { color: var(--muted); font-size: .9rem; white-space: nowrap; }
.empty { color: var(--muted); padding: 2rem .25rem; border-top: 1px solid var(--line); }
footer { color: var(--muted); font-size: .8rem; margin-top: 2rem; }
"""


def render_index(
    scans: Sequence[Scan],
    path_for: Callable[[ScanId], str],
    now: datetime,
) -> str:
    """Render the list of scans as a standalone HTML page.

    Args:
        scans: Newest first. Rendered in the order given.
        path_for: Turns a scan id into the path that serves it. Injected rather
            than built here so the URL is defined in exactly one place.
        now: Used to phrase dates relatively. Injected so the output is
            deterministic in a test.

    Returns:
        A complete HTML document.
    """
    if scans:
        count = f"{len(scans)} document{'s' if len(scans) != 1 else ''}"
        body = "<ul>\n" + "\n".join(_row(s, path_for, now) for s in scans) + "\n</ul>"
    else:
        count = "nothing here yet"
        body = (
            '<p class="empty">No scans yet. Press a button on the scanner and '
            "this page will list what comes out.</p>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>paperpi scans</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<h1>Scans</h1>
<p class="count">{html.escape(count)}</p>
{body}
<footer>paperpi</footer>
</main>
</body>
</html>
"""


# --- private ---------------------------------------------------------------


def _row(scan: Scan, path_for: Callable[[ScanId], str], now: datetime) -> str:
    href = html.escape(path_for(scan.scan_id))
    when = html.escape(_when(scan.modified, now))
    size = html.escape(format_size(scan.size_bytes))
    return (
        f'<li><a href="{href}">'
        f'<span class="when">{when}</span>'
        f'<span class="size">{size}</span>'
        "</a></li>"
    )


def _when(modified: datetime, now: datetime) -> str:
    """Phrase a timestamp the way someone looking for a scan would think of it.

    A scan is usually being retrieved minutes after it was made, so "Today" and
    "Yesterday" carry more meaning than a date. Older ones get the date, and the
    year only once it is not the current one.
    """
    delta_days = (now.date() - modified.date()).days
    clock = modified.strftime("%H:%M")
    if delta_days == 0:
        return f"Today {clock}"
    if delta_days == 1:
        return f"Yesterday {clock}"
    if modified.year == now.year:
        return f"{modified.strftime('%-d %b')} {clock}"
    return f"{modified.strftime('%-d %b %Y')} {clock}"
