# ReadyNAS → Debian migration (ARM Armada 370/XP family)

A practical, **non-destructive** guide to replacing the end-of-life Netgear **ReadyNAS OS 6** with
mainline **Debian** on the ARM (Armada 370 / Armada XP) ReadyNAS boxes — booting Debian from a **USB
stick** while leaving your existing **RAID1/RAID/btrfs data disks and the NAND untouched**.

It also carries over the **vendor tunings** Netgear shipped for this hardware (network/RAID/VM sysctls,
fan/thermal policy, LEDs, watchdog, disk spindown) and — most importantly — recreates the **SMART +
btrfs-scrub + mdadm monitoring** that ReadyNAS ran *inside its closed daemon* and that a plain Debian
install does **not** inherit. (**Wake-on-LAN is the one vendor feature that does *not* carry over** on
the RN102 — it's a hardware limit; see [docs/12](docs/12-wake-on-lan-rn102.md).)

> **Why**: ReadyNAS OS 6.10.10 is the final release; ReadyCLOUD and the app UI are gone, the base is an
> EOL Debian 8 (Jessie) with an ancient 4.x kernel, and Netgear has exited the business. The hardware,
> though, is a perfectly good little ARM NAS that mainline Linux fully supports.

> ⚠️ **Unofficial / at your own risk.** This replaces Netgear's firmware stack. Done carefully (backups
> first, USB-boot only, data disks mounted read-only until verified) the risk to your data is low, but it
> is never zero. Read [docs/08-rollback-and-recovery.md](docs/08-rollback-and-recovery.md) before you start.

---

## Supported models

Any Netgear ReadyNAS built on **Marvell Armada 370 or Armada XP** running **ReadyNAS OS 6** — they share
U-Boot, the NAND/MTD layout, and the mainline `mvebu` kernel. You only change the **device tree (DTB)** per
model. See [models/compatibility.md](models/compatibility.md) for the full table.

| Model | SoC | Bays | Device tree |
| --- | --- | --- | --- |
| **RN102** | Armada 370 | 2 | `armada-370-netgear-rn102.dtb` |
| **RN104** | Armada 370 | 4 | `armada-370-netgear-rn104.dtb` |
| **RN202** | Armada 385 | 2 | `armada-385-netgear-rn202.dtb` |
| **RN204** | Armada 385 | 4 | `armada-385-netgear-rn204.dtb` |
| **RN212 / RN214** | Armada 385 | 2 / 4 | `armada-385-netgear-rn21x.dtb` |
| **RN2120** | Armada XP | 4 | `armada-xp-netgear-rn2120.dtb` |

> The **method is identical** for all of them; substitute the DTB name for your model everywhere this guide
> says `<your-model>.dtb`. The Armada 370 boxes (RN102/RN104) are the most documented; the RN2120 (Armada
> XP) and the Armada 385 units (RN2xx) follow the same recipe with their own DTB.

---

## The approach in one picture

```
                 ┌─────────────────────────────────────────────────────────┐
   Netgear NAND  │ u-boot │ u-boot-env │ uImage │ minirootfs │   ubifs      │  ← left UNTOUCHED
   (128 MiB)     └─────────────────────────────────────────────────────────┘     (stock OS still here)
                                    │ U-Boot told to boot from USB
                                    ▼
   USB stick  ─────────────►  Debian rootfs + kernel + your-model DTB   ← the new OS lives HERE
                                    │  first boot
                                    ▼
   Data disks (RAID1 + btrfs) ──►  mounted READ-ONLY, verified, then read-write   ← never repartitioned
```

- The **OS moves to USB.** NAND keeps the stock ReadyNAS OS, so *unplug the stick → boots stock again*.
- The **data array is standard `mdadm` + `btrfs`** — assembled, never re-created. `mdadm --assemble`, not
  `mdadm --create`. No `mkfs`, no factory reset, no repartition of the data disks.
- A **serial (UART) console** is the only manual step; everything else can be scripted/agent-driven.

---

## Quick start

1. **[01 – Prerequisites](docs/01-prerequisites.md)** — a USB-TTL 3.3 V adapter, a USB stick, a Linux box.
2. **[02 – Back up & dump NAND](docs/02-backup-and-nand-dump.md)** — data backup + full NAND image (your
   restore-to-stock insurance) + capture your service config.
3. **[03 – Build the USB rootfs](docs/03-build-usb-rootfs.md)** — bodhi Debian rootfs + kernel + your DTB → `uImage`.
4. **[04 – UART & U-Boot](docs/04-uart-and-uboot.md)** — wire the serial header, boot Debian from USB.
5. **[05 – First boot & RAID](docs/05-first-boot-and-raid.md)** — verify hardware, mount the array read-only, then rw.
6. **[06 – Services & clients](docs/06-services-and-clients.md)** — NFS/SMB, users/UIDs, keep clients seamless.
7. **[07 – Optimizations](docs/07-optimizations.md)** — the vendor tunings + the resilience gaps to close.
8. **[08 – Rollback & recovery](docs/08-rollback-and-recovery.md)** — get back to stock, or recover data anywhere.
9. **[09 – RN102/RN104: silent hang after "Starting kernel..."?](docs/09-rn102-rn104-special-kernel.md)** —
   read this if step 5 hangs with no console output; you likely need the special old-U-Boot kernel build.
10. **[10 – Adopting newer kernels](docs/10-kernel-upgrades.md)** — the repeatable routine to track bodhi's 370xp releases.
11. **[11 – "invalid root flags" btrfs mount fix](docs/11-btrfs-mount-root-flags-fix.md)** — mount a ReadyNAS-created btrfs volume on a modern kernel.
12. **[12 – Wake-on-LAN on the RN102: why it can't work](docs/12-wake-on-lan-rn102.md)** — the full
    investigation + verdict (hardware limit). Read before you spend days on WOL.

> ⚠️ **Two traps this guide now documents up front:** (a) **WOL does not work from power-off on the
> RN102** — it's a hardware limit, not a config you're missing ([12](docs/12-wake-on-lan-rn102.md)); and
> (b) on a **non-systemd** rootfs the **`orion_wdt` watchdog will hard-reboot the box every ~4 minutes**
> unless you run a feeder — see [07 → Hardware watchdog](docs/07-optimizations.md#hardware-watchdog--feed-it-or-the-box-reboots-every-4-minutes).

---

## Credits & sources

This guide stands on the shoulders of the community that reverse-engineered these boxes:

- **bodhi** (Doozan forum) — the `mvebu` Debian kernels + rootfs and the stock-U-Boot USB-boot method:
  Doozan "Debian on Netgear RN102" and the kernel/rootfs release threads.
- **Uwe Kleine-König** — "Installing Debian Jessie on a Netgear ReadyNAS 104" (the canonical UART + netboot recipe).
- **Hillenius** — "Installing Debian Jessie on a Netgear ReadyNAS 102".
- Mainline Linux — device-tree + drivers (`mvneta`, `g762`, `rtc-isl12057`, `armada_thermal`) for these boards.

See each doc's *Sources* footer for links. **License: [MIT](LICENSE).** PRs welcome — especially confirmed
results and DTB/UART details for models not yet covered here.
