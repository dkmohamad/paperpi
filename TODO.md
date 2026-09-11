# TODO

Actions only. How things work and why they were built that way live in
[README.md](README.md) — don't restate it here. Delete an item when it is done;
an item that survives three rewrites is usually not an action, or is blocked on
something nobody has named.

## Next

- [ ] **Split the buttons.** Every button starts a scan, which was harmless
      while the scan was a mock and is not any more — Button A now moves real
      paper. The intended split is A scans and B runs a safe unmount before the
      drive is pulled: a change to `BUTTON_PINS` and `StatusScreen.on_button`,
      not a redesign.

## Secrets

- [ ] **Move the console passphrase into your password manager**, then
      `provisioning/console-password.txt` can go. It opens the Pi at an attached
      keyboard — the only way in if SSH ever stops working, and with the box
      deliberately ethernet-only it is the whole recovery story.

## Worth deciding, not yet urgent

- [ ] **Consider whether the scan drive should hold the scratch pages.** They
      currently land in a temporary directory on `/mnt/scans`, which keeps them
      off the RAM-backed `/tmp`. It also means an interrupted scan leaves a
      `.paperpi-scan-*` directory on the removable drive until the next reboot
      clears it. Harmless, and invisible to the index and to retention, which
      both match on `*.pdf` only -- but worth a sweep if it ever accumulates.

- [ ] **Serve on port 80 instead of 8080.** One change that improves three
      things at once: the address becomes `http://paperpi.local` with nothing to
      type after it; apps like WhatsApp are far more likely to turn it into a
      tappable link, since a bare `IP:port` often is not linkified at all; and
      the shorter URL drops the QR from 33 modules to 29, making it easier to
      scan. Needs `AmbientCapabilities=CAP_NET_BIND_SERVICE` in the unit so a
      non-root service can bind a privileged port. The cost is that the address
      everyone has learned changes once.

- [ ] **What a jam should leave behind.** A jam mid-batch currently discards
      every page already scanned, on the grounds that a truncated PDF which
      looks complete is worse than none. The opposite case is real too: losing
      forty good pages because sheet forty-one double-fed is its own kind of
      bad. Assembling the partial and saying so on the Done screen would need a
      partial-success path the `ScanEvent` union does not currently express.
      Leave it until it actually annoys someone.
- [ ] **Retry once on a busy scanner.** SANE reports `Device busy` when the
      scanner is waking from power-save, and the frontend treats it as fatal
      rather than retrying. One retry after a couple of seconds would absorb it.
      Not seen in practice yet, so not built.

## Carried from the code review

Structural rather than behavioural — none of these change what the box does.

- [ ] Name the remaining single-operation ports in
      [`paperpi/ports.py`](paperpi/ports.py) — `Clock`, `LinkFor`, `Home`,
      `Sleep`. They are declared inline at four call sites, so the contract is
      currently edited in four files.
- [ ] Replace `argparse.Namespace` and the unnamed 3-tuple from `_devices` in
      [`paperpi/__main__.py`](paperpi/__main__.py) with `Settings` and `Devices`
      dataclasses. The Namespace's attributes are `Any`, which is why one field
      needs a hand-written annotation to restore type safety.
- [ ] Decide what [`paperpi/protocols.py`](paperpi/protocols.py) does about
      `Canvas`. It imports the concrete Pillow class, so the Screen contract is
      bound to one rendering implementation. Either make the drawing surface a
      Protocol or document the coupling — but pick one.
- [ ] Move private constants below the public API in the ~10 modules that put
      them above (`app.py`, `serve.py`, the four screens, `render/canvas.py`,
      `adapters/hat.py`, `adapters/preview.py`). Some are forced — a
      default-argument value must precede its `def` — but most are body-only.
      `models.py`, `scans.py`, `adapters/status_linux.py`,
      `adapters/printer_cups.py` and `adapters/scan_sane.py` do it right.
- [ ] Make [`paperpi/__init__.py`](paperpi/__init__.py) and
      [`paperpi/render/__init__.py`](paperpi/render/__init__.py) honest. The
      first re-exports nothing while declaring `__all__`; the second re-exports
      a subset nothing imports. Either make them the front door or delete the
      re-exports. (`adapters/__init__.py` is now correct.)
- [ ] Drop `max_frames` from `app.run`. It duplicates what `running` already
      does, and is documented as test-only —
      `test_loop_should_stop_when_running_returns_false` shows `running`
      suffices.
- [ ] Inject the monotonic clock used for frame pacing in `app.run`. Everything
      else is injected; this one call to `time.monotonic()` is the only timing
      logic no test can drive.
- [ ] Give [`tests/test_qr.py`](tests/test_qr.py) an independent oracle. It
      re-encodes with the same library and parameters the implementation uses,
      so it proves the rendering and not the encoding. Decoding the rendered
      image and asserting the URL comes back would close it (`zbar-tools` is
      packaged but not installed). The row-overlap test in
      [`tests/test_canvas.py`](tests/test_canvas.py) now does the equivalent by
      comparing rendered pixels, so the technique is proven here.

## Ops

- [ ] Add `spidev.bufsiz=65536` to `/boot/firmware/cmdline.txt` and reboot. The
      default 4096 chunks each 153,600-byte frame into 38 writes; this cuts it
      to three. Not urgent — the loop no longer pushes unchanged frames — but
      free.
- [ ] Revisit the escpr queue at the CUPS 3.x transition. `lpadmin` already
      warns that printer drivers are deprecated; trixie's 2.4.10 is fine, and
      the replacement is likely a Printer Application rather than a PPD. Not
      actionable until a CUPS 3 lands in Debian, so this is a note to future
      you rather than a task.
