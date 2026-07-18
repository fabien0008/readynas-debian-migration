# 03 — Build the USB rootfs stick

On your Linux build box. This produces a self-contained Debian on USB, with a `uImage` built for **your**
model's device tree.

> ⚠️ **Identify the USB device carefully.** `lsblk` before and after plugging it in. Using the wrong
> `/dev/sdX` here is the one place in this whole process you can wipe something you care about.

## 1. Partition & format (one ext-labelled partition)

bodhi's rootfs expects the root partition **labelled `rootfs`**:

```bash
export DEV=/dev/sdX          # <-- YOUR usb stick, verified with lsblk. NOT an internal disk.
sudo wipefs -a "$DEV"
echo -e 'label: dos\n,,83\n' | sudo sfdisk "$DEV"     # single primary Linux partition
sudo mkfs.ext3 -L rootfs "${DEV}1"
```

## 2. Unpack the rootfs

```bash
sudo mkdir -p /mnt/usb && sudo mount "${DEV}1" /mnt/usb
sudo tar -xjf /path/to/Debian-<ver>-mvebu-tld-1-rootfs-bodhi.tar.bz2 -C /mnt/usb
sync
```

The rootfs already contains, for its bundled kernel `<ver>`:
`/boot/zImage-<ver>-mvebu-tld-1`, `/boot/uInitrd`, `/boot/dts/<all-models>.dtb`, and
`/usr/lib/modules/<ver>-mvebu-tld-1/`.

## 3. Build the `uImage` for your model

Concatenate the kernel `zImage` with **your model's DTB**, then wrap it with `mkimage`:

```bash
cd /mnt/usb/boot
sudo cp -a zImage-<ver>-mvebu-tld-1 zImage.fdt
sudo sh -c 'cat dts/<your-model>.dtb >> zImage.fdt'      # e.g. armada-370-netgear-rn102.dtb
sudo mkimage -A arm -O linux -T kernel -C none -a 0x00008000 -e 0x00008000 \
     -n "Linux-<ver>-mvebu-tld-1" -d zImage.fdt uImage
sudo rm -f zImage.fdt
```

Now `/mnt/usb/boot/` has **`uImage`** (kernel+DTB for your box) and **`uInitrd`** (from the rootfs) — the
two files U-Boot will load.

> Load/entry address `0x00008000` is correct for Armada 37x/38x/XP with Marvell stock U-Boot.

## 4. Sanity checks

```bash
grep -v '^#' /mnt/usb/etc/fstab | grep -v '^$'     # should contain:  LABEL=rootfs / ext3 ...
ls -la /mnt/usb/boot/uImage /mnt/usb/boot/uInitrd  # both present
```

Default bodhi root password is `root` (change it on first boot). Optionally drop your SSH public key into
`/mnt/usb/root/.ssh/authorized_keys` now for a key-only first login.

## 5. Finish

```bash
sync
cd / && sudo umount /mnt/usb
```

The stick is ready. Next: **[04 — UART & U-Boot](04-uart-and-uboot.md)**.
