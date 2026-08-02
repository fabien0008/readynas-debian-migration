# 06 — Services & seamless client cutover

Goal: after the OS swap, **existing clients keep working with no reconfiguration** — same IP, hostname, SSH
host keys, NFS exports, SMB shares, and file ownership. Use the capture from
[02](02-backup-and-nand-dump.md).

## 1. Preserve identity

| Thing | How to keep it |
| --- | --- |
| **Hostname** | `hostnamectl set-hostname <old-hostname>`; also `/etc/hosts`. |
| **IP** | Keep the same static IP / DHCP reservation. ⚠️ A MAC-keyed reservation is **not** automatically enough — see the DHCP client-id warning below. |
| **MAC** | Hardware — unchanged by the OS swap, so MAC-keyed reservations *can* keep working. |
| **SSH host keys** | Copy the old `/etc/ssh/ssh_host_*` into the new `/etc/ssh/` (`chmod 600` the private keys). **This is what stops the "REMOTE HOST IDENTIFICATION HAS CHANGED" warning** on every client. |
| **authorized_keys** | Restore `/root/.ssh/authorized_keys` (and per-user) so key logins + any automation keep working. |

### ⚠️ Your DHCP reservation can stop matching even though the MAC never changed

A MAC-keyed reservation is the obvious way to pin the box's address, and it looks safe because the NIC MAC
survives the OS swap. It can still break — and it breaks *later*, after a rootfs rebuild, when you have
forgotten this was ever a variable.

ISC `dhclient` does not identify itself by MAC alone. By default it sends an **RFC-4361 client-identifier**
derived from a DUID stored in `/var/lib/dhcp/dhclient.<iface>.leases`. Rebuild or replace the rootfs (a
kernel experiment, a restore, a fresh install) and that file is regenerated with a **new DUID**, so the
server sees a *different client* on the same MAC and hands out a pool address instead of your reservation.

The DUID does not even contain your NIC's MAC. Ours advertised
`ff:8e:35:96:ab:00:01:00:01:24:f6:79:f5:f2:3c:aa:a9:71:ac` — decoding the embedded link-layer address gives
`f2:3c:aa:a9:71:ac`, unrelated to the real `28:c6:8e:35:96:ab`. Meanwhile the machines whose reservations
kept working were sending the classic MAC-derived form, `01:<mac>`.

**Fix — pin the client-id to the hardware address**, in `/etc/dhcp/dhclient.conf`:

```
send dhcp-client-identifier = hardware;
```

Then `dhclient -r <iface> && dhclient <iface>`. The reservation matches on the first try, and it now
survives future rootfs rebuilds.

> **Check the right thing:** compare the *client-id* column in the server's lease table, not the MAC. In
> `dnsmasq.leases` the working hosts show `01:<mac>`; a box that has drifted shows a long `ff:…` DUID.

> **Diagnostic tip.** If the box transmits DHCP DISCOVERs but *never* completes a lease, suspect the
> **physical link before the DHCP config** — a cable with a damaged RX pair gives a one-way link that looks
> like a DHCP problem. Confirm by watching for a reply that the box ignores:
> `tcpdump -i <iface> -n -e 'port 67 or port 68'`. If you see the server broadcast an OFFER carrying the
> box's own MAC while the box keeps re-DISCOVERing, it cannot hear the reply — replace the cable. (That was
> our fault, after moving the NAS to a different switch; the "changing IPs" we chased were ARP-scan
> artifacts, not real leases.)

## 2. Recreate users with identical UID/GID

File ownership on the btrfs volume is numeric — recreate accounts with the **same** numbers or permissions
break. From your captured `/etc/passwd` / `/etc/group`:

```bash
groupadd -g <gid> <group>
useradd  -u <uid> -g <gid> -s /bin/bash -m <user>      # match the numbers you captured
# ...repeat for each account that owns data or is an SMB user.
```

## 3. NFS — recreate `/etc/exports`

Re-use your captured exports **verbatim** (same paths, same client IPs, same options) and **mount the array
at the same path** clients already use, so their fstab/mount URLs don't change. Example shape (ReadyNAS ran
NFSv3, async):

```
/<data-path>   <clients>(rw,async,insecure,no_subtree_check,no_root_squash,crossmnt,anonuid=99,anongid=99)
```

```bash
apt-get install -y nfs-kernel-server rpcbind
# keep the ReadyNAS tuning:
#   /etc/default/nfs-kernel-server:
#     RPCNFSDCOUNT=12
#     RPCMOUNTDOPTS="--manage-gids --no-nfs-version 4"
#     RPCNFSDARGS="--no-nfs-version 4"      # ReadyNAS served NFSv3 only
exportfs -ra
systemctl enable --now nfs-kernel-server
showmount -e localhost          # should list the same exports clients expect
```

## 4. Samba — recreate the shares

Re-create the same share **names** pointing at the same paths. To keep existing **passwords**, copy the old
`/var/lib/samba/private/passdb.tdb` (+ `secrets.tdb`) into the new `/var/lib/samba/private/`; otherwise
`smbpasswd -a <user>` and clients re-enter the password once.

```ini
# /etc/samba/smb.conf (minimal equivalent of the ReadyNAS frontview config)
[global]
   workgroup = WORKGROUP
   server string = %h
   security = user
   map to guest = bad user
   client max protocol = SMB3
   # keep these ReadyNAS throughput settings:
   use sendfile = yes
   min receivefile size = 16384
   # Mac interop, if you have Mac/Time-Machine-ish clients:
   vfs objects = fruit streams_xattr
   fruit:encoding = native
   ea support = yes

[<share-name>]
   path = /<data-path>/<share>
   writeable = yes
   # valid users / guest ok as per your capture
```

```bash
apt-get install -y samba
# cp captured passdb.tdb secrets.tdb into /var/lib/samba/private/  (to migrate passwords)
systemctl enable --now smbd nmbd
pdbedit -L                      # confirm your users are present
```

## 5. Automation that referenced the old firmware

Anything that called ReadyNAS-specific paths must be updated. The classic one is a remote **shutdown**
script that ran `/frontview/bin/autopoweroff` — that binary won't exist on Debian; change it to
`systemctl poweroff` (or `/sbin/poweroff`). Because you preserved the SSH host key and authorized_keys
(steps 1), the SSH auth itself keeps working unchanged.

## 6. Wake-on-LAN — ⚠️ do not build client automation around this on the RN102

If you relied on WOL (e.g. a home-automation controller powering the NAS on): the MAC is unchanged
on Debian, so a `wakeonlan <mac>` call from your controller is harmless to send — but on the
**RN102 it will not power the box back on from a real poweroff.** This was chased to a hardware-level
proof; see **[12 — Wake-on-LAN on the RN102: why it can't work](12-wake-on-lan-rn102.md)** before
you build any automation on top of it. Practical alternative: keep the box always-on and spin the
disks down instead (see [07 — Optimizations → Disk spindown](07-optimizations.md)), or use a smart
plug / scheduled RTC wake if you need actual remote power-on.
(If you're on a *different* Armada board in this family and it turns out to work there — the PHY
standby rail may be wired differently — please report back; see doc 12's closing section.)

## 7. Verify each client

```bash
showmount -e <nas-ip>                 # NFS clients (e.g. media players) see the same exports
smbclient -L //<nas-ip> -N            # SMB shares present
ssh root@<nas-ip> 'hostname; uname -a'# host key did NOT change -> no client warning
```

Next: **[07 — Optimizations](07-optimizations.md)**.
