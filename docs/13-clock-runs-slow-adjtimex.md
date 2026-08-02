# 13 — The clock runs ~8% slow (and it looks like "my monitoring is broken")

**TL;DR:** On a mainline-Debian RN102 the system clock ran **8.35 % slow — about 2 hours lost per day**,
measured against a known-good host. That is ~167× beyond what `ntpd` can correct by slewing, so **NTP can
never hold this clock**: it detects the offset, blows past its panic threshold, and then refuses to step.
Fix it by correcting the *tick rate* with `adjtimex` (`tick=10910` instead of the default `10000`), applied
at boot **before** NTP starts. That took the residual to **~1 ppm**.

> **The reason this is worth its own page:** it does not present as a clock bug. Everything looks fine —
> `date` returns a plausible time, NTP is running, no errors anywhere. What you actually notice, days later,
> is that **your metrics/graphs are empty**, or cron jobs fire at odd times, or TLS certificates start
> failing to validate. We chased "why is Grafana showing no data" twice before measuring the clock itself.

---

## Symptoms

Any of these, with nothing obviously wrong in the logs:

- A monitoring/metrics push that "works" (HTTP 2xx, no errors) but the data **never appears** in the
  graphs. Time-series databases discard or hide samples whose timestamps fall outside a lookback window,
  and if you stamp samples with local time on a drifting box, they land in the past.
- `ntpq -pn` shows a large `offset` (seconds to minutes) that **never shrinks**.
- The clock is visibly wrong hours or days after you last set it, even though `ntpd`/`chrony` is running.
- `date` disagrees with a trusted host by a growing amount.

## Step 1 — Measure it properly

Do **not** measure with something like `time ssh nas date`. SSH round-trip jitter is on the order of
±0.2 %, which is the same order as a "small" clock error, so those measurements are noise-dominated and
will send you chasing ghosts. We wasted a cycle on exactly that.

**Method A — against a trusted host** (good for spotting gross errors). Use the *trusted* host as the
timebase, never the suspect box's own `sleep`:

```bash
# Run from a machine with a known-good clock
T0_REF=$(date +%s.%N);  T0_NAS=$(ssh nas 'date +%s.%N')
sleep 180
T1_REF=$(date +%s.%N);  T1_NAS=$(ssh nas 'date +%s.%N')
python3 -c "
r=($T1_NAS-$T0_NAS)/($T1_REF-$T0_REF)
print('ratio %.5f -> %.2f%% %s, %.1f min/day' % (r, abs(1-r)*100, 'SLOW' if r<1 else 'FAST', abs(1-r)*1440))"
```

**Method B — with `ntpdig`, precise to ~±0.01 s** (use this for calibration). Run **on the box**, with NTP
stopped so nothing else is touching the clock:

```bash
/etc/init.d/ntpsec stop                 # or: systemctl stop ntpsec / chronyd
ntpdig -S -t 5 fr.pool.ntp.org          # step to ~zero
sleep 2 ; O0=$(ntpdig -t 4 fr.pool.ntp.org | awk '{for(i=1;i<=NF;i++) if($i=="+/-"){print $(i-1);exit}}')
sleep 240
O1=$(ntpdig -t 4 fr.pool.ntp.org | awk '{for(i=1;i<=NF;i++) if($i=="+/-"){print $(i-1);exit}}')
awk -v a="$O0" -v b="$O1" 'BEGIN{d=b-a; printf "drift %.4f s / 240 s = %.0f ppm (%.2f min/day)\n", d, d/240*1e6, d/240*1440*60}'
```

> ⚠️ Parse `ntpdig`'s offset as **the field before the `+/-` token**, not by column number. Its output is
> `2026-08-02 21:42:20.224439 (+0200) +38.680688 +/- 0.010835 …` — field 3 is the **timezone** `(+0200)`,
> which looks numeric and silently evaluates to 0. That bug made our first safety-net script never fire.

## Step 2 — Rule out the ordinary causes

Before blaming the timer, confirm:

```bash
uptime                                    # heavy load can cause lost ticks - ours was idle (0.04)
cat /proc/mdstat                          # no RAID resync running
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq   # RN102: no cpufreq at all
cat /sys/devices/system/clocksource/clocksource0/available_clocksource
```

On the RN102 the only clocksource is `armada_370_xp_clocksource` (`dmesg` shows
`sched_clock: 32 bits at 19MHz`), there is **no cpufreq**, and the drift is identical whether the box is
idle or busy — so it is a straightforward rate miscalibration, not lost interrupts.

**Also fix your NTP servers while you're here.** The vendor/base image may ship hard-coded, long-dead
servers — ours had four US addresses of which **three never answered**. Replace with pools near you and
allow stepping at any time, not just on the daemon's first update:

```
pool fr.pool.ntp.org iburst
pool 0.debian.pool.ntp.org iburst
tinker panic 0
```

This is worth doing, but on its own it will **not** fix a rate error this large.

## Step 3 — The fix: correct the tick rate

`adjtimex` adjusts how many microseconds the kernel adds per timer tick. At `CONFIG_HZ=100` the default is
`10000`, and the kernel permits roughly ±10 % (`9000`–`11000`). We needed +9.1 %, which just fits.

If `adjtimex` isn't installed, **don't `apt install` it** if your rootfs lives on the same disks as your
data — that write will spin the array up. Call the syscall directly from Python's stdlib instead:

```python
#!/usr/bin/env python3
"""Read or set the kernel tick via adjtimex(2). Usage: nas-timex.py [new_tick]"""
import ctypes, struct, sys, os

SIZE = 128                       # struct timex, 32-bit ARM: all fields 4-byte aligned
OFF_MODES, OFF_FREQ, OFF_STATUS, OFF_TICK = 0, 8, 20, 44
ADJ_TICK = 0x4000
libc = ctypes.CDLL("libc.so.6", use_errno=True)

def call(modes=0, tick=None):
    buf = bytearray(SIZE)
    struct.pack_into("I", buf, OFF_MODES, modes)
    if tick is not None:
        struct.pack_into("i", buf, OFF_TICK, tick)
    cbuf = (ctypes.c_char * SIZE).from_buffer(buf)
    if libc.adjtimex(cbuf) < 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e))
    out = bytes(cbuf)
    return {"tick":   struct.unpack_from("i", out, OFF_TICK)[0],
            "freq":   struct.unpack_from("i", out, OFF_FREQ)[0],
            "status": struct.unpack_from("i", out, OFF_STATUS)[0]}

if len(sys.argv) == 1:
    print("READ:", call())
else:
    t = int(sys.argv[1])
    if not 9000 <= t <= 11000:
        sys.exit("tick %d outside kernel-permitted 9000..11000" % t)
    print("before:", call())
    print("after :", call(modes=ADJ_TICK, tick=t))
```

> **Validate the struct layout before writing anything**: run it with no arguments first. On a healthy
> `CONFIG_HZ=100` box a read must return `tick: 10000`. If it returns garbage, the offsets are wrong for
> your architecture (the layout above is for **32-bit** ARM; on 64-bit, `long` is 8 bytes and every offset
> after `modes` changes) — stop and fix that rather than writing a bogus tick.

### Calibrate iteratively

`tick` scales the clock rate linearly, so one iteration usually lands it:

```
tick_new = tick_current × (1 + measured_ppm / 1e6)
```

Our run, measuring with Method B each time:

| tick | residual drift |
| ---- | -------------- |
| 10000 (default) | 83,500 ppm — **120 min/day** |
| 10882 | 2,566 ppm — 3.69 min/day |
| **10910** | **~1 ppm — effectively zero** ✅ |

Anything under **500 ppm** is inside NTP's slew range, at which point `ntpd` maintains it normally.

> If your board needs **more than ±10 %**, `tick` alone cannot express it. You would need `ADJ_FREQUENCY`
> as well (±32,768 ppm on top), or — better — to fix the timer clock rate in the device tree.

## Step 4 — Make it survive reboot, before NTP starts

`adjtimex` settings are runtime-only. On a SysV-init box (bodhi's rootfs is sysvinit, **not** systemd):

```sh
# /etc/init.d/nas-clocktick     then: ln -s ../init.d/nas-clocktick /etc/rcS.d/S02nas-clocktick
#!/bin/sh
### BEGIN INIT INFO
# Provides:          nas-clocktick
# Required-Start:    $local_fs
# Default-Start:     S
# Short-Description: Correct this board's miscalibrated timer rate (must run before NTP)
### END INIT INFO
[ -r /usr/local/sbin/nas-timex.py ] || exit 0
case "$1" in
  start|"") python3 /usr/local/sbin/nas-timex.py 10910 >/dev/null 2>&1 \
              && echo "nas-clocktick: tick=10910 applied" \
              || echo "nas-clocktick: FAILED (clock will drift ~2h/day)" >&2 ;;
esac
exit 0
```

Order matters: `rcS.d/S02` puts it after `S01hwclock.sh` (which seeds the clock from the RTC) and before
`rc2.d/S02ntpsec`.

> ⚠️ **Test it by actually reverting the tick**, not by reading it back. Ours guarded on
> `[ -x /usr/local/sbin/nas-timex.py ]` for a file that had been `scp`'d and never `chmod +x`'d — so it
> **exited 0 silently**, left `tick` at 10000, and would have quietly undone the fix at the next reboot.
> Reading the tick afterwards "confirmed" 10910 only because it was still set from the manual run. Prove it:
>
> ```bash
> python3 /usr/local/sbin/nas-timex.py 10000   # revert
> /etc/init.d/nas-clocktick start              # must print the success line
> python3 /usr/local/sbin/nas-timex.py         # must now read 10910
> ```

A cheap backstop, in case the tick is ever lost or the rate shifts — step only on a large offset, so NTP
stays in charge normally (`/etc/cron.hourly/`):

```sh
OFF=$(ntpdig -t 4 fr.pool.ntp.org 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="+/-"){print $(i-1);exit}}')
[ -z "$OFF" ] && exit 0
[ "$(awk -v o="$OFF" 'BEGIN{o=o<0?-o:o; print (o>=5)?1:0}')" = "1" ] || exit 0
/etc/init.d/ntpsec stop >/dev/null 2>&1
ntpdig -S -t 5 fr.pool.ntp.org >/dev/null 2>&1
hwclock --systohc >/dev/null 2>&1
/etc/init.d/ntpsec start >/dev/null 2>&1
```

## Caveats

- **This is software compensation, not a real fix.** The underlying defect is the timer clock rate the
  kernel derives for this board. The proper fix belongs in the DTS/clock driver.
- **The tick value is specific to your kernel build.** Recalibrate (Step 1 Method B) after adopting a new
  kernel — see [10 — Adopting newer kernels](10-kernel-upgrades.md).
- **We have confirmed this on one RN102** with a custom `7.0.11-mvebu-370xp-tld-1` build. Whether it
  affects all RN102s, other kernels, or other boards in the family is **unverified** — measure yours before
  applying a number from this page. If you test another board, the drift figure is worth reporting back.
- Run `hwclock --systohc` after correcting, so the RTC carries the right time into the next boot.
