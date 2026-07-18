# Model compatibility & per-model specifics

All of these are **ARM ReadyNAS OS 6** boxes with Marvell **Armada 370 / XP / 385** SoCs, Marvell stock
U-Boot in NAND, a btrfs-on-mdadm data layout, and full mainline Linux support. The migration **method is
the same** for every one of them — only the **DTB name** (and cosmetic things like bay count / UART
location) differ.

| Model | SoC | Cores | RAM | Bays | NAND | Device tree (DTB) | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RN102 | Armada 370 (88F6710) | 1 × 1.2 GHz | 512 MB | 2 | 128 MB | `armada-370-netgear-rn102.dtb` | most documented |
| RN104 | Armada 370 | 1 × 1.2 GHz | 512 MB | 4 | 128 MB | `armada-370-netgear-rn104.dtb` | UKL's canonical guide target |
| RN2120 | Armada XP (MV78230) | 2 × 1.2 GHz | 2 GB | 4 | 128 MB | `armada-xp-netgear-rn2120.dtb` | dual-core, more RAM |
| RN202 | Armada 385 | 2 × 1.0 GHz | 2 GB | 2 | — | `armada-385-netgear-rn202.dtb` | newer gen |
| RN204 | Armada 385 | 2 × 1.4 GHz | 2 GB | 4 | — | `armada-385-netgear-rn204.dtb` | newer gen |
| RN212 / RN214 | Armada 385 | 2 × 1.4 GHz | 2 GB | 2 / 4 | — | `armada-385-netgear-rn21x.dtb` | newer gen |

> **How to confirm your model & SoC from the running ReadyNAS** (before you migrate):
> ```bash
> tr -d '\0' < /sys/firmware/devicetree/base/model     # e.g. "NETGEAR ReadyNAS 102"
> grep -i hardware /proc/cpuinfo                        # e.g. "Marvell Armada 370/XP"
> cat /proc/mtd                                         # the NAND/MTD layout (see below)
> ```
> The DTB you need is the one whose name matches this model string. bodhi's `linux-*-mvebu` kernel
> packages ship **all** of these DTBs inside `linux-dtb-*.tar` (under `dts/`), so you don't have to hunt
> for them individually — extract the one for your box.

## Shared NAND / MTD layout (Armada 370, RN102/RN104)

```
mtd0  u-boot        0x180000 @ 0x000000   (1.5 MB)
mtd1  u-boot-env    0x080000 @ 0x180000   (512 KB)   env: /dev/mtd1 offset 0 size 0x20000
mtd2  uImage        0x600000 @ 0x200000   (6 MB, kernel)
mtd3  minirootfs    0x400000 @ 0x800000   (4 MB)
mtd4  ubifs         0x7400000 @ 0xc00000  (116 MB, the stock ReadyNAS OS)
```

`mtdparts` string U-Boot uses:
`armada-nand:0x180000@0(u-boot),0x20000@0x180000(u-boot-env),0x600000@0x200000(uImage),0x400000@0x800000(minirootfs),-(ubifs)`

RN2120 (Armada XP) and the Armada 385 units have the same *kind* of layout with sizes that may differ —
always read your own `/proc/mtd` and record it.

## UART / serial header

All these boxes expose a **3.3 V UART** on a small header hidden behind a sticker on the rear, typically
near the Ethernet jack. Settings are **115200 8N1** on the Armada OS6 units. Pinout and wiring are in
[../docs/04-uart-and-uboot.md](../docs/04-uart-and-uboot.md).

## Not covered here (different method)

Older **sparc/PowerPC/Kirkwood** ReadyNAS (Duo v2, NV+ v2, Pro/Ultra x86, NVX, etc.) are **not** in scope —
they use different bootloaders/architectures. The community has separate guides for those (search the
Doozan forum and the Debian wiki `InstallingDebianOn/NETGEAR`). This repo targets the **Armada ARM OS6
family** specifically.
