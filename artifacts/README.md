# artifacts

Reference material only. **Device tree blobs (DTBs) are not vendored here** — get the one for your model
from bodhi's `linux-*-mvebu` kernel package (`linux-dtb-*.tar` → `dts/<your-model>.dtb`) or from the
rootfs (`/boot/dts/<your-model>.dtb`). See [../models/compatibility.md](../models/compatibility.md).

| File | What |
| --- | --- |
| `armada-370-netgear-rn102.dts` | The RN102 device-tree **source**, from mainline Linux (GPL-2.0) — included as a readable reference so you can see what the board exposes (g762 fan, isl12057 RTC, GPIO LEDs/keys, SATA, etc.). Your model's `.dts` is the equivalent file for its board. |

> Do **not** commit device-specific binaries here (NAND dumps, u-boot-env images) or any secrets (SSH host
> keys, Samba password DBs) — those are private to each machine.
