#!/usr/bin/env python3
# Catches U-Boot's ~3s "Hit any key to stop autoboot" window automatically.
# Auto-detects the FTDI USB-TTL adapter's /dev/ttyUSBn (the device number shifts
# around after USB disconnects/reboots/hub churn - don't hardcode it).
# Usage: sudo ./rn102-break.py [/dev/ttyUSBn]   (explicit port overrides autodetect)
import serial, sys, time, os, subprocess, re
from serial.tools import list_ports

BAUD = 115200
FTDI_VID_PIDS = {(0x0403, 0x6001), (0x0403, 0x6015)}  # FT232R, FT231X etc.

if os.geteuid() != 0:
    os.execvp('sudo', ['sudo', '-A'] + sys.argv)

def find_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    candidates = [p for p in list_ports.comports() if (p.vid, p.pid) in FTDI_VID_PIDS]
    if not candidates:
        # fall back to any ttyUSB* if no known FTDI VID/PID matched
        candidates = [p for p in list_ports.comports() if 'ttyUSB' in p.device]
    if not candidates:
        sys.exit('No USB-TTL adapter found. Plug it in, or pass the port explicitly: '
                  './rn102-break.py /dev/ttyUSBn')
    if len(candidates) > 1:
        print(f'Multiple candidate ports found: {[p.device for p in candidates]}; '
              f'using {candidates[0].device}. Pass explicitly if this is wrong.', flush=True)
    return candidates[0].device

PORT = find_port()

subprocess.run(['fuser', '-k', PORT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.5)

ser = serial.Serial()
ser.port = PORT
ser.baudrate = BAUD
ser.timeout = 0.05
ser.exclusive = True
ser.rtscts = False
ser.dsrdtr = False
ser.xonxoff = False

for attempt in range(10):
    try:
        ser.open()
        ser.setDTR(False)
        time.sleep(0.1)
        ser.setDTR(True)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        break
    except serial.SerialException as e:
        print(f'Attempt {attempt+1}: {e}', flush=True)
        time.sleep(1)
else:
    sys.exit('Could not open serial port after 10 attempts')

print(f'Listening on {PORT}. Press the NAS front power button now.', flush=True)
buffer = ''

while True:
    try:
        data = ser.read(4096)
    except serial.SerialException:
        data = b''
    except Exception as e:
        print(f'Read error: {e}, reconnecting...', flush=True)
        time.sleep(1)
        for attempt in range(10):
            try:
                ser.close()
            except: pass
            try:
                ser = serial.Serial()
                ser.port = PORT
                ser.baudrate = BAUD
                ser.timeout = 0.05
                ser.exclusive = True
                ser.rtscts = False
                ser.dsrdtr = False
                ser.xonxoff = False
                ser.open()
                ser.setDTR(False)
                time.sleep(0.1)
                ser.setDTR(True)
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                break
            except serial.SerialException:
                time.sleep(1)
        else:
            sys.exit('Could not reconnect')
        continue

    if data:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        buffer += data.decode('utf-8', errors='replace')
        if re.search(r'[Mm]arvell\s*>>', buffer):
            print('\n--- Marvell prompt detected, stopped sending spaces ---', flush=True)
            # Stop writing spaces, keep reading
            while True:
                try:
                    data = ser.read(4096)
                except serial.SerialException:
                    data = b''
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()

    try:
        ser.write(b' ' * 32)
        ser.flush()
    except serial.SerialException:
        pass

    time.sleep(0.05)
