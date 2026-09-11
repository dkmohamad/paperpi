"""Serving the scans over HTTP.

This is the only way documents leave the box. An SMB share existed briefly and
was removed: no browser opens `smb://`, Android has no SMB client in its stock
file manager, and the setup friction meant nobody at home would have used it.
A web page needs nothing installed and works the same on every device.

Two routes, and the split is deliberate. `/` lists the scans, for someone
looking for a document. `/s/<id>` serves one, and is what the QR on the Done
screen encodes -- a capability link that opens the document just produced in a
single motion, with nothing to type.

Lookup is by the scan's content-derived id, recovered from the filename, so the
server holds no state that could disagree with the directory.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

from . import config
from .models import Scan, ScanId
from .scans import ID, scans_in
from .web import render_index

__all__ = ["ScanLibrary", "serve_in_background"]

logger = logging.getLogger(__name__)

# One definition of the link, used in both directions. Building and parsing a
# URL are two halves of a single policy: spelled separately they drift, and the
# failure mode is every link silently 404ing.
_PREFIX = "/s/"
_SAVE_PREFIX = "/d/"
_ID_PATTERN = re.compile(rf"^{ID}$")
_ROUTE = re.compile(rf"^{re.escape(_PREFIX)}({ID})$")
_SAVE_ROUTE = re.compile(rf"^{re.escape(_SAVE_PREFIX)}({ID})$")


def _path_for(scan_id: ScanId) -> str:
    """The path half of a scan's link. The only place it is constructed."""
    return f"{_PREFIX}{scan_id}"


def _save_path_for(scan_id: ScanId) -> str:
    """The same document, asked for as a file rather than a page.

    Two URLs for one document is the settled way to offer both readings: no
    response header can make a browser's own share command hand over the bytes
    of a page it is displaying, so getting a scan into another app means
    downloading it first. A second path rather than a query parameter, so both
    readings stay as easy to parse as they are to build.
    """
    return f"{_SAVE_PREFIX}{scan_id}"


@dataclass(frozen=True, slots=True)
class ScanLibrary:
    """The finished scans on disk, addressed by id.

    Attributes:
        directory: Where scans are written.
        address: Asked for the current address each time a link is built, not
            sampled once. A lease can change while the service runs, and a QR
            encoding yesterday's address is a link that asserts reachability
            and is wrong, with nothing to signal it.
        port: The port the server listens on.
        hostname: Used when there is no address.
    """

    directory: Path
    address: Callable[[], IPv4Address | None]
    port: int
    hostname: str

    def url_for(self, scan_id: ScanId) -> str:
        """Build the link encoded in the QR code.

        Kept short on purpose: every character pushes the code toward a denser
        version, and a dense code on a 2-inch panel is one a phone struggles to
        resolve.

        Args:
            scan_id: The scan's id.

        Returns:
            An absolute http URL.
        """
        current = self.address()
        host = str(current) if current is not None else self.hostname
        return f"http://{host}:{self.port}{_path_for(scan_id)}"

    def all(self) -> list[Scan]:
        """List every scan on the drive, newest first."""
        return scans_in(self.directory)

    def path_for(self, scan_id: ScanId) -> Path:
        """Find the document with this id.

        Args:
            scan_id: The scan's id.

        Returns:
            Path to the file.

        Raises:
            ValueError: If the id is not the shape an id can be.
            FileNotFoundError: If no document carries it.
        """
        if not _ID_PATTERN.match(scan_id):
            raise ValueError(f"not a scan id: {scan_id!r}")
        # Newest first: the id is a content hash, so re-scanning an identical
        # document produces the same id under a later timestamp. The most
        # recent is the one the link was just handed out for.
        for candidate in sorted(self.directory.glob(f"*-{scan_id}.pdf"), reverse=True):
            return candidate
        raise FileNotFoundError(f"no scan with id {scan_id}")


def serve_in_background(library: ScanLibrary) -> ThreadingHTTPServer:
    """Start the file server on a daemon thread.

    Args:
        library: The scans to serve and the port to serve them on.

    Returns:
        The running server, so a caller can shut it down.
    """
    handler = partial(_ScanRequestHandler, library)
    server = ThreadingHTTPServer((config.BIND_ADDRESS, library.port), handler)
    thread = threading.Thread(
        target=server.serve_forever, name="paperpi-http", daemon=True
    )
    thread.start()
    logger.info("serving scans from %s on port %d", library.directory, library.port)
    return server


# --- private ---------------------------------------------------------------


class _ScanRequestHandler(BaseHTTPRequestHandler):
    """Serves one route, read-only, and refuses everything else."""

    def __init__(self, library: ScanLibrary, *args: Any, **kwargs: Any):
        self._library = library
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # the base class dictates this name
        """Serve the index, or a scan by id, or 404."""
        if self.path in ("/", "/index.html"):
            self._send_index()
            return

        match = _ROUTE.match(self.path)
        save = _SAVE_ROUTE.match(self.path) if match is None else None
        found = match or save
        if found is None:
            self.send_error(404, "not found")
            return

        try:
            path = self._library.path_for(ScanId(found.group(1)))
        except (ValueError, FileNotFoundError):
            self.send_error(404, "not found")
            return

        # Separated from the lookup so a real IO failure is not reported as a
        # missing file. Answering 404 to a permissions error would hide a
        # broken share behind a message that says the scan does not exist.
        try:
            payload = path.read_bytes()
        except OSError:
            logger.exception("could not read %s", path)
            self.send_error(500, "could not read scan")
            return

        # The same bytes, offered two ways. `inline` is what the QR link uses:
        # scan the code and the document opens, which is the point of it.
        # `attachment` is what the download icon uses, because a phone can only
        # share a *file* -- share from the browser and it sends the address,
        # which arrives at the other end as a few dozen bytes of text wearing a
        # .pdf name.
        disposition = "inline" if save is None else "attachment"
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Content-Disposition", f'{disposition}; filename="{path.name}"'
        )
        self.end_headers()
        self.wfile.write(payload)

    def _send_index(self) -> None:
        """Render the list of scans as a page any browser can read."""
        try:
            scans = self._library.all()
        except OSError:
            logger.exception("could not list %s", self._library.directory)
            self.send_error(500, "could not list scans")
            return

        payload = render_index(scans, _path_for, _save_path_for, datetime.now()).encode(
            "utf-8"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        # The drive changes whenever a scan finishes, so a cached list would
        # hide the scan the user just made -- which is the one they want.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Route request logging through the module logger, not stderr."""
        logger.debug("http %s", format % args)
