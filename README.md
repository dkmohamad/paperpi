# paperpi

Status display and scan control for the headless Raspberry Pi that serves the
home scanner and printer. Runs on a Pi 4 with a Pimoroni Display HAT Mini.

The card build that produced the Pi is in [`provisioning/`](provisioning/).

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
`lgpio` needs. There is no aarch64 wheel for it, so it compiles from source and
wants swig plus the shared library — without these `uv sync` fails with
`command 'swig' failed` and then `cannot find -llgpio`.

```sh
ssh admin@paperpi.local 'curl -LsSf https://astral.sh/uv/install.sh | sh'
ssh admin@paperpi.local 'sudo apt-get update &&
  sudo apt-get install -y swig python3-dev liblgpio-dev'
```

Then each deploy:

```sh
rsync -a --delete --exclude .venv --exclude provisioning \
  ~/dev/paperpi/ admin@paperpi.local:~/paperpi/
ssh admin@paperpi.local 'cd paperpi && uv sync --extra hat --no-dev'
ssh admin@paperpi.local 'sudo install -m 644 \
  ~/paperpi/systemd/paperpi.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload && sudo systemctl enable --now paperpi'
```

The `hat` extra carries the Pi-only dependencies, which is why `uv sync` on a
desktop does not try to build them.

Optional: add `spidev.bufsiz=65536` to `/boot/firmware/cmdline.txt` and reboot.
The default is 4096, so each 153,600-byte frame is chunked into 38 writes; this
cuts it to three.

### Storage and the scan share

Scans are written to `/mnt/scans`, an exFAT USB drive mounted by UUID:

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

Three ports, each with a real implementation and a development one. The screens
are pure — state in, image out — so they are tested with no hardware at all.

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
| `models.py` | The vocabulary: readiness, scan events, colours |
| `ports.py` | IO contracts — Display, Buttons, StartScan, StatusSource |
| `protocols.py` | The Screen contract |
| `app.py` | The render loop |
| `screens/` | One module per view |
| `render/` | Canvas, fonts, QR — no hardware |
| `adapters/` | Real and stand-in implementations |
| `serve.py` | Read-only HTTP file server behind the QR |

The font ships inside the package rather than coming from the system, so the
desktop preview renders identically to the Pi — which has no fonts installed at
all.

## Next

Per the Notion build: the real SANE adapter once the fi-6130 arrives, CUPS with
AirPrint for the Epson, the Samba share on the pen drive, and 90-day retention.
Each plugs into the ports already here. Peripheral detection is honest today —
it reports what is attached, not what is driveable — so as each layer lands the
display lights up without changes to the screens.
