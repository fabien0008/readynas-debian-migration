# 10 — Adopting newer kernels as they're released

Once Debian is running from the special `370xp` kernel (see [09](09-rn102-rn104-special-kernel.md)),
staying current is a simple, repeatable routine. bodhi periodically publishes new
`linux-<ver>-mvebu-370xp-tld-1-bodhi.tar.bz2` builds in the Doozan release thread — the **370xp flavor is
the one to track** for RN102/RN104 (the generic `mvebu-tld` builds will hang, per [09](09-rn102-rn104-special-kernel.md)).

## The recipe (do it from the running system, natively — no cross-compile)

```bash
cd /root
# 1. fetch the new 370xp kernel tarball (from the Doozan release thread)
# 2. unpack + install the kernel .deb natively (installs modules + /boot files, runs depmod)
tar xjf linux-<ver>-mvebu-370xp-tld-1-bodhi.tar.bz2
dpkg -i linux-image-<ver>-mvebu-370xp-tld-1_1_armhf.deb

# 3. rebuild the U-Boot uImage from the new zImage + this board's DTB.
#    ALWAYS keep the current working uImage as a fallback first:
cd /boot           # (this is on the USB rootfs)
cp -a uImage uImage.bak
cp -a /root/zImage-<ver>-mvebu-370xp-tld-1 zImage.fdt
cat /usr/lib/linux-image-<ver>-mvebu-370xp-tld-1/armada-370-netgear-rn102.dtb >> zImage.fdt   # your board's DTB
mkimage -A arm -O linux -T kernel -C none -a 0x00008000 -e 0x00008000 \
        -n "Linux-<ver>-mvebu-370xp-tld-1" -d zImage.fdt uImage
rm -f zImage.fdt

# 4. regenerate the initrd for the new kernel (mdadm/btrfs/etc. hooks). Installing the
#    .deb usually already ran update-initramfs; make sure the matching initrd exists:
update-initramfs -c -k <ver>-mvebu-370xp-tld-1 2>/dev/null || update-initramfs -u
# then build the uInitrd U-Boot wraps (if your boot flow uses /boot/uInitrd):
mkimage -A arm -O linux -T ramdisk -C gzip -n "initramfs-<ver>" \
        -d /boot/initrd.img-<ver>-mvebu-370xp-tld-1 /boot/uInitrd

reboot
```

## Safety rails

- **Keep `uImage.bak`.** If the new kernel doesn't boot, at the U-Boot prompt load the backup instead:
  `ext2load usb 0:1 0x2000000 /boot/uImage.bak` (or just `cp uImage.bak uImage` from a rescue boot).
- **Test before trusting.** After reboot, confirm `uname -r`, that the NIC came up (`ip link`), the RTC set
  the clock, RAID assembled, and swap is active — the same checks as first boot ([05](05-first-boot-and-raid.md)).
- **The DTB must come from the new kernel's own package** (`/usr/lib/linux-image-<ver>.../` after `dpkg -i`),
  not an older standalone copy — device-tree bindings evolve with the kernel.
- **One kernel at a time.** Don't delete the previous `linux-image-*` package until the new one is proven;
  its `/boot/uImage.bak` + modules are your rollback.

## Why kernel modules must be installed (not just the zImage swapped)

On these builds the NIC (`mvneta`) and RTC drivers are **modules** (`CONFIG_MVNETA=m`), so a new kernel is
useless for networking until its `/lib/modules/<ver>/` tree exists. `dpkg -i` of the kernel `.deb` is what
populates that (and runs `depmod`). Swapping only the `zImage`/`uImage` gets you a login prompt but no
network — see [09](09-rn102-rn104-special-kernel.md) for the full symptom writeup.

## Building a custom kernel: keep drivers built-in

If you rebuild the kernel yourself (e.g. to patch a driver) — cross-compile is easy:
`ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf-`, bodhi ships the `.config` + a `.patch` in the
tarball, apply on top of the matching mainline `linux-<ver>` from kernel.org — beware the
**module-ABI trap**:

> Your rebuild's exported-symbol **CRCs won't match bodhi's prebuilt `.ko` files** (any `.config`
> change, even one flipped by `make olddefconfig`, shifts them). So **none of the stock
> `/lib/modules/<ver>/*.ko` will load** on your kernel (`Unknown symbol … (err -22)`). If a *boot- or
> hardware-critical* driver is a **module**, the box breaks in confusing ways:
> - `btrfs=m` → `mount /dev/md127 … No such device` (root fs type unavailable) → initramfs shell.
> - `mvneta=m` → boots, but **no `eth0`** → no network.
> - `i2c_mv64xxx=m` → **no I²C bus → no `g762` fan control** (thermal risk) and no RTC.

**Fix: build every RN102-relevant driver into the kernel (`=y`), not as a module.** It's a fixed
platform, so there's no downside. At minimum flip these from `=m` to `=y` before building
(`./scripts/config -e <OPT>` then `make olddefconfig`):

```
BTRFS_FS  MVNETA  MVNETA_BM  I2C_MV64XXX  I2C_CHARDEV  SENSORS_G762
RTC_DRV_DS1307   (the isl12057 RTC is driven by rtc-ds1307)   KEYBOARD_GPIO  CHR_DEV_SG
```
(RAID1/AHCI/MVMDIO/MARVELL_PHY are usually already `=y`.) The result is a **self-contained** kernel:
it boots with root + NIC + fan + RTC even against a mismatched/old initrd and `/lib/modules` tree —
much more robust than the stock `=m` layout. You then don't even need to reinstall modules.

If you flash a custom kernel to **NAND** (`mtd2`) rather than booting from USB, back up the current
`mtd2` first (`nanddump -f mtd2.bak /dev/mtd2`) and verify the readback md5 after `nandwrite`; recovery
is a serial/TFTP boot of the backup. (Real-world example: the `mvmdio` WOL patch in
[12 — Wake-on-LAN](12-wake-on-lan-rn102.md) was built and flashed exactly this way.)

## Keeping it boot-from-USB (no NAND writes)

None of this touches NAND. The kernel/initrd live on the USB rootfs; U-Boot loads them from USB. Newer
kernels change nothing about that contract — you're only replacing files on the stick.
