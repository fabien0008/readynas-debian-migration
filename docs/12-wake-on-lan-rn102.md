# 12 — Wake-on-LAN on the RN102: it works (one PHY register was the culprit)

**TL;DR:** WOL from a real power-off **works** on a mainline-Debian RN102. An earlier version of this
page said it was a hardware limit. That was wrong. The cause is one register of the Marvell
88E1318S PHY: the mainline driver sets its **LED function control** register (page 3, reg `0x10`) to
`0x0030`, while U-Boot sets `0x083f` and Netgear's kernel never touches it. LED[2] of that PHY is the
pin that carries the wake signal (INTn). With `0x0030` it becomes a "link" LED, and the board ignores
magic packets. One device-tree property puts the U-Boot value back:

```dts
&mdio {
	phy0: ethernet-phy@0 { /* Marvell 88E1318 */
		reg = <0>;
		marvell,reg-init = <3 0x10 0 0x083f>;
	};
};
```

Measured on a plug meter, box off with WOL armed: **0.2 W** without the property (no wake), **0.5 W**
with it (wakes about one second after the magic packet; Debian answers ping about 85 s later). The
Netgear 4.4 kernel also draws 0.5 W in that state.

> If your box **reboots itself every ~4 minutes**, that's the *watchdog*, not WOL — see
> [07 → Hardware watchdog](07-optimizations.md#hardware-watchdog-feed-it-or-the-box-reboots-every-4-minutes).

## What you need (all three were in place in every successful test)

1. **The shutdown hook in `mvmdio`** that arms the PHY at power-off, as Netgear's kernel does:
   [`../scripts/mvmdio-wol-shutdown.patch`](../scripts/mvmdio-wol-shutdown.patch), plus
   [`../scripts/mvmdio-wol-shutdown-v2.patch`](../scripts/mvmdio-wol-shutdown-v2.patch) on top of it
   (it resets the PHY first, then programs WOL control `0x5580` and LED[2] as INTn, and reads every
   register back to the console). Build it in (`CONFIG_MVMDIO=y`).
2. **The device-tree property above.** As a kernel source patch:
   [`../scripts/rn102-dts-phy-led-wol.patch`](../scripts/rn102-dts-phy-led-wol.patch). It needs
   `CONFIG_MARVELL_PHY=y` and `CONFIG_OF_MDIO=y` (both on in the usual 370xp configs).
   `marvell_config_init()` applies `marvell,reg-init` right after its own LED default, so the
   register ends at `0x083f`.
3. **`ethtool -s eth0 wol g` at every boot** (rc.local or an init script). Check with
   `ethtool eth0 | grep Wake-on` → `Wake-on: g`.

Not tested: the property **without** the hook of step 1. If you try it, report back.

## After a power cut: WOL is gone, the RTC alarm is not

WOL is armed by the kernel at shutdown. After a power cut nothing armed it: when the power comes back
the box stays off, draws 0.2 W, and ignores magic packets (tested). The RTC (ISL12057, battery-backed)
keeps its alarm through the cut and can power the board on (tested: alarm set, clean poweroff, AC
unplugged for ~10 s, the box started on its own at the alarm time). So set the alarm at every halt,
for example to the next 03:00, from a runlevel-0 script:

```sh
t=$(date -d "today 03:00" +%s); [ "$t" -le "$(date +%s)" ] && t=$(date -d "tomorrow 03:00" +%s)
echo 0 > /sys/class/rtc/rtc0/wakealarm; echo "$t" > /sys/class/rtc/rtc0/wakealarm
```

The cost is one short boot per night when there was no power cut (power the box off again when it is
idle); the gain is that it comes back on its own after a cut, by 03:00 at the latest.

## Adding the property to an existing NAND install (no kernel rebuild)

On these boxes the DTB is **appended to the zImage** inside the `uImage` in `mtd2`
([09](09-rn102-rn104-special-kernel.md), [10](10-kernel-upgrades.md)). So you only rebuild that
container, with the same zImage:

```bash
# 0. back up the kernel partition, twice, and keep the copy off the NAS
dd if=/dev/mtd2 of=mtd2-before.bin bs=128k
nanddump -f mtd2-before-nanddump.bin /dev/mtd2 && cmp mtd2-before.bin mtd2-before-nanddump.bin

# 1. split the current image: uImage header (64 B) + zImage + appended DTB
#    (zImage length = end field at offset 0x2c of the zImage header; the DTB follows it)
# 2. add the property to the DTB
fdtput -t u old.dtb /soc/internal-regs/mdio@72004/ethernet-phy@0 marvell,reg-init 3 16 0 2111
#    fdtput -t u reads DECIMAL: 16 = 0x10, 2111 = 0x083f. Check:
fdtget -t x new.dtb /soc/internal-regs/mdio@72004/ethernet-phy@0 marvell,reg-init   # 3 10 0 83f
# 3. same recipe as the original image
cat zImage new.dtb > zImage.fdt
mkimage -A arm -O linux -T kernel -C none -a 0x00008000 -e 0x00008000 -n "<name>" -d zImage.fdt uImage-new
```

Before flashing, boot that exact image from RAM once (U-Boot `tftpboot 0x2000000 uImage-new`, the
initrd from NAND as in your `bootcmd`, then `bootm`; no `saveenv`), check that
`/sys/firmware/devicetree/base/soc/internal-regs/mdio@72004/ethernet-phy@0/marvell,reg-init` exists,
power off and send a magic packet. Then flash it the way doc [10](10-kernel-upgrades.md) does
(`flash_erase /dev/mtd2 0 0 && nandwrite -p /dev/mtd2 uImage-new`), read it back with `nanddump` and
compare **before** rebooting.

## How it was found (2026-10-18/19)

The earlier conclusion ("`gpio-poweroff` cuts the PHY's power") came from a hook that ran and a box
that never woke, with every LED dark. What changed the picture:

- **A control run on the Netgear 4.4 kernel** (booted from RAM over TFTP, no disk access, WOL armed)
  drew 0.5 W when off and **woke** on the magic packet. Same board, so not a hardware limit.
- **Every register the two shutdown paths write was compared** (Ghidra/REA on the stock kernel, the
  decompressed build, and the sources). The PHY end state matched, apart from one interrupt-mask value.
  Changing that value alone (a one-instruction patch, RAM-only test): still 0.2 W, no wake.
- **The rest of the PHY driver was then compared.** The stock `m88e1318_set_wol` is upstream 4.4.218
  unchanged, and the device trees and the `gpio-poweroff` timing are the same. The difference:
  upstream 4.4 writes `0x0030` to the LED register in `m88e1121_config_aneg()`, and **Netgear removed
  that write**. Mainline 7.0 writes it again in `marvell_config_led()`. A PHY soft reset does not
  clear page 3, so the value survives to power-off.
- **U-Boot leaves `0x083f`** (read at the prompt with `phyWrite 0 16 3; phyRead 0 10`; this U-Boot has
  `phyRead`/`phyWrite`, not `mii`, numbers in hex). LED[2] = `0x8` = forced off.
- **Test:** the same kernel with `marvell_config_led()` patched to return at once → 0.5 W, woke, twice.
  The unchanged kernel with only the DT property → 0.5 W, woke. Then flashed, and verified after a
  normal Debian `poweroff`.

Why LED[2] in link mode stops the wake is inferred, not measured: there is no schematic here. The
measured facts are the power draw and the wake.

## For RN104 / RN2120 hackers

Same PHY family and the same Netgear shutdown code. If WOL does not work on your box, read the LED
function register at the U-Boot prompt (as above), compare it with the value your kernel leaves
(`marvell_config_led()` default for the 88E1318S family is `0x0030`), and try `marvell,reg-init` with
your U-Boot value. Please report back with your board and the values.
