# 12 — Wake-on-LAN on the RN102: why it can't work (and how far we chased it)

**TL;DR:** On a mainline-Debian RN102 you **cannot** wake the box from a real power-off with a WOL
magic packet. It's a **hardware/board-power limitation**, not a config or driver bug. `gpio-poweroff`
removes power from the Ethernet PHY, so nothing is left powered to hear the packet. Netgear's stock
"WOL mode" was a *different low-power state* (≈1 W) that the mainline kernel does not enter. This page
documents the full investigation so you don't repeat a multi-day effort — and so anyone with a
**different board in the family (RN104/RN2120)** has the exact mechanism to test.

> If you found this because your box "won't wake" — stop here for WOL, and instead keep it always-on
> with disks spun down (see [07 — Optimizations → Disk spindown](07-optimizations.md)). If it
> **reboots itself every ~4 minutes**, that's the *watchdog*, not WOL — see
> [07 → Hardware watchdog](07-optimizations.md#hardware-watchdog--feed-it-or-the-box-reboots-every-4-minutes).

## The hardware facts

- SoC: Marvell **Armada 370**. PHY: Marvell **88E1318S** on RGMII. The MAC (`mvneta`) does **not**
  implement WOL — WOL is a **PHY** function.
- Mainline runs the PHY as `irq=POLL` (dmesg: `PHY [...mdio-mii:00] driver [Marvell 88E1318S]
  (irq=POLL)`). **No PHY interrupt line is described in the device tree** — the PHY INTn pin is not
  wired to a SoC GPIO IRQ. So a magic packet cannot raise a CPU interrupt; the PHY's INTn goes to the
  **board power circuit** instead (that's the vendor wake path).
- Netgear datasheet lists **three** power states: ~31 W running, **~1 W "WOL mode"**, **210 mW**
  power-off. The 1 W state keeps the PHY alive on a standby rail so it can watch for the packet; the
  210 mW state does not. Mainline's `gpio-poweroff` lands in the **210 mW** state.
- The mainline and vendor **device trees are functionally identical** for ethernet/PHY/gpio-poweroff.
  There is no extra "keep the PHY rail alive" node to port.

## What the stock firmware actually did (from the GPL sources)

Netgear's userspace does nothing special — `frontview/bin/autopoweroff` → `rnutil rn_shutdown` →
plain `/sbin/poweroff`. The magic is one **kernel patch** in
`drivers/net/ethernet/marvell/mvmdio.c`: a Netgear-added **`orion_mdio_shutdown()`** registered as the
MDIO platform driver's `.shutdown`. At poweroff, if WOL is armed, it programs the 88E1318S to route
the magic-packet event to the PHY **INTn pin** (paged registers: page-select = reg `0x16`; WOL ctrl =
page `0x11` reg `0x10`; LED[2]/INTn = page `3` reg `0x12`). The annotated vendor function is in
[`../scripts/orion_mdio_shutdown.vendor.c`](../scripts/orion_mdio_shutdown.vendor.c).

## What we tried (all failed to wake the box)

1. **`ethtool -s eth0 wol g` + shutdown-script ordering** (NETDOWN, ifdown ordering). The PHY WOL
   registers *do* get armed (verified by reading them back over MDIO: magic-match bit set, correct
   MAC latched). No wake.
2. **Suspend-to-RAM (`s2idle`)** instead of poweroff. Here the PHY *stays* powered (its LEDs blink),
   but nothing wakes s2idle — there is no PHY IRQ line, and even the **power button** can't wake it
   (the `gpio-keys` node has no `wakeup-source`). ⚠️ This can leave the box needing an AC unplug to
   recover — don't leave it suspended unattended.
3. **Userspace replica** of `orion_mdio_shutdown` run as the last thing before `halt`. Fails: the
   kernel's own `device_shutdown()` runs the PHY driver's shutdown *after* our script and either
   disables PHY interrupts or `BMCR_PDOWN`s the PHY, wiping the arming. Userspace can't win that race.
4. **The real fix — a custom kernel** with `orion_mdio_shutdown()` compiled into the built-in `mvmdio`
   ([`../scripts/mvmdio-wol-shutdown.patch`](../scripts/mvmdio-wol-shutdown.patch)). This runs at the
   *exact* vendor point (mdio driver `.shutdown`, during `device_shutdown`, mdio clock still live, PHY
   child already shut down). Serial **confirmed it fired** (`orion-mdio: RN102 PHY WOL wake pin armed`,
   printed right after `Stopping disk`, after the full register sequence completed). **Still no wake,
   and every LED dark when off.**

## Conclusion

A faithful, in-kernel reproduction of Netgear's exact WOL-arm, executing at exactly the right moment,
does not wake the RN102 — because `gpio-poweroff` has already removed power from the PHY. The 88E1318S
magic-packet detector needs the ~1 W standby rail that the mainline poweroff path doesn't provide.
**On-demand remote power-on is not achievable on the RN102 from mainline Linux.**

Alternatives:
- **Always-on + disk spindown** (recommended) — [07 → Disk spindown](07-optimizations.md).
- **Scheduled** power-on via the **RTC alarm** (`rtcwake` / `/sys/class/rtc/rtc0/wakealarm`) — survives
  poweroff on the RTC's own power. Time-based only, not on-demand.
- An external **smart plug** to AC-cycle the box if a controller must power it on remotely.

## For RN104 / RN2120 hackers

The mechanism above (INTn → board power latch) is the same code Netgear shipped for the whole family.
If your board keeps a PHY standby rail through `gpio-poweroff` (check: is any RJ45/switch-port LED lit
when the box is "off"?), the `mvmdio` patch may actually wake it. Build it in (`CONFIG_MVMDIO=y`),
`ethtool -s eth0 wol g` at boot, and test. Report back — the RN102 specifically does not keep that rail.
