"""Driving the document scanner through SANE.

`scanimage` is a subprocess that runs for the length of a scan -- tens of
seconds for a full feeder -- and assembling the PDF afterwards is real work on
a Pi. `poll()` is called from inside the render loop, so neither can happen
there. A worker thread owns the subprocess and the assembly, and puts finished
events on a queue; `poll()` only drains it.

The pages arrive as TIFFs and leave as one PDF. Pillow does that with no extra
dependency: it encodes 1-bit images as CCITT G4, so a 12-page lineart document
is tens of kilobytes rather than tens of megabytes.
"""

import logging
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from PIL import Image

from .. import config
from ..models import (
    PageScanned,
    ScanEvent,
    ScanFailed,
    ScannerLookup,
    ScanStarted,
    Side,
)
from ..ports import ScanHandle, ScannerDevice
from ..scans import write_scan

__all__ = [
    "DeviceListing",
    "SaneScanner",
    "ScanProcess",
    "Spawn",
    "find_device",
    "make_scanner_probe",
]

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 10

# How long to wait before looking for a scanner again, having found none, and
# the ceiling that wait backs off to.
#
# The ceiling is the important number, and it is a hardware concern rather than
# a performance one. Listing devices issues a driver command, and the operator's
# guide lists that among the things that wake the scanner from power save -- so
# a probe that repeats forever at a fixed interval holds the scanning lamp lit
# for as long as the box is on. That lamp is a cold-cathode tube: it has a
# finite life, it is not in the manual's consumables table, and there is no
# counter for it, so wearing it out is both invisible and not a thing anyone can
# put right. Backing off past the scanner's own fifteen-minute power-save
# timeout means a scanner we cannot reach is retried often enough to recover
# quickly from a start-up race, and rarely enough to let the lamp go out.
_RETRY_SECONDS = 1.0
_MAX_RETRY_SECONDS = 20 * 60.0


class ScanProcess(Protocol):
    """The part of a running `scanimage` this adapter actually uses.

    Narrower than `subprocess.Popen` on purpose: naming the concrete class here
    would mean a test could only stand in for it by being one.
    """

    @property
    def stderr(self) -> Iterable[str] | None:
        """Its diagnostics, read a line at a time as the scan proceeds."""
        ...

    def wait(self) -> int:
        """Block until it exits, and give its status."""
        ...

    def poll(self) -> int | None:
        """Its status if it has exited, else None. Never blocks."""
        ...

    def terminate(self) -> None:
        """Ask it to stop."""
        ...


# How to start one. Injected so the whole adapter can be driven by a scripted
# `scanimage` and no scanner, per the repo's inject-never-patch rule.
type Spawn = Callable[[Sequence[str]], ScanProcess]

# How to ask SANE what is attached. A plain "give me the listing" rather than
# a second process seam: listing devices has no lifecycle to manage, and a
# test standing in for it should not have to pretend to be a subprocess.
type DeviceListing = Callable[[], str]


def find_device(
    *, listing: DeviceListing | None = None, backend: str = config.SCANNER_BACKEND
) -> ScannerLookup:
    """Ask the scanning software what it can see.

    Matched on the backend prefix rather than the full name. The full name
    carries the unit's own identifiers, so pinning one into the source would
    mean a replacement scanner silently stopped working -- and this box has a
    second SANE device on it, the printer's flatbed, which must never be
    chosen by accident.

    Args:
        listing: How to obtain SANE's device list. Injected for tests.
        backend: The backend whose devices count as ours.

    Returns:
        What was found, and whether there was anything to ask. Never raises: a
        scanner that cannot be found is a state to report, not a failure to
        handle. The distinction matters -- software that is absent and software
        that got no answer look the same to the caller otherwise, and only one
        of them is fixed by installing something.
    """
    read = listing if listing is not None else _device_listing
    try:
        text = read()
    except FileNotFoundError:
        # No scanimage on this machine at all, which is every development
        # machine and any Pi where the install step was skipped.
        logger.debug("no scanning software installed")
        return ScannerLookup(installed=False)
    except (OSError, subprocess.SubprocessError):
        logger.debug("the scanning software failed to answer", exc_info=True)
        return ScannerLookup(installed=True)
    for line in text.splitlines():
        if line.startswith(f"{backend}:"):
            return ScannerLookup(installed=True, device=line.strip())
    return ScannerLookup(installed=True)


class SaneScanner:
    """Starts scans on a SANE device, one at a time.

    Attributes:
        scan_dir: Where the finished PDF is written.
    """

    def __init__(
        self,
        *,
        scan_dir: Path,
        now: Callable[[], datetime],
        device: str | None = None,
        spawn: Spawn | None = None,
        find: ScannerDevice = find_device,
    ):
        self._scan_dir = scan_dir
        self._now = now
        self._device = device
        self._spawn = spawn if spawn is not None else _spawn
        self._find = find

    def start(self) -> ScanHandle:
        """Begin a scan.

        Returns immediately. The device is looked up on the worker thread, not
        here: this is called from a button handler inside the render loop, and
        listing SANE devices spawns a process -- fast against the trimmed
        backend list, but seconds against the system default, which is what a
        box that skipped the config install would get. Resolving per scan
        rather than once at start-up is what lets a scanner be unplugged and
        plugged back in without a restart.

        Returns:
            A handle whose events arrive as the scanner produces them.
        """
        return _SaneScanHandle(
            scan_dir=self._scan_dir,
            device=self._device,
            find=self._find,
            spawn=self._spawn,
            started_at=self._now(),
            now=self._now,
        )


def make_scanner_probe(
    *, find: ScannerDevice = find_device, retry_after: float = _RETRY_SECONDS
) -> ScannerDevice:
    """A scanner lookup that answers at once and refreshes behind itself.

    `find_device` spawns a process. That is fast against the trimmed backend
    list and slow -- seconds -- against the system default, which is what a box
    that skipped the config install has. Either way it has no business on the
    thread drawing the display, so the answer is kept and the work is done
    elsewhere.

    The first call reports nothing, because nothing is known yet; a moment
    later the answer is there. That is the honest shape for a display that
    redraws twice a second, and it is why a failed lookup is retried rather
    than remembered: access to the scanner is granted asynchronously when it is
    plugged in, so "on the bus but not yet reachable" is the ordinary case at
    boot, not an error.

    Args:
        find: The real lookup. Injected for tests.
        retry_after: How long to wait before asking again, having found nothing.

    Returns:
        Something satisfying `ScannerDevice` that never blocks its caller.
    """
    return _BackgroundProbe(find=find, retry_after=retry_after)


class _BackgroundProbe:
    """Holds the last answer, and fetches a new one off-thread when it lacks one."""

    def __init__(self, *, find: ScannerDevice, retry_after: float):
        self._find = find
        self._retry_after = retry_after
        self._lock = threading.Lock()
        self._found: ScannerLookup | None = None
        self._asked_at: float | None = None
        self._running = False
        self._failures = 0

    def __call__(self) -> ScannerLookup:
        """What was last found, starting a fresh look if one is due."""
        with self._lock:
            unresolved = self._found is None or not self._found.device
            if unresolved and not self._running and self._due():
                self._running = True
                threading.Thread(target=self._look, daemon=True).start()
            # Before the first look has returned there is nothing to report,
            # and claiming the software is missing would be a guess.
            return self._found if self._found is not None else ScannerLookup(True)

    def _due(self) -> bool:
        """Whether enough time has passed to be worth asking again.

        The wait doubles with each failure. A scanner that has just been
        plugged in is usually reachable within a second or two, so the first
        retries are quick; one that is not coming back is left alone.
        """
        if self._asked_at is None:
            return True
        wait = min(self._retry_after * 2**self._failures, _MAX_RETRY_SECONDS)
        return time.monotonic() - self._asked_at >= wait

    def _look(self) -> None:
        try:
            found = self._find()
        except Exception:
            logger.debug("looking for a scanner failed", exc_info=True)
            found = ScannerLookup(installed=True)
        with self._lock:
            self._found = found
            self._asked_at = time.monotonic()
            self._running = False
            self._failures = 0 if found.device else self._failures + 1


class _SaneScanHandle:
    """One run of the scanner, with a thread behind it."""

    def __init__(
        self,
        *,
        scan_dir: Path,
        device: str | None,
        find: ScannerDevice,
        spawn: Spawn,
        started_at: datetime,
        now: Callable[[], datetime],
    ):
        self._scan_dir = scan_dir
        self._device = device
        self._find = find
        self._spawn = spawn
        self._started_at = started_at
        self._now = now
        self._events: queue.Queue[ScanEvent] = queue.Queue()
        self._process: ScanProcess | None = None
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._finished = False

        self._events.put(ScanStarted(at=started_at))
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def poll(self) -> Sequence[ScanEvent]:
        """Return whatever the worker has finished with since the last call.

        Returns:
            Possibly empty. Never blocks, and never touches the subprocess.
        """
        drained: list[ScanEvent] = []
        while True:
            try:
                drained.append(self._events.get_nowait())
            except queue.Empty:
                return drained

    def cancel(self) -> None:
        """Ask the scan to stop.

        Terminating the subprocess makes the worker take the same path as any
        other failure, so cancellation is not a second way for a run to end.
        """
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def _emit(self, event: ScanEvent) -> None:
        """Put the run's one and only terminal event.

        The contract says nothing follows a terminal event. Enforced here
        rather than reasoned about, because the paths that could break it are
        the error paths -- the ones least likely to be exercised.
        """
        if self._finished:
            logger.debug("suppressed a second terminal event: %r", event)
            return
        self._finished = True
        self._events.put(event)

    # --- everything below runs on the worker thread ------------------------

    def _run(self) -> None:
        """Scan, assemble, and report. Never lets an exception escape."""
        try:
            # On the scan drive rather than /tmp: /tmp is a tmpfs here, and
            # the page images are uncompressed -- about 1 MB per A4 side at
            # this resolution, so a full 50-sheet hopper is ~100 MB that would
            # otherwise sit in RAM alongside the decoded copies the assembly
            # holds. On disk a huge batch runs out of disk, which is
            # recoverable, rather than out of memory, which is not.
            self._scan_dir.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix=".paperpi-scan-", dir=self._scan_dir
            ) as directory:
                self._scan_into(Path(directory))
        except Exception:
            # The render loop cannot see this thread, so an escaping exception
            # would hang the scan screen forever with no explanation.
            logger.exception("the scan worker failed")
            self._emit(ScanFailed(message="the scan failed unexpectedly"))

    def _scan_into(self, directory: Path) -> None:
        device = self._device or self._find().device
        if not device:
            # Never fall through to SANE's own choice: the printer's flatbed
            # answers SANE too, so "no device" must stop here rather than
            # quietly scan on the wrong machine.
            self._emit(ScanFailed(message="no scanner found"))
            return

        pattern = str(directory / "p%04d.tif")
        try:
            process = self._spawn(_command(device, pattern))
        except OSError:
            logger.exception("could not start scanimage")
            self._emit(ScanFailed(message="the scanner software is missing"))
            return

        # Published and re-checked under one lock: a cancel arriving between
        # the spawn and the assignment would otherwise be dropped, and the
        # operator would wait out the whole feeder before anything happened.
        with self._lock:
            self._process = process
            if self._cancelled.is_set():
                process.terminate()

        pages = 0
        failure: str | None = None
        stderr = process.stderr
        if stderr is None:
            self._emit(ScanFailed(message="the scanner produced no output"))
            return
        for line in stderr:
            page = _page_scanned(line)
            if page is not None:
                pages = page
                self._events.put(PageScanned(page=page, side=_side_of(page)))
                continue
            counted = _batch_total(line)
            if counted is not None:
                pages = counted
                continue
            failure = _sane_error(line) or failure
        process.wait()

        if self._cancelled.is_set():
            self._emit(ScanFailed(message="cancelled at the panel"))
            return
        self._finish(directory, pages, failure)

    def _finish(self, directory: Path, pages: int, failure: str | None) -> None:
        """Turn the outcome into one terminal event."""
        # An ADF batch always ends by running out of paper, so that message is
        # how a *successful* scan finishes. The page count is what separates
        # the two, and reading it the other way round would put an error on
        # screen after every good scan, or hand back a truncated document
        # after a jam.
        #
        # Two things this deliberately tolerates. `failure` is last-wins, and
        # a diagnostic we have no wording for is not treated as fatal once
        # pages exist: paper that has already been through the machine should
        # not be thrown away because a future release added an advisory line.
        # Only a fault we recognise discards a document.
        #
        # And the scanner's own Stop button reports as end-of-feed, so
        # stopping a run mid-stack yields a shorter document reported as
        # finished. That is the right outcome; it is recorded here because the
        # alternative reading -- that Stop is a fault path -- would send a
        # reader looking for a branch that does not exist.
        if failure is not None and _is_fault(failure):
            self._emit(ScanFailed(message=_wording(failure)))
            return
        if pages == 0:
            self._emit(ScanFailed(message=_wording(config.SCANNER_END_OF_FEED)))
            return

        images = sorted(directory.glob("*.tif"))
        if not images:
            self._emit(ScanFailed(message="the scanner produced no pages"))
            return
        self._emit(self._assemble(images))

    def _assemble(self, images: list[Path]):
        """Fold the page images into one PDF and write it.

        The page count is taken from the images themselves rather than from
        what the scanner said. They can disagree -- a final page that failed to
        write still gets counted in the batch summary -- and the number the
        display shows should describe the document that exists.

        Memory is bounded by the hopper: the save decodes every page, at about
        8 MB each, so a full 50-sheet duplex batch peaks near a quarter of this
        machine's RAM. Survivable, and the reason the scratch pages live on
        disk rather than adding to it.
        """
        for path in images:
            _straighten(path)
        opened = [Image.open(path) for path in images]
        buffer = BytesIO()
        opened[0].save(
            buffer,
            format="PDF",
            save_all=True,
            append_images=opened[1:],
            resolution=config.SCAN_RESOLUTION_DPI,
        )
        return write_scan(
            data=buffer.getvalue(),
            scan_dir=self._scan_dir,
            started_at=self._started_at,
            pages=len(images),
            duration=self._now() - self._started_at,
        )


# --- private ---------------------------------------------------------------

# Short: this runs off the render thread now, but a scanner that is not
# answering should be reported as absent quickly rather than held onto.

# SANE's status strings are not translated at runtime on this release -- the
# backend compiles its own i18n macro away and never binds gettext -- but the
# wording is what this module parses, so the locale is pinned anyway. It costs
# nothing and it means a future release that does wire up translation cannot
# quietly change what "finished" looks like.
_ENVIRONMENT = {
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "SANE_CONFIG_DIR": config.SANE_CONFIG_DIR,
}

# `Scanned page N.` is printed after a page is through, unlike `Scanning page
# N` which is printed before one is attempted -- and which appears even when
# the feeder turns out to be empty.
_SCANNED = re.compile(r"^Scanned page (\d+)\.")

# The authoritative count, printed once at the end.
_TOTAL = re.compile(r"^Batch terminated, (\d+) pages? scanned")

# scanimage prefixes its own diagnostics, sometimes with the call that failed.
_ERROR = re.compile(r"^scanimage: (?:[a-z_]+: )?(.+?)\s*$")

# Noise that is not a failure: the backend rounds the page size to its own step
# and says so on every single run.
_ROUNDED = re.compile(r"^scanimage: rounded value of ")


def _device_listing() -> str:
    """Ask scanimage what is attached, one device name per line."""
    finished = subprocess.run(
        ["scanimage", "--formatted-device-list", "%d%n"],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_SECONDS,
        env=_ENVIRONMENT,
        check=False,
    )
    return finished.stdout


def _spawn(command: Sequence[str]) -> ScanProcess:
    """Start `scanimage` with its output readable line by line."""
    return subprocess.Popen(
        list(command),
        # Discarded, not piped. A batch writes its pages to files and puts
        # nothing on stdout, and an unread pipe that ever did fill would block
        # the child forever -- leaving the scan with no terminal event at all,
        # which is the one thing the contract forbids. Listing devices is a
        # separate call that captures its own output.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=_ENVIRONMENT,
    )


def _command(device: str | None, pattern: str) -> list[str]:
    """Build the scanimage invocation for the one fixed profile."""
    command = ["scanimage"]
    if device is not None:
        command += ["-d", device]
    return command + [
        "--source",
        config.SCAN_SOURCE,
        "--mode",
        config.SCAN_MODE,
        "--resolution",
        str(config.SCAN_RESOLUTION_DPI),
        "--page-width",
        str(config.SCAN_PAGE_WIDTH_MM),
        "--page-height",
        str(config.SCAN_PAGE_HEIGHT_MM),
        "--format=tiff",
        f"--batch={pattern}",
    ]


def _straighten(path: Path) -> None:
    """Turn one page the right way up, in place.

    One page at a time and written back to disk rather than rotating the whole
    document in memory: the assembly already holds every page open, and this
    runs on a machine where a full hopper is a real fraction of the RAM.
    """
    if config.SCAN_ROTATION_DEGREES % 360 == 0:
        return
    with Image.open(path) as page:
        upright = page.rotate(config.SCAN_ROTATION_DEGREES, expand=True)
    upright.save(path, format="TIFF")


def _side_of(page: int) -> Side:
    """Which side of a sheet a page number refers to.

    Only meaningful because the profile is duplex and the backend feeds one
    sheet at a time, front first. A simplex profile would make every page a
    front, and blank-page skipping would break it outright -- which is one of
    the reasons that option stays off.
    """
    if config.SCAN_SOURCE != "ADF Duplex":
        return Side.FRONT
    return Side.FRONT if page % 2 else Side.BACK


def _page_scanned(line: str) -> int | None:
    """The number of a page that has finished, if this line reports one."""
    found = _SCANNED.match(line.strip())
    return int(found.group(1)) if found else None


def _batch_total(line: str) -> int | None:
    """The final page count, if this line carries it."""
    found = _TOTAL.match(line.strip())
    return int(found.group(1)) if found else None


def _sane_error(line: str) -> str | None:
    """The SANE status text from a diagnostic line, if it is one."""
    stripped = line.strip()
    if _ROUNDED.match(stripped):
        return None
    found = _ERROR.match(stripped)
    return found.group(1) if found else None


def _is_fault(failure: str) -> bool:
    """Whether a SANE status should cost us the document.

    End-of-feed never does: it is how a batch ends. Nor does a status we have
    no wording for, because that is as likely to be a new advisory as a new
    disaster, and discarding already-scanned paper on a guess is the more
    expensive mistake.
    """
    if failure == config.SCANNER_END_OF_FEED:
        return False
    return failure in config.SCANNER_FAULTS


def _wording(failure: str) -> str:
    """Say a SANE status in words that fit a panel and a person.

    An unmapped status is passed through rather than replaced with something
    vague: SANE's own wording is worse than ours but far better than nothing.
    """
    return config.SCANNER_FAULTS.get(failure, failure)
