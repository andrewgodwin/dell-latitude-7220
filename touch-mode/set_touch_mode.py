#!/usr/bin/env python3
"""
Set the touch mode (Finger / Glove / Water-Rain) on an EETI/eGalax
"Orion" family PCAP touch controller (USB VID:PID 0eef:c003 -- the
eGalaxTouch P80H84, as fitted to the Dell Latitude 7220 Rugged Extreme
Tablet) over Linux hidraw.

No vendor Linux driver or sysfs knob exists for this; the mode lives in
a proprietary HID vendor command. See README.md in this directory for
how this protocol was derived and what is/isn't verified.

Usage:
    set_touch_mode.py {finger|glove|water} [--device /dev/hidrawN] [-v]

The mode is stored in the touch controller's own firmware/EEPROM, not
on the host -- it survives reboots and even booting a different OS, so
this only needs to be run once per desired change, not on every boot.
"""
import argparse
import glob
import os
import sys

VENDOR_ID = 0x0EEF
PRODUCT_ID = 0xC003

MODES = {
    "water": 0x00,   # tolerates water droplets / rain on the panel
    "finger": 0x01,  # normal finger + passive stylus (the "off"/default state)
    "stylus": 0x01,  # alias
    "glove": 0x02,   # detects touches through gloves
}


def find_device() -> str:
    """Locate the hidraw node for the eGalax P80H84 touch controller."""
    for uevent_path in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(uevent_path) as f:
                content = f.read()
        except OSError:
            continue
        # HID_ID is formatted like: HID_ID=0003:00000EEF:0000C003
        for line in content.splitlines():
            if line.startswith("HID_ID="):
                bus, vid, pid = line[len("HID_ID="):].split(":")
                if int(vid, 16) == VENDOR_ID and int(pid, 16) == PRODUCT_ID:
                    hidraw_name = uevent_path.split("/")[4]  # hidrawN
                    return f"/dev/{hidraw_name}"
    raise FileNotFoundError(
        f"no hidraw device found for {VENDOR_ID:04x}:{PRODUCT_ID:04x} "
        "(eGalax P80H84) -- pass --device explicitly if it's present under "
        "a different node"
    )


def _pkt(*leading_bytes: int) -> bytes:
    buf = bytearray(64)
    for i, b in enumerate(leading_bytes):
        buf[i] = b
    return bytes(buf)


def build_sequence(target: int, include_identify_queries: bool = True) -> list[bytes]:
    """
    The exact byte sequence eGalaxDr.Touch.exe sends on Windows when you
    click a mode button, captured with Wireshark+USBPcap and replayed
    verbatim. All packets are HID SET_REPORT, Output, Report ID 3
    (confirmed via the control transfer's wValue = 0x0203).
    """
    seq = []
    if include_identify_queries:
        # Device self-identification reads (returned "Orion", "PCAP8xx",
        # "A1_N" on the captured hardware). Not confirmed to be required
        # for the mode change to take effect, but included for fidelity
        # to the real captured sequence -- see README "Unknowns".
        seq += [
            _pkt(0x03, 0x01, 0x45, 0x00),
            _pkt(0x03, 0x01, 0x46, 0x00),
            _pkt(0x03, 0x01, 0x45, 0x00),
            _pkt(0x03, 0x01, 0x44, 0x00),
            _pkt(0x03, 0x02, 0x36, 0x14),
        ]
    seq += [
        _pkt(0x03, 0x04, 0x3F, 0x65, 0x02, 0x01),   # bracket open
        _pkt(0x03, 0x04, 0x3F, 0x65, 0x01, target),  # actual mode select
        _pkt(0x03, 0x04, 0x3F, 0x65, 0x00, 0x00),   # bracket close
    ]
    return seq


def send_sequence(dev_path: str, target: int, verbose: bool = False) -> int:
    """Sends the sequence; returns the mode value echoed back by the
    device in the closing packet's response (byte[5]), as a sanity check."""
    fd = os.open(dev_path, os.O_RDWR)
    last_echo = None
    try:
        for buf in build_sequence(target):
            os.write(fd, buf)
            resp = os.read(fd, 64)
            if verbose:
                print(f"  wrote {buf[:8].hex(' ')}  ->  read {resp[:8].hex(' ')}")
            last_echo = resp
    finally:
        os.close(fd)
    if last_echo is not None and last_echo[3] == 0x65:
        return last_echo[5]
    return -1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=sorted(MODES.keys()))
    parser.add_argument("--device", help="hidraw device path (auto-detected if omitted)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    target = MODES[args.mode]
    dev_path = args.device or find_device()

    print(f"setting touch mode '{args.mode}' (value {target:#x}) on {dev_path}")
    echoed = send_sequence(dev_path, target, verbose=args.verbose)

    if echoed == target:
        print(f"confirmed: device echoed back mode {echoed:#x}")
    else:
        print(f"warning: device echoed {echoed:#x}, expected {target:#x}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
