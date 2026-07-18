# 09 — RN102/RN104: you need the special "old-u-boot" kernel, not the generic build

If you followed [03](03-build-usb-rootfs.md) using bodhi's **generic** `linux-x.y.z-mvebu-tld-N-bodhi.tar.bz2`
kernel package, your RN102 or RN104 will very likely **hang silently right after `Starting kernel ...`**
with zero further console output — even with `earlyprintk`/`earlycon` set. Checksums verify fine, the
images load fine; it just goes dark.

## Root cause

The RN102/RN104 (and the GlobalScale Mirabox — same Armada 370 family) ship with an **old Marvell U-Boot**
that initializes the SoC's internal MBUS memory windows at the **old** physical address for the SoC's
internal registers (including the UART). Bodhi's generic `mvebu-tld-N` kernel line is compiled for the
**new** address used by newer U-Boot on most other MVEBU boxes. When the kernel tries to talk to hardware
at an address U-Boot never actually mapped there, it hangs — before any console driver gets a chance to
print anything. That's the entire mechanism; it has nothing to do with your DTB pairing or how you got the
kernel onto the board (USB vs TFTP vs NAND all fail identically).

This is documented directly by bodhi (the kernel maintainer) in the Doozan "Debian on Netgear RN102" forum
thread, after another user hit this exact symptom.

## The fix: use the special Mirabox/370xp-flavored kernel

Bodhi maintains a **separate kernel line** built specifically for these old-U-Boot boxes:

- `linux-x.y.z-mvebu-mirabox-tld-N-bodhi.tar.bz2`, or later renamed
- `linux-x.y.z-mvebu-370xp-tld-N-bodhi.tar.bz2`

Use this kernel's `zImage`, still paired with **your board's own DTB** (`armada-370-netgear-rn102.dtb` or
`-rn104.dtb`) — don't swap to the Mirabox's DTB. Everything else in [03](03-build-usb-rootfs.md) is
unchanged; only the kernel source differs.

A `370xp-tld-4` build (kernel 5.9.3) is confirmed in the thread by a real SSH login into a working RN102
Debian system, reaching ~580–640 Mbit/s iperf throughput — so this line is a solid, proven choice, even
though it's an older kernel than the generic release line.

> Link rot: the original `bodhi`-hosted Dropbox links for these special builds from ~2020–2021 have started
> to die. Check the current pinned links in the Doozan **"Debian on Netgear RN102"** thread and the
> **"Linux Kernel MVEBU package and Debian armhf rootfs"** release thread; if a `/s/...` style link is dead,
> search the thread for a later re-post/mirror before assuming it's gone for good.

## How to tell if you're hitting this

- U-Boot loads and checksums both images fine (`Verifying Checksum ... OK` for both kernel and initrd).
- `Starting kernel ...` prints, then **total silence** — not even garbled output, not even with
  `earlycon=ns16550,mmio32,0xd0012000` (the RN102/104's actual UART physical address) added to `bootargs`.
- Swapping the delivery method (USB → TFTP) changes nothing — same hang, same point. This rules out USB
  corruption/flakiness as the cause and points at the kernel/board-U-Boot combination itself.
- Re-pairing with a different/newer DTB from the same kernel family also changes nothing — this isn't a DTB
  versioning mismatch, it's a fundamental physical-address mismatch baked into the kernel's compile-time
  config (`CONFIG_DEBUG_UART_PHYS`/`_VIRT`).

## One important procedural note

Once `bootm` hands control to the kernel, **U-Boot's command shell is gone** — you cannot send further
`setenv`/`bootm` commands into the same hung serial session to try something else. Any further keystrokes
are simply lost (or land on whatever, if anything, is listening on that TTY inside the hung/silent kernel).
To try a different kernel or bootarg, you must power-cycle and re-enter U-Boot fresh each time.

Next: rebuild `uImage` per [03](03-build-usb-rootfs.md) using the special kernel's `zImage` + your board's
DTB, and retry [04](04-uart-and-uboot.md)/[05](05-first-boot-and-raid.md) from a fresh power-cycle.

---

*Source: Doozan forum, "Debian on Netgear RN102" thread (bodhi's diagnosis and the confirmed-working
`370xp-tld-4` boot log), and the "Linux Kernel MVEBU package and Debian armhf rootfs" release thread
(kernel package index and naming history).*
