# 04 — UART wiring & booting Debian from USB

The serial console is the only step you can't automate. Once it's up, everything after is keyboard-driven
and non-destructive.

## 1. Find & wire the UART header

There's a **small sticker on the rear**, usually near the Ethernet jack — peel it to reveal a **4-pin
3.3 V header**. Typical order **top → bottom**:

```
Pin 1  VCC (3.3V)  ->  DO NOT CONNECT   (the NAS powers itself; VCC is a logic reference only)
Pin 2  TX          ->  adapter RX
Pin 3  RX          ->  adapter TX
Pin 4  GND         ->  adapter GND
```

**Rules that keep the board alive:**

- Adapter switch on **3.3 V**. Never 5 V.
- **Leave VCC unconnected.** Only TX, RX, GND.
- TX↔RX are **crossed** (adapter TX → NAS RX, and vice-versa). If you see **no or garbled output, swap
  TX/RX** and retry — a wrong guess here harms nothing.

> Pin order can vary slightly between board revisions; if unsure, identify **GND** first (continuity to
> chassis ground) and start from there. The RN102/RN104 pinout above is the widely-documented one.

## 2. Open the serial console

On the build box, with the NAS still **powered off**:

```bash
sudo screen /dev/ttyUSB0 115200        # 115200 8N1, no flow control.  (exit screen: Ctrl-a then k)
# minicom -D /dev/ttyUSB0 -b 115200    # alternative
```

Plug the **prepared USB stick** into the NAS, then power it on. You should see the Marvell **BootROM**
banner and U-Boot counting down "**Hit any key to stop autoboot**". Press a key to land at the
`Marvell>>` prompt.

> **Tip — automate the catch.** The countdown is only ~3 seconds, easy to miss by manually reaching for a
> key at the right moment. **[`scripts/catch-autoboot.py`](../scripts/catch-autoboot.py)** opens the serial
> port, spams spaces until it sees `Marvell>>`, then stops and streams the console live:
> ```bash
> pip install pyserial   # if not already present
> sudo ./scripts/catch-autoboot.py          # or: sudo ./scripts/catch-autoboot.py /dev/ttyUSB1
> # -> "Listening on /dev/ttyUSB0. Press the NAS front power button now."
> ```
> Power on the NAS after it says "Listening...". Once it prints "Marvell prompt detected, stopped sending
> spaces", `Ctrl-C` it and reattach with `screen`/`minicom` for interactive use — only one program can hold
> the serial port at a time.

## 3. Save the current environment (so you can always get back)

```
printenv
```

Copy the whole dump into your notes. The important stock line is the NAND boot command, typically:

```
bootcmd=nand read 0x2000000 0x200000 0x400000; nand read 0x3000000 0x800000 0x400000; bootm 0x2000000 0x3000000 0x1000000
```

Keep it — it's how you restore stock booting later.

## 4. Boot Debian from USB (non-destructive — don't `saveenv` yet)

Paste this set of environment variables. It boots from the USB stick's `/boot/uImage` + `/boot/uInitrd`
and **does not overwrite the stock `bootcmd`** unless you `saveenv` (we don't, on the first try — so any
mistake is undone by a power-cycle):

```
setenv usb_set_bootargs 'setenv bootargs console=ttyS0,115200 root=LABEL=rootfs rootdelay=10 earlyprintk=serial'
setenv load_uimage 'ext2load usb 0:1 0x2000000 /boot/uImage'
setenv load_uinitrd 'ext2load usb 0:1 0x3000000 /boot/uInitrd'
setenv usb_boot 'run load_uimage; if run load_uinitrd; then bootm 0x2000000 0x3000000; else bootm 0x2000000; fi'
setenv usb_bootcmd 'run usb_set_bootargs; run usb_boot'
setenv fdt_skip_update yes
usb start
run usb_bootcmd
```

- Load addresses `0x2000000` / `0x3000000` are correct for any Armada 37x/38x/XP with Marvell stock U-Boot.
- If `usb start` doesn't detect the stick: try the other USB port, re-seat it, or use a different (USB 2.0)
  stick. Some boxes are picky about USB 3 sticks in U-Boot.
- If it hangs after `Starting kernel...`: usually a **wrong DTB** for the model, or a kernel/module
  mismatch. Recheck the DTB name ([03](03-build-usb-rootfs.md) step 3) against
  [../models/compatibility.md](../models/compatibility.md).

You should see the kernel boot and Debian come up on the serial console.

## 5. Make it permanent — LATER, not now

Only after Debian boots cleanly **and** you've verified your data ([05](05-first-boot-and-raid.md)), persist
the USB boot so the box comes up on its own:

```
# re-enter the env block above, then:
setenv bootcmd 'usb start; run usb_bootcmd; usb stop; reset'
saveenv
reset
```

This writes **only** the 512 KB env partition — it does **not** touch the kernel NAND and does **not**
invoke the buggy `flash-kernel` NAND path (see [08](08-rollback-and-recovery.md)). Keep the USB stick
permanently installed.

Next: **[05 — First boot & RAID](05-first-boot-and-raid.md)**.

---

*Sources: Uwe Kleine-König "Installing Debian Jessie on a Netgear ReadyNAS 104"; bodhi (Doozan) "Boot MVEBU
rootfs with stock u-boot".*
