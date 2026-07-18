#!/usr/bin/env python3
# Catches the ~3-second U-Boot "Hit any key to stop autoboot" window automatically:
# opens the serial console, spams spaces until it sees a Marvell>> prompt, then stops
# sending and just streams the console live. Saves you from manually mashing the
# keyboard at exactly the right moment after powering the NAS on.
#
# Usage: sudo ./catch-autoboot.py [/dev/ttyUSBn]
# Requires: pyserial (pip install pyserial), and passwordless sudo (or run as root).
import serial, sys, time, os, subprocess, re

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
BAUD = 115200

if os.geteuid() != 0:
    os.execvp('sudo', ['sudo', '-A'] + sys.argv)

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
