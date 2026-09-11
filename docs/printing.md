# Printing

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


Back to the [README](../README.md).
