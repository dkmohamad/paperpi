"""Link building and the lookup that backs it."""

from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlparse

import pytest

from paperpi.models import ScanId
from paperpi.serve import _ROUTE, ScanLibrary

_ADDRESS = IPv4Address("192.168.1.246")


def _library(
    directory: Path | str, address: IPv4Address | None = _ADDRESS
) -> ScanLibrary:
    return ScanLibrary(
        directory=Path(directory),
        address=lambda: address,
        port=8080,
        hostname="paperpi.local",
    )


def test_url_for_should_be_short_enough_to_keep_the_qr_sparse():
    """The link stays compact because QR density scales with its length.

    A long URL pushes the code to a denser version, which on a 2-inch panel is
    the difference between a scan that resolves instantly and one that does
    not. 40 characters keeps it comfortable.
    """
    url = _library("/tmp").url_for(ScanId("a1b2c3d4"))
    assert url == "http://192.168.1.246:8080/s/a1b2c3d4"
    assert len(url) < 40


def test_url_for_should_fall_back_to_the_hostname_without_an_address():
    """A box with no address is still reachable by mDNS name."""
    url = _library("/tmp", address=None).url_for(ScanId("a1b2c3d4"))
    assert url == "http://paperpi.local:8080/s/a1b2c3d4"


def test_url_for_should_follow_the_address_when_the_lease_changes(scan_dir: Path):
    """The link is built from the address at the time it is handed out.

    A DHCP lease can change while the service runs. Sampling the address once
    at start-up would leave every later QR encoding an address the box no
    longer answers on -- a link that looks right, resolves to nothing, and
    gives no clue why.
    """
    current = [IPv4Address("192.168.1.246")]
    library = ScanLibrary(
        directory=scan_dir,
        address=lambda: current[0],
        port=8080,
        hostname="paperpi.local",
    )
    assert library.url_for(ScanId("a1b2c3d4")).startswith("http://192.168.1.246:")

    current[0] = IPv4Address("192.168.1.99")
    assert library.url_for(ScanId("a1b2c3d4")).startswith("http://192.168.1.99:")


def test_url_and_route_should_agree_on_the_same_path(scan_dir: Path):
    """Round-trip a built link back through the server's own route pattern.

    Building and parsing the URL are two halves of one policy. Each side has
    its own test above, but only this one fails if the prefix or the id shape
    changes on one side and not the other -- whose symptom is every link
    silently 404ing.
    """
    scan_id = ScanId("a1b2c3d4")
    path = urlparse(_library(scan_dir).url_for(scan_id)).path
    match = _ROUTE.match(path)
    assert match is not None, f"the server would not route its own url: {path}"
    assert match.group(1) == scan_id


def test_path_for_should_find_a_scan_by_its_content_id(scan_dir: Path):
    """The id in the filename is what resolves the link.

    The server keeps no index, so the directory is the only source of truth and
    cannot drift from it.
    """
    written = scan_dir / "2026-09-10-1423-a1b2c3d4.pdf"
    written.write_bytes(b"%PDF-1.4\n")
    assert _library(scan_dir).path_for(ScanId("a1b2c3d4")) == written


def test_path_for_should_refuse_an_id_that_is_not_an_id(scan_dir: Path):
    """A request naming a path rather than an id is rejected before any IO.

    This is the guard that stops the read-only server being walked out of its
    directory, so it is asserted rather than left to the route regex alone.
    """
    for hostile in ("../../etc/passwd", "a1b2*", "", "A1B2C3D4"):
        with pytest.raises(ValueError, match="not a scan id"):
            _library(scan_dir).path_for(ScanId(hostile))


def test_path_for_should_raise_when_no_document_carries_the_id(scan_dir: Path):
    """A well-formed id with no file behind it is a not-found, not an empty path."""
    with pytest.raises(FileNotFoundError, match="no scan with id"):
        _library(scan_dir).path_for(ScanId("deadbeef"))
