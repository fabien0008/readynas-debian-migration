# 02 — Back up data, dump NAND, capture config

Do this **while the stock ReadyNAS is still running.** Three parts: (1) back up data, (2) dump the NAND
(restore-to-stock insurance), (3) capture your service config so clients keep working after the switch.

> Enable SSH on the ReadyNAS (Admin UI → System → Settings → Services → SSH) if it isn't already, and log
> in as `root`.

## 1. Back up your data

**Triage first — most of a media NAS is replaceable.** Check what's actually irreplaceable:

```bash
# on the ReadyNAS
du -sh /<data-volume>/*/ | sort -rh      # e.g. /<volume> is the btrfs data mount
```

Typically videos/ISOs/games are re-downloadable and RAID-protected; **photos, documents, personal files**
are the irreplaceable core and are usually a fraction of the total. Back up at least that core off-box.

**Copy it off** (from another Linux box, pulling over SSH — gentle on the array):

```bash
# on the backup target box; repeat per folder you want to keep
DEST=/path/to/backup
rsync -aH --numeric-ids --info=progress2 \
      --rsync-path="ionice -c3 nice -n19 rsync" \
      root@<nas-ip>:/<data-volume>/photos/ "$DEST/photos/"
```

- `--numeric-ids` preserves the original UID/GID **as numbers** — essential, because you'll recreate the
  same users on Debian ([06](06-services-and-clients.md)) and ownership must line up.
- `--rsync-path="ionice -c3 nice -n19 rsync"` runs the reader at idle priority so it can't disturb the
  array (or a running RAID rebuild).
- **Expect it to be slow** (~10 MB/s) on the 1-core Armada 370 — SSH crypto is the bottleneck (no AES
  acceleration), *not* the disks or network. Let it run overnight.

**Verify** a sample before trusting it (`diff <(ssh root@<nas-ip> 'ls /<vol>/photos|sort') <(ls "$DEST/photos"|sort)`).

> RAID1 is **not** a backup. Even though this migration never writes to the data disks, take the backup —
> it's the difference between "annoying" and "catastrophic" if anything goes wrong.

## 2. Dump the NAND (your restore-to-stock insurance)

Copy every MTD partition to your build box. This lets you reflash the original ReadyNAS bootloader/OS if
you ever need to (see [08](08-rollback-and-recovery.md)):

```bash
# on the build box — pulls each /dev/mtdN over SSH
ssh root@<nas-ip> 'cat /proc/mtd'                 # note the layout first
for m in 0 1 2 3 4; do
  ssh root@<nas-ip> "dd if=/dev/mtd$m 2>/dev/null" > mtd${m}.bin
done
sha256sum mtd*.bin > NAND-MANIFEST.sha256         # record checksums
```

`mtd0`=u-boot, `mtd1`=u-boot-env, `mtd2`=kernel(uImage), `mtd3`=minirootfs, `mtd4`=ubifs(stock OS). Keep
these safe and **out of any public repo** (the env can contain your MAC/serial).

> Also check for NAND **bad blocks** now — they affect whether flashing the kernel to NAND is safe (we
> avoid that anyway; we USB-boot): `dmesg | grep -i 'bad block'`. Table markers at the top pages are
> normal; actual "bad block at ..." in the data region means *never* let `flash-kernel` write NAND.

## 3. Capture your service config

So NFS/SMB clients, users, and automation keep working after the switch. Save these (they're **not**
secret except where noted — keep host keys / password DBs private):

```bash
ssh root@<nas-ip> '
  echo "== identity =="; hostname; ip -o link show | grep ether; ip -o -4 addr show
  echo "== NFS =="; cat /etc/exports; grep -vE "^#|^$" /etc/default/nfs-kernel-server
  echo "== Samba =="; testparm -s 2>/dev/null; pdbedit -L
  echo "== users/groups (UID/GID) =="; awk -F: "\$3>=99 && \$3<65000" /etc/passwd; awk -F: "\$3>=99 && \$3<65000" /etc/group
' > nas-service-config.txt

# PRIVATE (do not commit anywhere public):
#   /etc/ssh/ssh_host_*         -> reuse so clients get no host-key-changed warning
#   /var/lib/samba/private/*.tdb -> reuse to keep existing SMB passwords
#   /root/.ssh/authorized_keys   -> keep your key-based logins working
```

You'll turn this capture into working Debian config in [06 — Services & clients](06-services-and-clients.md).

## When can you power off?

Once **(1) the data backup has completed and verified, (2) the NAND dump + checksums are saved, and
(3) the service config is captured**, you're free to shut the NAS down and begin the physical work.
Shut down **gracefully** (Admin UI, power button, or `ssh root@<nas-ip> 'systemctl poweroff'`) so btrfs
flushes cleanly. **Leave the disks in the unit** — the migration keeps them in place.

Next: **[03 — Build the USB rootfs](03-build-usb-rootfs.md)**.
