# scripts

| Script | What |
| --- | --- |
| [`catch-autoboot.py`](catch-autoboot.py) | Automates catching U-Boot's ~3-second "Hit any key to stop autoboot" window — opens the serial port, spams spaces until it sees `Marvell>>`, then stops and streams the console live. See [../docs/04-uart-and-uboot.md](../docs/04-uart-and-uboot.md). |

Requires `pyserial` (`pip install pyserial`) and root (or passwordless `sudo`) to open the serial device.
