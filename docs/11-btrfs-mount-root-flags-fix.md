# 11 — Fixing "invalid root flags" so the ReadyNAS btrfs volume mounts on a modern kernel

## Symptom

Your Debian is running, the RAID array assembles fine (`mdadm --assemble --scan` → `[UU]`), but mounting
the data volume fails:

```
$ mount -o ro /dev/md127 /mnt
mount: can't read superblock on /dev/md127

$ dmesg | tail
BTRFS critical (device md127): corrupt leaf: root=1 block=... slot=..., \
    invalid root flags, have 0x10000 expect mask 0x1000000000001
BTRFS error (device md127): read time tree block corruption detected
BTRFS error (device md127): open_ctree failed: -5
```

## Why

ReadyNAS OS 6 shipped a **vendor-patched btrfs** that sets a proprietary flag (**bit 16, `0x10000`**) on
the root item of its data subvolume — part of its snapshot machinery. Mainline btrfs added a
**tree-checker** (kernel commit `259ee775`, ~v5.2) that validates root-item flags against a strict mask
(only `SUBVOL_RDONLY` bit 0 and `SUBVOL_DEAD` bit 48 are legal). The stray `0x10000` fails that check, so
**any kernel ≥ 5.2 refuses to mount** — even read-only, even with `rescue=all`.

**Your data is fine.** This is a metadata-format nit, not corruption:
- `btrfs check /dev/md127` passes (only benign qgroup accounting diffs).
- `btrfs restore` reads every file correctly.
- `btrfs inspect-internal dump-tree -t root` shows exactly one offending item.

## The fix: clear that one flag

The change is surgical — **one 8-byte field in one metadata leaf** (plus that leaf's checksum). No data
blocks are touched. The proper tool is `btrfs-corrupt-block` (recomputes the checksum), but Debian doesn't
package it. The method below is a **fully deterministic, self-validating byte patch** that needs no special
tools — and, crucially, you can *prove your checksum math is correct against the live block before writing
anything*.

> ⚠️ Back up first. This edits filesystem metadata. Take at least a `dd` copy of the affected leaf (below),
> and ideally a full `btrfs-image -c9 /dev/mdX -` metadata snapshot. Unmount the volume during the edit.

### 1. Find the offending root item and its leaf

```bash
btrfs inspect-internal dump-tree -t root /dev/md127 | grep -B0 -A2 'flags 0x10000'
#   item 30 key (260 ROOT_ITEM 0) itemoff 27218 itemsize 439
#       last_snapshot 29613 flags 0x10000(none) refs 1     <- the culprit (subvol 260 here)

# which leaf holds it, and its item offset
btrfs inspect-internal dump-tree -t root /dev/md127 | awk '
  /^\tleaf [0-9]+ items/ {leaf=$2}
  /flags 0x10000/ {print "leaf(logical)="leaf}'
```

Note the **`itemoff`** (here `27218`) and the **nodesize** (`btrfs inspect-internal dump-super /dev/md127 |
grep nodesize` — commonly `16384`, on this box `32768`).

### 2. Map the leaf to physical offsets (btrfs stores metadata as DUP → **two** copies)

```bash
btrfs-map-logical -l <leaf_logical> /dev/md127
#   mirror 1 logical <L> physical <P1> device /dev/md127
#   mirror 2 logical <L> physical <P2> device /dev/md127
```

Both copies are identical and **both must be fixed** (leave one stale and btrfs may read it, or a scrub may
"heal" the good one from the bad one).

### 3. Back up the leaf, then patch on a workstation (self-validated)

```bash
NS=<nodesize>
dd if=/dev/md127 bs=1 skip=<P1> count=$NS of=leaf_orig.bin      # rollback copy
```

The **flags field** lives inside the `btrfs_root_item`. Its byte offset within the leaf is:

```
flag_off = 101 (btrfs_header) + <itemoff> + 208 (flags offset inside btrfs_root_item)
```

(101 = header size; 208 = `sizeof(btrfs_inode_item)=160` + 6×`__le64`=48, i.e. generation, root_dirid,
bytenr, byte_limit, bytes_used, last_snapshot — flags is the 7th u64.) **Verify** before trusting it:
`xxd -s $flag_off -l 8 leaf_orig.bin` must read `00 00 01 00 00 00 00 00` (little-endian `0x10000`).

Patch + recompute the crc32c checksum (btrfs default; covers bytes `[32 .. nodesize)`, stored little-endian
at bytes `[0:4]`). **Validate the crc32c implementation against the existing checksum first** — if it
reproduces the block's stored csum, it's correct:

```python
POLY=0x82F63B78                     # reflected crc32c (Castagnoli)
tbl=[]
for n in range(256):
    c=n
    for _ in range(8): c=(c>>1)^POLY if c&1 else c>>1
    tbl.append(c)
def crc32c(buf):
    crc=0xFFFFFFFF
    for b in buf: crc=(crc>>8)^tbl[(crc^b)&0xFF]
    return crc^0xFFFFFFFF

d=bytearray(open('leaf_orig.bin','rb').read())
assert crc32c(d[32:]) == int.from_bytes(d[0:4],'little'), "crc impl wrong - STOP"  # self-check

FL=<flag_off>
assert d[FL:FL+8]==bytes([0,0,1,0,0,0,0,0])
d[FL:FL+8]=b'\x00'*8                                   # clear the flag
d[0:4]=crc32c(d[32:]).to_bytes(4,'little')            # recompute checksum
open('leaf_fixed.bin','wb').write(d)
# sanity: only the csum (bytes 0-3) and the one flag byte should differ from leaf_orig.bin
```

### 4. Write both mirrors, verify, mount

```bash
# nodesize-aligned writes (seek = physical_offset / nodesize)
dd if=leaf_fixed.bin of=/dev/md127 bs=$NS seek=$((P1/NS)) count=1 conv=notrunc oflag=direct
dd if=leaf_fixed.bin of=/dev/md127 bs=$NS seek=$((P2/NS)) count=1 conv=notrunc oflag=direct
sync

# verify the tool now reads flags 0x0, then mount
btrfs inspect-internal dump-tree -t root /dev/md127 | grep -A2 '(260 ROOT_ITEM 0)'   # flags 0x0(none)
mkdir -p /FFNASVOLUME && mount -o ro /dev/md127 /FFNASVOLUME && ls /FFNASVOLUME
```

If it mounts read-only and lists your shares — **done**. Remount read-write
(`mount -o rw,noatime,nodiratime`), run a `touch` write test, and add it to `/etc/fstab`.

**Rollback** if anything looks wrong at any step: `dd if=leaf_orig.bin of=/dev/md127 bs=$NS seek=$((P1/NS))
count=1 conv=notrunc; ` (and P2). Because you only changed one leaf, this is an exact revert.

## Notes

- Multiple subvolumes may carry the flag (snapshots). Repeat for every `flags 0x10000` line `dump-tree`
  shows — each is one leaf/one field.
- This is a **one-time** fix. Once cleared, the volume mounts on any modern kernel and stays fixed; newer
  kernels ([10](10-kernel-upgrades.md)) mount it normally.
- Verified in practice: a real RN102 data volume (2.0 TB used, created by ReadyNAS OS 6.10.10) went from
  `open_ctree failed` to a clean read-write mount with all files intact, using exactly this procedure.
