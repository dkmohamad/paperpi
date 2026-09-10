# TODO

Actions only. How things work and why they were built that way live in
[README.md](README.md) — don't restate it here. Delete an item when it is done;
an item that survives three rewrites is usually not an action, or is blocked on
something nobody has named.

## Waiting on you

- [ ] **Buy the scanner.** Blocked until a suitable used fi-6130 / fi-6130Z
      appears — the seller checklist and parts list are on the tracking task,
      not duplicated here. Nothing else in this list depends on it except the
      SANE work below.

## Secrets

- [ ] **Move the console passphrase into your password manager**, then
      `provisioning/console-password.txt` can go. It opens the Pi at an attached
      keyboard — the only way in if SSH ever stops working, and with the box
      deliberately ethernet-only it is the whole recovery story. It is `0600` and gitignored, but
      this is a public repo, a gitignored file is one `git add -f` away from
      being in it, and it is backed up nowhere.

## Replacing the mock

- [ ] **Write the SANE adapter** implementing `StartScan` / `ScanHandle` in
      [`paperpi/ports.py`](paperpi/ports.py), alongside
      [`adapters/scan_fake.py`](paperpi/adapters/scan_fake.py) rather than
      replacing it — the fake stays useful for development and tests. It shells
      `scanimage --batch` and turns its `Scanning page N` output into
      `PageScanned` events. Do this only once the scanner is in hand.
- [ ] **Settle the trigger.** Run `scanimage -A` when the scanner arrives: if
      its front-panel button exposes a usable SANE option, `scanbd` becomes the
      trigger and the HAT's Button A is the fallback. This decision gates the
      button mapping below, so make it first.
- [ ] **Split the buttons.** Every button currently starts a scan, which is
      right while there is nothing else to do. The intended split is A scans and
      B runs a safe-unmount before the drive is pulled — a change to
      `BUTTON_PINS` and `StatusScreen.on_button`, not a redesign.

## Worth trying

- [ ] **Use the Epson's flatbed as an interim scanner.** Its network advert
      carries `Scan=T`, meaning it exposes eSCL, so `sane-airscan` would reach
      it over the LAN with no USB and no vendor driver. It is a flatbed, so it
      cannot do the duplex ADF job this box exists for — but it would let the
      scan path be built and tested against real hardware before the fi-6130
      arrives, instead of against the mock.

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
      `models.py`, `adapters/status_linux.py` and `adapters/printer_cups.py`
      are the ones that do it right.
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
