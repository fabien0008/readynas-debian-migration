# 05 — First boot & mounting your RAID (read-only first)

Debian is now running from USB. Verify the hardware, then bring up your existing array **read-only** and
confirm your data before you ever write to it.

## 1. Verify the box

Log in on the serial console (bodhi default `root` / `root`), then:

```bash
uname -a                        # your kernel version
ip a                            # NIC up? (some boxes: only the UPPER Ethernet jack works in U-Boot; both work in Linux)
lsblk                           # data disks (sda/sdb/...), md devices, and the USB all present?
lsusb
dmesg | grep -iE 'sata|ahci|mvneta|mvebu|error' | tail
free -m ; cat /proc/cpuinfo
```

Get it on the network (DHCP is fine for now) and `ssh` in so you're not tied to the serial line.

## 2. Assemble the array and mount READ-ONLY

**This is the moment of truth — and it is read-only, so it's safe. Never `mdadm --create`.**

```bash
apt-get update && apt-get install -y mdadm btrfs-progs

mdadm --assemble --scan          # reads superblocks; does NOT create anything
cat /proc/mdstat                 # your data array should appear, e.g. [UU]

mkdir -p /mnt/data
mount -o ro /dev/mdXYZ /mnt/data # the data array (btrfs). ReadyNAS default subvol works; or -o ro,subvol=data
ls -la /mnt/data
du -sh /mnt/data/* 2>/dev/null
btrfs filesystem show /dev/mdXYZ
```

Open a few real files (a photo, a document). **Cross-check against the backup** from
[02](02-backup-and-nand-dump.md). If anything about the array looks wrong — **stop**, unplug the USB
stick, power-cycle, and you're back on stock ReadyNAS with your data intact. Nothing was written.

> ReadyNAS lays the data out as **btrfs subvolumes** on top of an mdadm RAID. Mounting the top volume
> exposes the subvolumes as directories (e.g. `/mnt/data/<share>`). Note the subvolume you actually serve
> so you can keep client paths identical in [06](06-services-and-clients.md).

## 3. Go read-write

Only once you've verified the data:

```bash
umount /mnt/data
mount /dev/mdXYZ /mnt/data       # read-write
# persist in /etc/fstab (by UUID):
echo "UUID=$(blkid -s UUID -o value /dev/mdXYZ) /mnt/data btrfs noatime,nodiratime,space_cache=v2 0 0" >> /etc/fstab
```

> On kernel 6.x, mount with **`space_cache=v2`** (free-space tree) — much faster mount/allocation on large
> volumes than the ReadyNAS-era `space_cache` (v1). More in [07](07-optimizations.md).

## 4. Persist the array

```bash
mdadm --detail --scan >> /etc/mdadm/mdadm.conf     # pin the ARRAY lines
update-initramfs -u                                # so the array assembles at boot
```

Next: **[06 — Services & clients](06-services-and-clients.md)**.
