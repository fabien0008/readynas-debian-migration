# 08 — Rollback & recovery

## The easy rollback (because we never wrote to NAND or the disks)

For the whole USB-boot approach, **restoring the stock ReadyNAS OS is just: power off, unplug the USB
stick, power on.** The stock firmware is untouched in the `ubifs` NAND partition and boots via the
original `bootcmd`.

The only exception: if you ran `saveenv` to make USB boot permanent ([04 §5](04-uart-and-uboot.md)). Then,
at the U-Boot prompt, restore the stock boot command you saved earlier:

```
setenv bootcmd 'nand read 0x2000000 0x200000 0x400000; nand read 0x3000000 0x800000 0x400000; bootm 0x2000000 0x3000000 0x1000000'
saveenv
reset
```

## Recover your data on *any* Linux box

The data is standard **mdadm RAID + btrfs** — portable to any Linux machine. If the NAS itself dies, pull
the disks, attach them (SATA or USB dock), and:

```bash
mdadm --assemble --scan            # or: mdadm --assemble --run /dev/mdX /dev/sdX /dev/sdY
mount -o ro /dev/mdX /mnt/recover  # read-only first, always
```

This works from a desktop, a laptop, even a Raspberry Pi. It's the ultimate safety net — your files are
never locked inside a proprietary format.

## If NAND is ever damaged (last resort)

If you deliberately flashed NAND and bricked boot, reflash from the dumps you took in
[02](02-backup-and-nand-dump.md) (`mtd0`=u-boot, `mtd2`=kernel, etc.) with `flash_erase` + `nandwrite`,
**only** after reading the Doozan "Restore ReadyNAS 102/104 to original state" HOWTO. Verify against your
`NAND-MANIFEST.sha256`.

## ⚠️ The one thing to never do: `flash-kernel` → NAND

The "classic" Debian-on-ReadyNAS guides offer to write the Debian kernel into NAND via `flash-kernel`.
**Both** original authors (Uwe Kleine-König and Hillenius) warn that `flash-kernel` mishandles NAND bad
blocks and *"might damage your flash beyond repair."*

This guide's USB-boot method **deliberately avoids it** — the kernel stays on the USB stick, NAND stays
read-only. Stay on USB boot. If you insist on NAND boot, first confirm zero bad blocks in the `uImage`
region (`dmesg | grep -i 'bad block'`) and accept the risk.

## Rules that protect your data (recap)

- `mdadm --assemble`, **never** `mdadm --create`.
- **No** `mkfs` / `wipefs` / `sgdisk` / `fdisk` on the data disks.
- **No** ReadyNAS factory reset / RAID-level change (those destroy the volume).
- Mount **read-only first**, verify, then read-write.
- Back up before you start; keep the NAND dumps.

---

*Sources: Doozan forum "Restore ReadyNAS 102/104 to original state"; Uwe Kleine-König & Hillenius Debian-on-
ReadyNAS guides (flash-kernel warning); community RN102 data-salvage threads.*
