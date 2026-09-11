# 14 — SSD root migration: getting `/` off the data disks (in progress)

> ⚠️ **Status: planned, not yet executed.** This doc records the plan and one hard-won live finding that
> motivates it. Unlike the other docs in this repo, nothing here has been carried out on real hardware
> yet — treat it as a design doc + open item, not a proven recipe.

## Why

If you followed the USB-free path ([09](09-rn102-rn104-special-kernel.md), the "Advanced" section of the
[README](../README.md)) or otherwise ended up with root as a btrfs subvolume **on the same `mdadm` array
as your data**, you inherit a problem the disk-spindown tuning in
[07 — Optimizations](07-optimizations.md) (the "Flash / USB-boot wear reduction" section) cannot fully
close: **any activity against `/` — SSH logins, cron reading `/etc`, your own diagnostics — keeps the
data disks spinning**, because root and data share physical spindles. That section's item 4 has the live
measurement: 53 hours of continuous rotation with zero standby transitions, traced to exactly this. Three
prior fixes (smartd off the disks, scrub awareness, SMART-poll-vs-timer ratio) are necessary but **not
sufficient** on a root-on-disk build.

The fix isn't another exclusion rule — it's moving `/` onto its own device, so the class of "root reads
wake the array" activity stops touching the data disks at all.

## Scope and limits — what this migration is *not*

- **Not** adding the SSD to the RAID. Data stays exactly where it is: `md127` + btrfs, RAID1, checksums
  and redundancy intact, mounted at the same data mountpoint.
- **Not** a block-level cache (no bcache/LVM cache layer implied). A cold read of something not already
  cached still goes to the HDDs — that's expected and fine; the goal is idle-time silence, not eliminating
  legitimate data I/O.
- **Root only.** `/FFNASVOLUME` (or your equivalent data mount) keeps its own UUID, its own mount, and is
  never recreated or reformatted as part of this.

## Status

- An inexpensive USB-to-SATA adapter for a 2.5" SATA SSD already on hand has been ordered; delivery not
  yet confirmed as received.
- The adapter's UASP / SMART-via-SAT / TRIM support is **unverified** — the listing doesn't guarantee any
  of the three. Confirm on the actual hardware once it arrives; don't assume all three "just work."
- No copying, partitioning, or boot-config change has been made yet. This section will be updated (or
  superseded by a "results" doc) once execution starts.

## Plan

### 1. Qualify the SSD and adapter — read-only, no writes

- Identify the SSD by `lsblk` + `/dev/disk/by-id`, not by inferred device letter (USB enumeration order
  isn't stable, especially across boots).
- Check for existing partitions/filesystems and note what's on it before proposing to reuse it.
- Check SMART via SAT if the adapter passes it through (`smartctl -a -d sat /dev/sdX`). If it doesn't,
  that's not proof the drive is healthy — verify it on a different machine with native SATA before
  trusting it as root.
- No `mkfs`, `wipefs`, repartitioning, or write testing on the target until it's identified and its
  current contents are understood.

> **Known trap to avoid here:** `/etc/rc.local` and `smartd.conf` on a box like this typically reference
> the HDDs as `/dev/sda`/`/dev/sdb` by device letter. Before wiring the SSD into permanent boot
> configuration, switch those HDD references to stable identities (by-id or UUID) — otherwise a USB
> enumeration order change can silently point a spindown timer or a SMART check at the wrong disk, or
> apply the HDD's policy to the SSD by accident.

### 2. Decide scope, back up, measure

- Confirm data backups and RAID/btrfs health are current — RAID1 and snapshots are not a backup.
- Record the currently-running kernel, module set, known-good boot images, and the U-Boot boot command —
  don't assume last week's tested kernel/image combo is still what's active.
- Measure actual root usage **excluding** the data mount and pseudo-filesystems — this, plus the SSD's
  real capacity, decides partitioning; don't guess ahead of the numbers.
- Audit `/root`, `/home`, `/usr`, `/var` for anything that's actually a bind-mount or symlink pointing back
  at the data disks — a leftover admin home directory or binary on the HDDs can still wake them even after
  `/` itself moves.

Two variants, decide after the audit above:

| Variant | Gets you | Requires |
| --- | --- | --- |
| Full root on SSD | Cleanly separates all routine OS reads/writes from data disks | A validated USB-boot-or-SSD-root path and an approved persistent boot change |
| Targeted state/cache move only | Smaller, reversible first step | Root stays on HDD, so it can still be woken by anything not explicitly moved — don't assume partial coverage |

Full root is the actual goal; the targeted variant is a fallback if a persistent boot change turns out not
to be feasible in the available window.

### 3. Copy and prepare, only after the SSD is validated

- Pick a root filesystem the kernel/initramfs in use actually support (ext4 is the simple default; not
  finalized).
- Copy with a tool that preserves numeric UID/GID, permissions, ACLs, hard and symbolic links, xattrs, and
  capabilities (e.g. `rsync -aHAX` plus an explicit dry run first) — verify the resulting tree, not just
  the exit code.
- Explicitly exclude the data mount, `/proc`, `/sys`, `/dev`, `/run`, tmpfs mounts, and the destination
  itself — don't rely solely on `rsync -x` to correctly infer every sub-mount and bind mount.
- Confirm the exact kernel/initramfs that will boot this actually has the USB host, USB-storage/UAS, SCSI
  disk, and target-filesystem drivers — matching a release *name* has not been sufficient to guarantee
  module ABI compatibility in this project before (see [09](09-rn102-rn104-special-kernel.md) and
  [10](10-kernel-upgrades.md)).
- Build any test initramfs in a scratch location to avoid accidentally triggering `flash-kernel` hooks;
  inspect its contents (and confirm no secrets end up in it) before serving it via TFTP.
- Update the **copy's** fstab by UUID, keeping the data volume's existing UUID and mountpoint untouched.

### 4. Test boot with a real fallback available

- Physical console present, no user data copied through it, disks left clean before any reboot.
- First boot attempt via U-Boot/TFTP with **volatile** arguments only — no `saveenv`, no NAND write, until
  the SSD root is proven.
- Explicit checks before calling it a pass:
  - `findmnt /` actually reports the SSD, not the old HDD subvolume.
  - The data mount still resolves to the right btrfs/RAID volume; RAID still shows `[UU]`.
  - No NFS/SMB export of an empty placeholder directory if the data mount failed silently — check the
    real mount source before trusting an export.
  - Network, SSH, NFS/SMB, watchdog feeding, fan control, and RTC all still work (see
    [07](07-optimizations.md) for what "still works" means for each of these).
  - No USB resets, I/O errors, or filesystem errors under both read and controlled-write testing.
  - Falling back to the old HDD root, and booting with the SSD absent entirely, both work without a boot
    loop.

**Persisting the change is a separate, later decision** — this project's standing rule against NAND
writes/`saveenv` without explicit sign-off applies here too (see [08 — Rollback & recovery](08-rollback-and-recovery.md)
for why that rule exists and what it protects).

### 5. Qualify disk-idle behavior after cutover

- Keep integrity checks, non-waking SMART polling (per the "`/var/log` on tmpfs is not enough" callout in
  [07 — Optimizations](07-optimizations.md)), and reasonable spindown timers on the HDDs; a scheduled
  backup or scrub is legitimate activity, not a regression.
- Move only the state that's actually responsible for waking disks onto the SSD — don't blanket-move every
  logging/state policy without checking each one.
- Observe a genuinely hands-off idle window using metrics already being collected, not active polling
  (active polling perturbs exactly what you're trying to measure — see the "measurement traps" list in
  that same callout in [07](07-optimizations.md)).
- Confirm ordinary admin access (SSH, cron) stays on the SSD and does **not** wake the HDDs; if it does,
  there's still a dependency on the data disks to chase.
- An actual (non-cached) video read should still wake the HDDs, as expected; after real idle time, confirm
  they return to standby on their own.

Do not remove the old HDD root subvolume or its boot-fallback configuration until this qualification
window has run and the result has been explicitly signed off.

## Related

- [07 — Optimizations](07-optimizations.md) (Flash / USB-boot wear reduction → disk spindown) — the
  spindown tuning this migration is meant to complete, including the live 53-hour finding that motivated
  this plan.
- [08 — Rollback & recovery](08-rollback-and-recovery.md) — the NAND-write policy and rollback rules that
  also govern step 4 above.
- [09 — RN102/RN104 special kernel](09-rn102-rn104-special-kernel.md) / [10 — kernel upgrades](10-kernel-upgrades.md) —
  the module-ABI and driver-availability traps that step 3's kernel/initramfs check exists to avoid.
