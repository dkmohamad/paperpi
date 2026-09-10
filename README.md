# paperpi

Status display and scan control for the headless Raspberry Pi that serves the
home scanner and printer. Runs on a Pi 4 with a Pimoroni Display HAT Mini.

The card build that produced the Pi is in [`provisioning/`](provisioning/).
What is still outstanding is in [`TODO.md`](TODO.md).

## Background

**What it does.** At rest it shows peripheral readiness and how to reach the
box. Press any button and it runs a scan, reporting progress live. When the
scan finishes it shows a QR code that opens the document on your phone.

**The scan is currently mocked**, because the scanner has not arrived.
Everything downstream of it is real: the mock writes a genuine multi-page PDF,
the HTTP server serves it, and the QR resolves. Swapping in the SANE adapter
later changes one module and nothing else.

**Rendering is not a framebuffer.** There is no `/dev/fb*` on the Pi. The panel
is an ST7789 on SPI, and a frame is 320×240×2 bytes pushed down `/dev/spidev0.1`.
So drawing decomposes into producing an image and pushing it somewhere — which
is why the same screens render to a desktop window unchanged.

**The printer is not natively discoverable, despite being on the wifi.** Asked
directly over IPP it reports no `urf-supported` attribute at all, and iOS keys
AirPrint discovery on exactly that. So it could never appear on an iPhone or
iPad however it was paired. Android's Mopria uses PWG Raster, which the printer
does support, which is why this presented as an iOS-only problem. CUPS
synthesises the missing attribute for any queue it drives — so the queue on the
Pi advertises what the printer itself cannot.

**Progress is a count, not a percentage.** A sheet feeder does not know how many
pages it holds until the hopper empties, so "page 7, back side" is what we can
honestly say. A completion bar would be invented.

**Pimoroni's `displayhatmini` library is deliberately not used.** It has had no
release since February 2022 and drives buttons and LED through `RPi.GPIO`, whose
edge detection raises on kernels from Bookworm onward; this Pi runs trixie. Its
`__del__` also calls a global `GPIO.cleanup()`, resetting every GPIO the process
touched, at garbage-collection time. The panel is driven through `st7789` and the
buttons through `gpiozero`, giving one GPIO stack instead of two. The wiring
constants it would have supplied are in `config.py`.

## Setup

**Develop on a desktop.** No Pi and no HAT needed:

```sh
uv sync
uv run paperpi --preview          # a/b/x/y are the four buttons
uv run paperpi --screenshot shots # one PNG per screen, then exit
```

The preview magnifies by 2 so it is visible on a monitor. It is a stand-in, not
a simulation — check legibility on the real glass before calling a layout done.

**After cloning**, wire the commit hook once:

```sh
git config core.hooksPath hooks
```

`hooks/commit-msg` enforces a 50-character header, 72-character body lines, and
no AI-tool attribution. It is tracked, but `core.hooksPath` is local config and
cannot be, so a fresh clone has to opt in. Plain shell rather than husky, so a
Python project does not carry npm to host one hook.

**Checks:**

```sh
uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest
```

**Deploy to the Pi.** One-off, on the Pi: install `uv`, and the build tooling
the compiled dependencies need. Neither `lgpio` nor `pycups` has an aarch64
wheel, so both build from source — without these `uv sync` fails with
`command 'swig' failed`, then `cannot find -llgpio`, then a missing `cups.h`.

```sh
ssh admin@paperpi.local 'curl -LsSf https://astral.sh/uv/install.sh | sh'
ssh admin@paperpi.local 'sudo apt-get update &&
  sudo apt-get install -y swig python3-dev liblgpio-dev libcups2-dev'
```

Then each deploy:

```sh
rsync -a --delete --exclude .venv --exclude provisioning \
  ~/dev/paperpi/ admin@paperpi.local:~/paperpi/
ssh admin@paperpi.local 'cd paperpi && uv sync --extra hat --extra cups --no-dev'
ssh admin@paperpi.local 'sudo install -m 644 ~/paperpi/systemd/*.service \
  ~/paperpi/systemd/*.timer /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable --now paperpi paperpi-retention.timer'
```

All the units, not just `paperpi.service` — the retention timer is one of them,
and installing only the service is how a box ends up quietly never tidying up.

The `hat` and `cups` extras carry the Pi-only dependencies, which is why
`uv sync` on a desktop does not try to build them. They are separate because
the panel and the print server are separate concerns: a box could reasonably
have one and not the other.

Optional: add `spidev.bufsiz=65536` to `/boot/firmware/cmdline.txt` and reboot.
The default is 4096, so each 153,600-byte frame is chunked into 38 writes; this
cuts it to three.

### Storage and the scan share

Scans are written to `/mnt/scans`, an exFAT USB drive matched by label:

```
LABEL=share  /mnt/scans  exfat
  defaults,nofail,uid=1000,gid=1000,umask=0022,x-systemd.device-timeout=10  0  0
```

Matched on the label rather than the UUID, and `99-paperpi-scans-mount.rules`
matches the same way. A UUID is unique but disposable: reformat the drive or
swap in a replacement and both the fstab entry and the rule silently stop
matching, with no error anywhere. The label is ours to set, so "the drive
labelled `share`" is the contract and a replacement prepared the same way works.

A plain fstab entry only mounts once, at boot. If the drive drops off the bus --
a nudged connector, a bus reset when something else is plugged into the same hub
-- systemd unmounts it and never brings it back, so scans would quietly start
landing on the SD card. The udev rule starts the mount unit whenever a matching
device appears, which closes that.

`x-systemd.automount` would also recover, and is deliberately not used: with no
drive attached it leaves an autofs mount in place, so writes fail outright
rather than falling back to the SD card, and `is_mount()` reports storage that
is not there. Degraded and honest beats broken.

`nofail` is not optional on a headless box: without it, a drive that is missing
or failing drops the boot into an emergency shell nobody can reach. The device
timeout stops systemd waiting 90 seconds for a drive that is not there.

exFAT rather than ext4 so the drive is readable if it is pulled and plugged into
anything else, and rather than FAT32 so a large scan is not capped at 4 GB.

The path lives in the systemd unit, not in `config.py` — where the app writes is
a deployment choice, and the code default stays sensible for a development
machine with no `/mnt/scans`. The unit deliberately does not set
`RequiresMountsFor`: with the drive unplugged the display should still come up
and report storage as absent, which is more use than a service that refuses to
start. Mount propagation into the service namespace is `slave`, so replugging
the drive is picked up without restarting anything.

### Reading the scans

**`http://paperpi.local:8080/`** — a list of every scan, newest first, on any
phone or laptop browser. The QR on the Done screen links straight to the
document that was just produced.

There is no SMB share. There was one, briefly, and it was removed: setting up an
SMB client is friction nobody at home will accept, Android has no SMB in its
stock file manager, and no browser can open `smb://` at all. It solved a problem
for one technical user and none for the household. For administrative access
`sshfs admin@paperpi.local:/mnt/scans` gives a real mounted folder using a
credential that already exists.

The index is **open — no password**, and that is a deliberate trade: anyone on
the LAN can list and read the scans. A login prompt on a phone is exactly the
friction that stopped the share being used. Adding basic auth is a small change
if that stops being the right call.

The page is entirely self-contained — inline CSS, no JavaScript, no webfont, no
CDN. The person opening it is usually standing beside the scanner on the house
wifi, which is precisely where a phone may have no route to the internet.

### Printing

**The printer appears as `paperpi`** on any phone, tablet or laptop on the LAN —
no app, no account, no pairing. CUPS drives the Epson over USB and advertises
the queue over DNS-SD, which is what AirPrint and Mopria both discover. Setup,
once:

```sh
sudo apt-get install -y --no-install-recommends \
    cups printer-driver-escpr cups-ipp-utils avahi-utils libpaper-utils
sudo paperconfig -p a4
sudo systemctl enable --now cups.service

# Read both URIs off the machine rather than typing them.
device=$(sudo lpinfo -v | awk '/usb:\/\/EPSON/ {print $2}')
driver=$(sudo lpinfo -m | awk '/Epson-ET-2810_Series/ {print $1}')
sudo lpadmin -p paperpi -D paperpi -L home -v "$device" -m "$driver" \
    -o printer-is-shared=true -E
sudo lpadmin -d paperpi
sudo cupsctl --share-printers
sudo systemctl restart cups
```

Six things here are not obvious, and five of them cost an afternoon each if got
wrong:

- **`--no-install-recommends` is about correctness, not disk space.** The
  recommends include `cups-browsed`, which discovers *remote* queues and creates
  local ones — the opposite of what is wanted, and a known source of phantom
  duplicates — and the whole SANE stack, which should not arrive as a side
  effect of installing a printer.
- **`paperconfig -p a4` is not optional.** There is no `/etc/papersize` on a
  fresh image, and CUPS derives `media-ready` from libpaper. iOS reads
  `media-ready` to choose paper, so if it resolves to Letter then A4 jobs print
  scaled or clipped, and it looks like a driver fault.
- **`cups.service` must be enabled, not merely `cups.socket`.** The socket unit
  listens only on the UNIX socket, and cupsd idle-exits after 60 s when nothing
  is shared — so nothing would be left to wake it over the network.
- **`cupsctl --share-printers` is the whole of the sharing config.** It rewrites
  `Listen localhost:631` to `Port 631`, puts `Allow @LOCAL` in `<Location />`,
  and sets `Browsing On`, while leaving `<Location /admin>` alone — which is
  what keeps administration on localhost. Editing `cupsd.conf` by hand is both
  unnecessary and fragile in the other direction: `cupsctl` and the web UI
  rewrite that file, so a hand edit can be silently reverted.
- **The driver URI must be copied exactly.** Debian's `printer-driver-escpr`
  ships no `.ppd` files at all; they are generated on demand by a driver
  enumerator, so a stray character produces the thoroughly misleading
  `Missing PPD-Adobe-4.x header on line 0`. Hence reading it with `awk` above.
- **`usblp` is deliberately left loaded.** It holds the printer as
  `/dev/usb/lp0`, and CUPS's libusb backend detaches and re-attaches it around
  each job. Blacklisting it is pre-libusb advice that would only break other
  tooling.

Verify the advert rather than trusting it — this is the part that decides
whether an iPhone will offer the printer at all:

```sh
ipptool -tv ipp://localhost/printers/paperpi \
    /usr/share/cups/ipptool/get-printer-attributes.test | grep -i urf-supported
avahi-browse -rt _ipp._tcp
```

`URF=` must be non-empty, `pdl=` must contain both `application/pdf` and
`image/urf`, and `media-ready` must contain A4.

Administration is localhost-only by design, so reach the web UI over a tunnel:

```sh
ssh -L 6310:localhost:631 admin@paperpi.local   # then http://localhost:6310/
```

`lpadmin` warns that printer drivers are deprecated and will stop working in a
future CUPS. That is a CUPS 3.x change rather than a trixie one, and it will
need revisiting then, most likely as a Printer Application instead of a PPD.

### If a device cannot see the box

Check which wifi it is on first. The house has two routers on separate subnets,
and only one of them is the network the Pi is wired to. A device joined to the
other cannot reach the Pi at all — not the scans page, not the QR link, not the
print queue.

The Pi itself deliberately holds **one** address, over ethernet. It briefly had
two, one per router, and that is worse than it sounds: a host on two subnets
advertises both over mDNS, so a phone can resolve `paperpi.local` and be handed
the address it cannot reach. Everything then works from some devices and not
others, intermittently, which is the most expensive kind of broken.

**There is deliberately no wifi fallback**, and it is worth saying why so it is
not helpfully added back. The Pi is wired to the router it sits beside, so a
fallback would have to join *that same router* — meaning it covers nothing the
cable does not already cover except the cable itself, the Pi's ethernet port, or
one LAN port failing. All three are physical faults on a stationary box in a
room you can walk into, and the recovery path for those is a keyboard on the
console, which needs no network at all.

Against that it would cost a stored Wi-Fi PSK on a machine that is trying to
hold fewer secrets, and it would put the second address back within one
misconfiguration of returning. A radio that cannot associate with anything is
the simpler machine.

### Retention

`paperpi-retention.timer` runs daily and removes scans older than 90 days,
`Persistent=true` so a box that was off overnight still tidies when it returns.

It works through `serve.scans_in`, which is the safety argument: that function
only returns `.pdf` files whose name carries a valid content-hash id, so
retention **cannot delete anything the application did not write**. A plain
`find /mnt/scans -mtime +90 -delete` would take whatever else happens to be on
the drive, which on removable media is a real prospect.

```sh
python -m paperpi.retention --scan-dir /mnt/scans --days 90 --dry-run
```

### What it costs

Measured on the Pi 4: a full status render is ~10 ms, an SPI push ~38 ms,
comparing two frames ~0.5 ms. So the loop does two things rather than redrawing
blindly — it skips the push when the frame is byte-identical, and it backs off
from 20 fps toward 150 ms between passes while nothing is changing. Together
those took the idle service from 49% of a core to about 11%. Both reset the
moment the frame changes, so a running scan still animates at full rate, and no
press is lost while idle because the button adapter queues them on gpiozero
callbacks rather than being polled.

## Architecture

Every collaborator outside the process is a port with a real implementation
and a development one, chosen in one place. The screens are pure — state in,
image out — so they are tested with no hardware at all.

```
   ButtonEvent                    SystemStatus / ScanEvent
        |                                    |
  +-----v------------------------------------v-----+
  |                    app.run()                    |
  |         holds one Screen, drives the loop        |
  +----------------------+--------------------------+
                         | render(canvas)
                +--------v---------+
                |  Screen variants |  status / scanning / done / error
                +--------+---------+
                         | Image
                  +------v-------+
                  | Display port |
                  +--+--------+--+
                     |        |
              HatDisplay    PreviewDevice
              (ST7789/SPI)  (window + keys)
```

| Module | Holds |
|---|---|
| `models.py` | The vocabulary: readiness, scan events, print queues, colours |
| `ports.py` | IO contracts — Display, Buttons, StartScan, StatusSource, PrintQueues |
| `protocols.py` | The Screen contract |
| `app.py` | The render loop |
| `screens/` | One module per view |
| `render/` | Canvas, fonts, QR — no hardware |
| `adapters/` | Real and stand-in implementations |
| `serve.py` | Read-only HTTP file server behind the QR |
| `retention.py` | The 90-day sweep, built on `serve.scans_in` |

The font ships inside the package rather than coming from the system, so the
desktop preview renders identically to the Pi — which has no fonts installed at
all.

## Next

The real SANE adapter, once the scanner arrives. It implements `StartScan` and
`ScanHandle` alongside the fake rather than replacing it, so the fake stays
useful for development and for tests. Everything downstream of it is already
real: the PDF, the HTTP server, the QR and retention.

Peripheral detection stays honest — it reports what is attached and, separately,
what can actually be driven, never treating one as evidence of the other. That
is why the printer row moved from `no queue` to `ready` the moment CUPS could
answer for it, without a line changing in any screen.
