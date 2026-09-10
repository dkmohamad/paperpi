# paperpi — card build

Card build for the headless Raspberry Pi that serves the home scanner and
printer. This covers getting a clean, reachable Pi; the scan and print stacks
are installed over SSH afterwards, in the [top-level README](../README.md).

## Background

**The old card.** Raspberry Pi OS Lite 64-bit, image 2025-12-04, hostname
`raspberrypi`, with a personal user account. Its entire history of use was one `apt install
pulseaudio ... avahi-daemon` (an AudioRelay experiment) and a five-line shell
history — empty `/opt`, `/srv`, `/root`, no custom units, bare home directory.
Nothing worth preserving, so reflashing beat tidying, and it picks up an image
six months newer.

**What lands on the card.** Raspberry Pi OS Lite 64-bit 2026-06-18 (Debian 13
trixie, kernel 6.18); hostname `paperpi` on mDNS; user `admin` — a role account,
not a personal one — with passwordless sudo; ethernet preferred with Wi-Fi as an
optional fallback so it boots on either; `en_GB.UTF-8` / `Europe/London`; and
`dtparam=spi=on`, since the Display HAT Mini's screen is on SPI and finding that
out after the HAT is fitted costs a reboot.

**Access.** Two independent routes, so losing one does not mean reflashing. SSH
is key-only (`ssh_pwauth: false`, `id_ed25519` authorised) — which is also why
the predictable username `admin` is not a concern, as there is no password to
guess remotely. The console passphrase works only at an attached keyboard; it is
five words rather than random because it gets typed without a clipboard. The old
card's password was lost, so it was regenerated. The passphrase is in
`provisioning/console-password.txt` — move it to a password manager.

**Why `dd` runs unprivileged.** `dd` is dangerous mainly because it is normally
run under `sudo`, where one mistyped device name reaches any disk in the
machine. The udev rule here gives the `plugdev` group raw access to devices that
are both USB and kernel-flagged removable — which internal disks can never be —
so `dd` runs as you and a wrong target fails with a permission error rather than
destroying a system disk. It deliberately does not use the `disk` group, which
would grant raw access to every device including internal ones.

**The board.** Raspberry Pi 4 Model B Rev 1.5, confirmed on first boot — the
comfortable choice here, with four USB ports for scanner and printer and enough
RAM to assemble duplex 300 dpi PDFs. Running Debian 13 trixie, kernel
6.18.34+rpt-rpi-v8 aarch64, wired at 192.168.1.246.

**Open questions.** Whether the fi-6130's front-panel button exposes a usable
SANE option, and the exact Epson driver package.

## Setup

The image is already at
`~/Downloads/rpi/2026-06-18-raspios-trixie-arm64-lite.img.xz`
(sha256 `acff736c…`, verified). Re-fetch it and its `.sha256` from
`downloads.raspberrypi.com/raspios_lite_arm64/images/` if needed.

**1. Install the udev rule — the only step needing sudo.**

```sh
sudo install -m 0644 -o root -g root \
  ~/dev/paperpi/provisioning/99-usb-removable-raw.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=block --action=add
```

The action must be `add`, not `change`. udev applies node ownership when it
creates the node; on a `change` event it recomputes the rules and then preserves
the existing permissions, so the rule appears to do nothing.

Confirm it took effect before going further — the rule can install cleanly and
still not apply:

```sh
ls -l /dev/sd?           # the reader's device should show group `plugdev`
```

Unplugging and replugging the reader does the same job with no sudo, and is the
surer option since it generates a genuine `add` event. Either way the card
auto-mounts again afterwards, so unmount it before writing.

The rule grants to `plugdev` rather than using `TAG+="uaccess"`. uaccess looks
tidier and does not work here: systemd applies it at priority 70, before any
`99-` file can set the tag, and only for seat-assigned devices, which block
devices are not. It fails silently, which is why step 1 verifies.

**2. Identify the card, and confirm it is the right one.** Use the `by-id` path
throughout: `/dev/sdX` letters are reassigned between plug-ins.

```sh
lsblk -o NAME,SIZE,TRAN,RM,HOTPLUG,LABEL,MOUNTPOINT
ls -l /dev/disk/by-id/usb-*

DEV=/dev/disk/by-id/usb-NORELSYS_1081CS0_0123456789ABCDE-0:0
lsblk -dno NAME,SIZE,TRAN,HOTPLUG "$DEV"      # expect: sdb 59.5G usb 1
cat /sys/block/"$(lsblk -dno NAME "$DEV")"/removable   # expect: 1
test -w "$DEV" && echo "writable unprivileged - rule is active"
```

If it is not writable, replug the reader. Do not reach for `sudo` — that
reintroduces exactly the risk the rule removes.

**3. Unmount, then write.**

```sh
udisksctl unmount -b "$DEV-part1"
udisksctl unmount -b "$DEV-part2"

xz -dc ~/Downloads/rpi/2026-06-18-raspios-trixie-arm64-lite.img.xz \
  | dd of="$DEV" bs=4M iflag=fullblock conv=fsync oflag=direct status=progress
sync
```

`iflag=fullblock` matters because the input is a pipe: without it `dd` accepts
short reads and writes undersized blocks, warning `partial read ... suggest
iflag=fullblock`. No data is lost or reordered, so a write that omits it is
still correct — but it is slower, and were the image not block-aligned the
final undersized write could fail against `oflag=direct`. This image is
4096-aligned, so both are safe; the flag makes that not depend on luck.

**4. Verify what actually landed** — this is what catches a wrong target or a
dying card.

```sh
dd if="$DEV" bs=4M count=64 iflag=fullblock status=none | sha256sum
```

Expect the first 256 MB of the image:

```
215b3bc18fbde64b3718c55198a11d7a91e420b4010d38538c5818bdc34a21dc
```

If you get `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
that is the hash of *nothing* — the read returned no bytes, so it is a
permissions problem (step 1), not a bad write.

**5. Provision.** udisks mounts removable media with `uid=1000`, so these files
are yours to write without elevation.

```sh
udevadm settle
udisksctl mount -b "$DEV-part1"
B=$(findmnt -no TARGET "$DEV-part1")

cp ~/dev/paperpi/provisioning/boot/{user-data,network-config,meta-data,ssh} "$B/"
printf '\n# Display HAT Mini (1.3" IPS) talks over SPI\ndtparam=spi=on\n' \
  >> "$B/config.txt"

grep -E '^(hostname|ssh_pwauth):' "$B/user-data"   # paperpi, false
grep '^dtparam=spi=on' "$B/config.txt"
test -e "$B/ssh" && echo "ssh flag present"
sync && udisksctl unmount -b "$DEV-part1"
```

The empty `ssh` file is not optional. Raspberry Pi OS ships with SSH disabled
and enables it only when `sshswitch.service` finds `/boot/ssh` or
`/boot/firmware/ssh` on boot — that flag is what Imager's "Enable SSH" tickbox
creates. Without it cloud-init still creates the user, sets the hostname and
installs the authorised key, and the Pi boots and answers mDNS and ping, but no
sshd ever starts. With `ssh_pwauth: false` that leaves console-only access, and
the symptom is a healthy host refusing on port 22.

**6. Boot.** Fit the card, power on, allow ~2 minutes for cloud-init and its one
reboot, then `ssh admin@paperpi.local`.

To change the hostname or user, edit `boot/user-data` before step 5 — and keep
`boot/meta-data`'s `local-hostname` in step with it.

## Next

This document ends at a clean, reachable Pi. Everything installed over SSH
afterwards — the display service, the scan drive, the web index, retention and
the print queue — is in the [top-level README](../README.md), which is the one
to follow for a rebuild.

Still outstanding there is the scanner: `sane-utils`, `scanimage -L` to confirm
detection, and `scanimage -A` to learn whether the scanner's own button is
usable, which decides whether it or the HAT's Button A becomes the trigger.

None of it runs at first boot, deliberately — a failed package install is close
to invisible on a headless box, so a Pi that does not come up has a short list
of causes.

## Files

| Path | What it is |
|---|---|
| `99-usb-removable-raw.rules` | The udev policy, commented |
| `boot/user-data` | cloud-init: hostname, user, key, locale. `0600`. |
| `boot/network-config` | netplan: eth0 + wlan0, both optional. `0600`. |
| `boot/meta-data` | instance-id and local-hostname |
| `boot/ssh` | Empty flag; without it Raspberry Pi OS leaves SSH off |
| `99-paperpi-scans-mount.rules` | Remounts the scan drive when it reappears |
| `provisioning/console-password.txt` | The console passphrase in clear. `0600`. |

`console-password.txt` and `boot/user-data` / `boot/network-config` hold a
passphrase, a password hash and a Wi-Fi PSK in clear. **This directory is
tracked, in a public repo**, so those three are named in `.gitignore` and are
the reason it exists. `git add -f` defeats that, so check before forcing
anything here. The passphrase should not live in a file at all; moving it to a
password manager is tracked in [TODO.md](../TODO.md).
