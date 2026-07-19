# 07 — Optimizations: carry over Netgear's tunings + close the resilience gaps

These are the tunings the **stock ReadyNAS firmware** applied to this hardware, recovered by inspecting a
live unit, plus the things ReadyNAS did *inside its closed `readynasd` daemon* that a plain Debian install
does **not** inherit. Apply them **after** the base system and clients work.

> Values below are the ReadyNAS defaults observed on an **Armada 370 / 512 MB** box (RN102). On the
> Armada XP / 385 units (RN2120, RN2xx — 2 GB, dual-core) you can be more generous with buffers and worry
> less about RAM pressure. Treat them as sensible starting points, then measure.

## Speed stack — network + I/O + VM

Netgear's `/etc/sysctl.conf` and live values worth keeping. Drop into `/etc/sysctl.d/60-nas.conf`:

```ini
# --- Network: sized for gigabit + the mvneta NIC ---
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_min_tso_segs = 22        # mvneta-specific TSO tuning the firmware ships
# --- VM: tuned for low RAM (relax on the 2 GB models) ---
vm.swappiness = 1                     # avoid swapping on a tiny-RAM box
vm.min_free_kbytes = 16384            # reserve; avoids allocation deadlock under load
vm.dirty_background_ratio = 10
vm.dirty_ratio = 20
fs.inotify.max_user_watches = 99200   # for Samba/inotify-heavy clients
# --- RAID: raise the resync floor so a rebuild runs fast, not at the 1 MB/s default ---
dev.raid.speed_limit_min = 30000
```

Apply: `sysctl --system`.

**I/O scheduler**: ReadyNAS used `cfq` (removed in kernel 6.x). Use **`mq-deadline`** for rotational disks
(or `bfq` for interactivity under mixed load). Media streaming likes a larger read-ahead than the
128 KB default:

```bash
# /etc/udev/rules.d/60-nas-io.rules
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", \
  ATTR{queue/scheduler}="mq-deadline", ATTR{queue/read_ahead_kb}="512"
```

**CPU frequency**: the Armada 370 has **no cpufreq scaling** (fixed 1.2 GHz) — there is no governor to
tune; don't chase it. (Armada XP/385 likewise run fixed here.)

**Network offloads**: the firmware had TSO/GSO/GRO/scatter-gather/tx-checksum all **on**; `mvneta` on
Debian enables these by default — verify with `ethtool -k eth0` and only force any that regress.

**btrfs mount options**: ReadyNAS used `noatime,nodiratime,space_cache`. On kernel 6.x upgrade to
**`space_cache=v2`** (see [05](05-first-boot-and-raid.md)). Consider `commit=120` to batch writes. **Do
not** blanket-enable `compress` — media is incompressible and this CPU has no spare cycles; if anything,
compress only a text-heavy subvolume with `compress=zstd:1`.

**NFS/SMB**: keep `async` + `RPCNFSDCOUNT=12` + NFSv3, and Samba `use sendfile = yes` /
`min receivefile size = 16384` — all from the ReadyNAS config, all matter on this CPU (see [06](06-services-and-clients.md)).

## Storage resilience — the biggest wins (recreate what `readynasd` did)

The stock firmware ran SMART self-tests, periodic btrfs scrubs, and emailed you on a degrading disk —
**from its closed daemon.** A plain Debian install has **none** of this. This is the single most valuable
section: it's the early-warning that catches a dying disk *before* it takes the array down.

**1. SMART monitoring + alerts:**
```bash
apt-get install -y smartmontools
# /etc/smartd.conf
DEVICESCAN -a -o on -S on -n standby,q \
  -s (S/../.././02|L/../../6/03) \      # short test daily 02:00, long test Saturdays 03:00
  -W 4,45,55 \                          # track temp; warn 45°C / alarm 55°C
  -m you@example.com -M exec /usr/share/smartmontools/smartd-runner
systemctl enable --now smartd
```

**2. Monthly btrfs scrub** (detects/repairs bit-rot on the mirror):
```ini
# /etc/systemd/system/btrfs-scrub.service   (Type=oneshot)
#   ExecStart=/usr/bin/btrfs scrub start -B -c idle /<data-mount>
# /etc/systemd/system/btrfs-scrub.timer     (OnCalendar=monthly, Persistent=true)
```
```bash
systemctl enable --now btrfs-scrub.timer
```

**3. mdadm array monitoring** (email when a member fails/degrades):
```bash
# /etc/mdadm/mdadm.conf
MAILADDR you@example.com
# plus the ARRAY lines from: mdadm --detail --scan
systemctl enable --now mdmonitor
# Debian's /etc/cron.d/mdadm already runs a monthly `checkarray` parity check — keep it.
```

> **When you replace a failed disk, buy CMR, not SMR.** SMR drives (e.g. some consumer "Red" models) fail
> or crawl during RAID rebuilds — a classic ReadyNAS-era foot-gun. This is independent of Debian but worth
> repeating.

## Hardware: fan, LEDs, RTC, watchdog, WOL, power button

Mainline has the drivers (`g762`, `rtc-isl12057`, `armada_thermal`, `gpio-keys`, `leds-gpio`, `mvneta`);
you just add policy. Netgear's exact fan *curve* lives compiled in `readynasd` (not a copyable file) — the
mechanism below reproduces its behaviour.

### Fan (g762) — do not skip this

The firmware runs the g762 in **closed-loop mode** (`pwm1_enable=2`, a target RPM), regulated by the CPU
temperature. If Debian leaves the g762 unconfigured the fan may sit off or run flat out. Minimum safe
replication + a simple curve:

```bash
apt-get install -y lm-sensors fancontrol
# quick & safe (hardware closed-loop at a fixed RPM at boot) — /etc/systemd/system/nas-fan.service:
#   Type=oneshot, RemainAfterExit=yes
#   ExecStart=/bin/sh -c 'echo 2 > /sys/class/hwmon/hwmon0/pwm1_enable; echo 1600 > /sys/class/hwmon/hwmon0/fan1_target'
# better: a temp->RPM curve via `pwmconfig`/`fancontrol` reading armada_thermal (CPU temp).
#   e.g. <50°C:1200  50-60:1600  60-70:2200  >70:max, polled every 30 s.
systemctl enable --now nas-fan.service
```
**Watch `sensors` under real load for the first day.**

### Front-panel LEDs

Give at-a-glance status (`/sys/class/leds/<model>:blue:{pwr,sata1,sata2,...}`):

```bash
# power LED solid:      echo default-on   > /sys/class/leds/<model>:blue:pwr/trigger
# per-bay disk activity:echo disk-activity> /sys/class/leds/<model>:blue:sata1/trigger
```

### RTC

`rtc-isl12057` keeps time across reboots/internet outages. Ensure the module is present and
`systemd-timesyncd` (or chrony) syncs when online; `hwclock --systohc` on shutdown.

### Hardware watchdog — ⚠️ **feed it or the box reboots every ~4 minutes**

The `orion_wdt` (RN102/RN104) is **started at boot** with a ~229 s timeout and **does not support
magic-close** — i.e. once running, nothing short of feeding it will stop it. If no userspace process
pets `/dev/watchdog`, the board **hard-reboots roughly every 229 s, forever.** This presents as a
box that "reboots itself every few minutes" for no obvious reason — an easy multi-hour trap. Confirm
with `wdctl` (watch `Timeleft` count down).

- **systemd as PID 1:** it feeds the watchdog for you — just set the timeouts:
  ```ini
  # /etc/systemd/system.conf
  RuntimeWatchdogSec=30
  RebootWatchdogSec=10min
  ```
- **SysVinit / no systemd** (e.g. the bodhi rootfs many of these builds use): **you must run a
  feeder yourself**, or you get the reboot loop. `busybox` has one built in:
  ```sh
  # /etc/init.d/nas-watchdog  (enable EARLY, e.g. rcS S01, so it starts within 229 s of boot)
  #   start)  [ -e /dev/watchdog ] && /bin/busybox watchdog -t 20 -T 220 /dev/watchdog ;;
  # -t 20 = pet every 20 s, -T 220 = hardware timeout 220 s. A genuine hang (feeder dead)
  # still triggers the intended safety reboot after 220 s.
  ```
  Verify it survives: `uptime` must climb past ~4 min, and `pgrep -f 'busybox watchdog'` alive.

Confirm `/dev/watchdog` exists (`modprobe orion_wdt` if built as a module — but prefer `=y`, see
[10 — kernel upgrades](10-kernel-upgrades.md)).

### Wake-on-LAN — ⚠️ does **not** work from full power-off on the RN102 (hardware limit)

`ethtool -s eth0 wol g` succeeds and the NIC reports `Supports Wake-on: g` / `Wake-on: g`, so it
*looks* like the stock firmware. **But a magic packet will not power an RN102 back on from a real
poweroff.** This was chased to the end (custom kernel carrying Netgear's own PHY-arming code, proven
firing at the exact right moment) — the board's `gpio-poweroff` removes power from the Ethernet PHY,
so there is no powered chip left to hear the packet. Netgear's "WOL mode" (≈1 W in their datasheet,
vs 210 mW true-off) was a *different low-power state* that mainline can't reach. Full write-up and
proof: **[12 — Wake-on-LAN on the RN102: why it can't work](12-wake-on-lan-rn102.md)**.

Practical guidance:
- Do **not** rely on WOL to power these boxes on. Keep the NAS **always-on** (idle draw is a few
  watts with disks spun down — see *Disk spindown* below) — this is usually what people actually
  want anyway (instant availability + disks asleep).
- If you need scheduled power-on, the **RTC alarm** works from poweroff (`rtcwake`/`/sys/class/rtc/
  rtc0/wakealarm`) — time-based, not on-demand.
- Still set `ethtool -s eth0 wol g` on boot — harmless, and it *may* help on other models in this
  family whose board wires the PHY INTn differently (unverified; only the RN102 was tested here).

### Power button

`gpio-keys` emits `KEY_POWER`; **systemd-logind handles it out of the box** (`HandlePowerKey=poweroff`) —
the physical button does a graceful shutdown with no configuration.

## Flash / USB-boot wear reduction

The OS now lives on a USB stick — reduce needless writes:

```ini
# /etc/systemd/journald.conf
[Journal]
Storage=volatile        # or Storage=auto + RuntimeMaxUse=32M ; log to RAM/tmpfs
RuntimeMaxUse=32M
```
- Mount `/tmp` (and optionally `/var/log`) as `tmpfs`; keep `noatime` on the USB root.
- **Keep a `dd`-cloned spare USB stick** — it's the USB-boot equivalent of a RAID mirror; a failed boot
  stick becomes a 2-minute swap instead of an outage.

**Memory (low-RAM models)**: add zram so the 512 MB boxes tolerate bursts:
```bash
apt-get install -y zram-tools    # /etc/default/zramswap:  PERCENT=150  ALGO=zstd
```

**Disk spindown — for "disks spin only for real client I/O"**: since WOL can't power the box off/on
(above), the way to save the disks is to keep the NAS always-on but let the **data disks sleep** when
no client is using them. The catch on a **USB-free / root-on-disk** build (see [09](09-rn102-rn104-special-kernel.md)):
the OS root is on the *same* disks as the data, so any OS write spins them up. Make the OS
write-silent at idle, then let the drives park themselves:

```bash
# 1) drive-internal idle timer: park after 20 min of no I/O (persist in rc.local / a boot unit)
hdparm -S 240 /dev/sda /dev/sdb          # 240 = 20 min; some NAS drives honour -S even without APM

# 2) keep OS writes OFF the disks so they don't get woken:
#    - /tmp and /var/log -> tmpfs (RAM). For /var/log, restore a dir skeleton at boot AFTER the
#      tmpfs is mounted (an rcS script ordered after `mountall`), or services lose their log dirs.
#    - journald Storage=volatile ; noatime on root (already set by the fstab in 05).
```
Verify: `hdparm -C /dev/sd?` shows `standby` when idle; `awk '$3~/^sd/{print $8}' /proc/diskstats`
(write field) stays flat at idle. **Gotchas:** keep `smartd` on `-n standby` (skips sleeping disks);
don't enable a node_exporter/collectd **SMART/hddtemp** collector (it reads the disk and wakes it);
and note your *own* `ssh`+`find`/`df` probing resets the idle timer, so test spindown **hands-off**.
Trade-off: aggressive spindown adds first-access latency (possible media-playback stutter) and
start/stop cycles — 20 min is a reasonable balance.

## Apply order

1. Sysctl → re-check `ethtool -k`, throughput.
2. **Storage resilience early** — smartd + monthly scrub + mdmonitor + `space_cache=v2`.
3. Fan service → watch temps a day.
4. WOL + watchdog + LEDs.
5. Flash-wear (journald volatile) + clone a spare stick.
6. zram on low-RAM models.

Next: **[08 — Rollback & recovery](08-rollback-and-recovery.md)**.
