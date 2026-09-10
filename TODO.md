# TODO

Actions only. How things work and why they were built that way live in
[README.md](README.md) — don't restate it here. Delete an item when it is done;
an item that survives three rewrites is usually not an action, or is blocked on
something nobody has named.

## Hardware not yet attached

- [ ] **Plug in the Epson and set up printing.** `apt install cups avahi-daemon`
      plus the driver (`printer-driver-escpr` is the likely one — confirm against
      the actual model), add the queue, tick *Share this printer*; AirPrint
      discovery then follows from `cups-browsed`. The PRINTER row already detects
      a USB printer structurally by interface class, so it moves from `no device`
      to `no queue` the moment it is plugged in. Once a queue exists, replace the
      inference in `paperpi/adapters/status_linux.py::_printer` with a real queue
      check so the row can reach READY.
- [ ] **Buy the scanner.** Blocked until a suitable used fi-6130 / fi-6130Z
      appears — the seller checklist and the parts list are on the tracking task,
      not duplicated here. Nothing else in this list depends on it except the
      SANE work below.

## Watch

- [ ] `wlan0` is now enabled but repeatedly disconnecting in the journal
      (`CTRL-EVENT-DISCONNECTED reason=7`). The box is on ethernet so nothing is
      broken, but the wifi fallback is not proven to work — worth confirming
      the credentials are still current before relying on it.

## Secrets

- [ ] **Move the console passphrase into your password manager**, then the file
      can go. `provisioning/console-password.txt` opens the Pi at an attached
      keyboard — the only way in if SSH ever stops working. It is `0600` and
      gitignored, but a gitignored file is one `git add -f` from a public repo
      and is not backed up anywhere.

## Replacing the mock

- [ ] **Write the SANE adapter** implementing `StartScan` / `ScanHandle` in
      `paperpi/ports.py`, alongside `adapters/scan_fake.py` rather than replacing
      it — the fake stays useful for development and tests. It shells
      `scanimage --batch` and turns its `Scanning page N` output into
      `PageScanned` events. Do this only once the scanner is in hand.
- [ ] **Settle the trigger.** Run `scanimage -A` when the scanner arrives: if its
      front-panel button exposes a usable SANE option, `scanbd` becomes the
      trigger and the HAT's Button A is the fallback. This decision gates the
      button mapping below, so make it before building either.
- [ ] **Split the buttons.** Every button currently starts a scan, which is right
      while there is nothing else to do. The intended split is A scans and B runs
      a safe-unmount before the drive is pulled — a change to `BUTTON_PINS` and
      `StatusScreen.on_button`, not a redesign.

## Carried from the code review

Structural rather than behavioural — none of these change what the box does.

- [ ] Name the remaining single-operation ports in `paperpi/ports.py` — `Clock`,
      `LinkFor`, `Home`, `Sleep`. They are declared inline at four call sites, so
      the contract is currently edited in four files.
- [ ] Replace `argparse.Namespace` and the unnamed 3-tuple from `_devices` in
      `paperpi/__main__.py` with `Settings` and `Devices` dataclasses. The
      Namespace's attributes are `Any`, which is why one field needs a
      hand-written annotation to restore type safety.
- [ ] Decide what `paperpi/protocols.py` does about `Canvas`. It imports the
      concrete Pillow class, so the Screen contract is bound to one rendering
      implementation. Either make the drawing surface a Protocol or document the
      coupling — but pick one.
- [ ] Move private constants below the public API in the ~10 modules that put
      them above (`app.py`, `serve.py`, the four screens, `render/canvas.py`, the
      three adapters). Some are forced — a default-argument value must precede
      its `def` — but most are body-only. `models.py` is the module that does it
      right.
- [ ] Make `paperpi/__init__.py` and `render/__init__.py` honest. The first
      re-exports nothing while declaring `__all__`; the second re-exports a
      subset nothing imports. Either make them the front door or delete the
      re-exports.
- [ ] Drop `max_frames` from `app.run`. It duplicates what `running` already
      does, and is documented as test-only —
      `test_loop_should_stop_when_running_returns_false` shows `running` suffices.
- [ ] Inject the monotonic clock used for frame pacing in `app.run`. Everything
      else is injected; this one call to `time.monotonic()` is the only timing
      logic no test can drive.
- [ ] Give `tests/test_qr.py` an independent oracle. It re-encodes with the same
      library and parameters the implementation uses, so it proves the rendering
      and not the encoding. Decoding the rendered image and asserting the URL
      comes back would close it (`zbar-tools` is packaged but not installed).

## Ops

- [ ] Add `spidev.bufsiz=65536` to `/boot/firmware/cmdline.txt` and reboot. The
      default 4096 chunks each 153,600-byte frame into 38 writes; this cuts it to
      three. Not urgent — the loop no longer pushes unchanged frames — but free.
- [ ] Consider whether the web index should stay open. It has no password today,
      which is what makes it usable from a phone without friction, and the trade
      is that anyone on the LAN can read every scan. Revisit if the box ever
      holds anything you would not leave on the kitchen table.
