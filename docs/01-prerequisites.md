# 01 — Prerequisites

## Hardware you need

- **A USB-to-TTL serial adapter that does 3.3 V logic** (FTDI FT232, CP2102, CH340, etc.). Many have a
  **5 V / 3.3 V switch — keep it on 3.3 V.** 5 V can destroy the SoC's UART.
- **4 female–female Dupont jumper wires** (2.54 mm).
- **A USB stick ≥ 2 GB** you can dedicate to the NAS OS (USB 2.0 is fine). A **second identical stick** as
  a cold spare is strongly recommended — it becomes your "OS mirror".
- **A Linux workstation** (or another Debian/Ubuntu box, a Raspberry Pi, even the target NAS's future host)
  to build the USB stick and run the serial console.
- **External storage** big enough for your irreplaceable data backup (see [02](02-backup-and-nand-dump.md)).

## Software on the build box

```bash
sudo apt-get update
sudo apt-get install -y u-boot-tools screen mdadm btrfs-progs rsync
# u-boot-tools -> mkimage (build the uImage); screen -> serial console
```

## Downloads (bodhi's mvebu Debian kernel + rootfs)

You need three things; all come from **bodhi's Doozan releases**:

1. **A Debian `mvebu` rootfs** — `Debian-<ver>-mvebu-tld-1-rootfs-bodhi.tar.bz2`.
   It ships a matching kernel + modules + **all** the ReadyNAS DTBs, so it can boot self-contained.
2. **(optional) A newer `mvebu` kernel** — `linux-<ver>-mvebu-tld-1-bodhi.tar.bz2` — for upgrading *after*
   first boot. Its `linux-dtb-*.tar` also contains every model's DTB under `dts/`.
3. **Your model's DTB** — either from the rootfs (`/boot/dts/<your-model>.dtb`) or the kernel's
   `linux-dtb-*.tar`. Confirm the file name from [../models/compatibility.md](../models/compatibility.md).

> Find the current release links in the Doozan forum thread **"Linux Kernel MVEBU package and Debian armhf
> rootfs"** (bodhi). Dropbox links rotate over the years — grab the latest. Verify each download is a real
> `bzip2` archive: `file <file>.tar.bz2` should say *"bzip2 compressed data"* (not *HTML*).

## A note on strategy (read before downloading a kernel)

The rootfs is **named after the kernel bundled inside it** (e.g. `Debian-6.6.2-...` ships kernel 6.6.2 +
`/usr/lib/modules/6.6.2-...`). For the **first boot, use that bundled kernel** — modules are guaranteed to
match, minimal moving parts. Only *after* Debian is up and stable do you (optionally) install a newer
kernel `.deb` natively and rebuild the `uImage` ([07](07-optimizations.md)). This keeps first boot as
simple and reliable as possible.

## Time budget & risk posture

- Backup: hours (limited by the NAS's weak CPU on SSH — see [02](02-backup-and-nand-dump.md)).
- Build stick + UART + first boot: ~1 hour once backups are done.
- **Nothing is written to the data disks or NAND during OS setup.** Up to the moment you deliberately
  mount the array read-write, every step is undone by unplugging the USB stick.

Next: **[02 — Back up & dump NAND](02-backup-and-nand-dump.md)**.
