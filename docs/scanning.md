# Scanning

Load the feeder, press **Button A**, and a duplex PDF lands in `/mnt/scans` with
a QR on the panel that opens it. One profile, no settings:

```
300 dpi  ·  ADF duplex  ·  lineart  ·  A4  ·  every side kept
```

## Loading the feeder

Hold the document as you would to read it, **flip the whole stack over like
closing a book** — not end over end — and put it in the rear chute with the top
of the page going in first. The operator's guide, section 2.2, step 3:

> Set the documents face-down in the ADF paper chute (so that the side to be
> scanned faces towards the ADF paper chute).

Face-down is not a detail. Get it wrong and every sheet's blank reverse arrives
before its front, because the first sensor reads whichever side faces down. And
the book flip matters as much as the flip itself: turning the stack end over end
also gets you face-down, but with the bottom of the page leading, and the scan
comes out inverted.

**Page order needs no correction, and that is worth stating so nobody adds one.**
The feeder takes from the *bottom* of the stack. Loading face-down means turning
the document over, which puts page one at the bottom — exactly where the feeder
starts. The two cancel out. Software that reverses the pages looks right for a
stack loaded face-up and is wrong for anyone following the manual; this code did
that briefly and it was a mistake.

**Orientation does need one.** The scanner hands every page back upside down, so
`SCAN_ROTATION_DEGREES` turns each one before it enters the PDF. Measured, not
assumed: a sheet with `TOP` written across it came back with the writing in the
bottom fifth of the image, loaded exactly as above.

If a different scanner ever replaces this one, re-measure rather than inherit
these: write `TOP` on one sheet, number a second, scan them loaded per that
machine's own manual, and see where the ink lands.

Setup, once:

```sh
sudo apt-get install -y --no-install-recommends sane-utils
sudo usermod -aG scanner admin
sudo udevadm trigger --action=add --subsystem-match=usb
sudo install -D -m 644 provisioning/sane/dll.conf /etc/paperpi/sane/dll.conf
sudo systemctl restart paperpi          # to pick up the new group
scanimage -L                            # expect the scanner, and only it
```

Each choice above is load-bearing, and most of them fail quietly rather than
loudly:

- **Access is an ACL, not a group.** `libsane1` ships a udev rule that runs
  `setfacl -m g:scanner:rw` on the device node; the node itself stays
  `root:root`. Look for the `+` in `crw-rw-r--+`, not for a changed group.
- **`--action=add`, not `change`.** The scanner was already plugged in when the
  rules were installed, so its node has to be re-added before they apply to it.
  A `change` event is not reliably enough, and it fails silently.
- **A fresh login is needed**, which is why the service is restarted. Group
  membership is granted at exec, so a running service never picks it up.
  `SupplementaryGroups=scanner` in the unit says the same thing where someone
  rebuilding the box will see it.
- **A4 is set explicitly.** The backend's own default page size is US Letter,
  which is 17.6 mm shorter than A4 — left alone it cuts the bottom off every
  page, and the result looks like a scan rather than a bug.
- **`dll.conf` lists one backend.** Debian enables 77 and loads every one to
  enumerate devices. Measured here: **8.7 s** to list devices with the default,
  **0.03 s** with just this one. It also returned four devices instead of one,
  because the printer's flatbed answers SANE too — so an unpinned scan could
  have run on the wrong machine.
- **Blank backs are kept.** Duplexing a one-sided stack gives a PDF that is half
  blank pages, which is ugly and deliberate. The backend's `--swskip` would drop
  them, but it does so *inside* `sane_start`, invisibly to the caller — which
  both desynchronises the front/back labelling the panel shows, and can discard
  a page carrying nothing but a faint pencil note, silently. A record you cannot
  trust to be complete is worth less than a tidy one.
- **The scanner's own buttons are not used.** They exist — `scanimage -A` lists
  `Scan button` and `Send to` — and driving them means `scanbd`, which holds the
  device open to poll them and so contends with scanning itself. It also brings
  an inetd listener, a D-Bus service and a mandatory loopback hop for every
  scan. Button A is two feet away and already debounced.

If a replacement scanner ever arrives, `scanimage -A -d <device>` is the
authority on what to put in `config.py` — the option spellings there were read
off this unit, not out of a manual.


## The lamp, and why the panel does not keep asking

The scanner drops into power save after fifteen minutes idle. What brings it
back, per the operator's guide, is loading paper, pressing a button on it — or
"a command from the scanner driver".

**The scanning lamp does not go out**, which is worth knowing before someone
reports it as a fault. Power save is visible on the operator panel instead: the
Function Number Display — the single green digit on the right-hand side — goes
dark, while the green power LED stays lit. Both of those are documented; the
lamp is not mentioned anywhere in the guide. Verified on this unit: the display
was out, and pressing Function lit it again.

Fujitsu never wrote down what the lamp does, but the numbers say it cannot be at
full brightness — 38 W operating against under 6.2 W asleep, with two cold
cathode tubes to account for — and the SANE backend's maintainer describes this
family's sleep as "lamp at half brightness". So a lit lamp on an idle scanner is
this machine working correctly.

That last one includes listing SANE devices, which is exactly what the status
row does to learn whether the scanner is driveable. So the probe asks **once**
when the scanner appears and then stops. When it cannot find one it retries, but
on a doubling backoff that climbs past the fifteen-minute power-save window, so
a scanner we cannot reach recovers quickly from a start-up race and is otherwise
left alone.

This is a hardware concern, not a performance one. The lamp is a cold-cathode
tube — the manual's safety section warns it contains mercury — and it has a
finite life. It is not in the consumables table, which lists only the pick and
brake rollers (200,000 sheets or one year, with counters on the scanner). So
there is no way to read how much lamp life is left and no user-serviceable way
to replace it. A probe loop that held it lit would be wearing out a part nobody
can measure or fix.

## If SANE stops seeing the scanner

Power it off and on — hold the power button for two seconds, then press it
again. The panel notices within a couple of seconds and returns to READY on its
own; nothing needs restarting. A USB-level reset is not enough: unbinding and rebinding the device, or
toggling its `authorized` flag, leaves it enumerated on the bus but in a state
libusb cannot open, and `scanimage -L` then finds nothing even as root. Only a
real power cycle re-initialises it.

Back to the [README](../README.md).
