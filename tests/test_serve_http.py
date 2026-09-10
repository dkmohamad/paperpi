"""The file server, exercised over a real socket.

The route regex is the first line of defence against a request naming a path
instead of a scan, and until this file existed it had never been watched
refuse anything.
"""

import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path

import pytest

from paperpi.serve import ScanLibrary, serve_in_background

_PDF = b"%PDF-1.4\nnot really a pdf\n"

Server = tuple[ThreadingHTTPServer, str]


@pytest.fixture
def server(scan_dir: Path) -> Iterator[Server]:
    """A running server on an ephemeral port, torn down after the test."""
    (scan_dir / "2026-09-10-1423-a1b2c3d4.pdf").write_bytes(_PDF)
    library = ScanLibrary(
        directory=scan_dir,
        address=lambda: IPv4Address("127.0.0.1"),
        port=0,
        hostname="paperpi.local",
    )
    running = serve_in_background(library)
    host, port = running.server_address[0], running.server_address[1]
    try:
        yield running, f"http://{host}:{port}"
    finally:
        running.shutdown()
        running.server_close()


def _get(url: str) -> tuple[int, bytes, dict[str, str]]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def test_a_known_scan_should_be_served_inline_as_a_pdf(server: Server):
    """The document comes back with headers that make a phone display it.

    `inline` rather than `attachment` is the whole point of the QR: the reader
    should see the scan, not a downloaded file they then have to find.
    """
    _, base = server
    status, body, headers = _get(f"{base}/s/a1b2c3d4")
    assert status == 200
    assert body == _PDF
    assert headers["Content-Type"] == "application/pdf"
    assert headers["Content-Disposition"].startswith("inline")


def test_the_route_should_refuse_anything_that_is_not_a_scan_link(server: Server):
    """Paths that are not a scan id are rejected before any file is touched.

    Includes a traversal attempt: the id pattern, not the filesystem, is what
    stops a read-only server being walked out of its directory.
    """
    _, base = server
    for path in (
        "/s/../../etc/passwd",
        "/s/A1B2C3D4",
        "/s/",
        "/s/zzzz",
        "/etc/passwd",
        "/s/a1b2c3d4/../../etc/passwd",
        "/../index.html",
    ):
        status, _, _ = _get(f"{base}{path}")
        assert status == 404, f"{path} should not have been served"


def test_the_index_should_list_the_scans_on_the_drive(server: Server):
    """Browsing the root returns a page naming the scans and linking to them.

    This is the route the household actually uses: no app, no client setup, no
    login, identical on Android, iPhone and a laptop.
    """
    _, base = server
    status, body, headers = _get(f"{base}/")
    page = body.decode()
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "/s/a1b2c3d4" in page


def test_the_index_should_not_be_cached(server: Server):
    """A stale list hides the scan the reader just made.

    The drive changes the moment a scan finishes, and the whole point of
    opening this page is to find the newest document.
    """
    _, base = server
    _, _, headers = _get(f"{base}/")
    assert headers.get("Cache-Control") == "no-store"


def test_a_well_formed_id_with_no_file_should_be_not_found(server: Server):
    """A plausible id that names nothing is a 404, not an error page."""
    _, base = server
    status, _, _ = _get(f"{base}/s/deadbeef")
    assert status == 404
