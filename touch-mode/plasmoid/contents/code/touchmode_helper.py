#!/usr/bin/env python3
"""
Helper for the Touch Mode plasmoid: reads or sets the EETI/eGalax touch
mode over hidraw and prints a single line of JSON for the QML side.

Usage:
    touchmode_helper.py get
    touchmode_helper.py set {finger|glove|water}

Output is always one JSON object, e.g.:
    {"ok": true, "mode": "glove", "value": 2, "device": "/dev/hidraw4"}
    {"ok": false, "error": "..."}

The query is the "bracket close" packet (03 04 3F 65 00 00) on its own:
byte[4] = 0 appears to be a read op, and the response carries the
current mode in byte[5] without changing it. See ../../../README.md.
"""
import fcntl
import glob
import json
import os
import select
import sys

VENDOR_ID = 0x0EEF
PRODUCT_ID = 0xC003
TIMEOUT = 1.0

MODES = {0x00: "water", 0x01: "finger", 0x02: "glove"}
VALUES = {name: value for value, name in MODES.items()}


class HelperError(Exception):
    pass


def find_device() -> str:
    for uevent_path in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(uevent_path) as f:
                content = f.read()
        except OSError:
            continue
        for line in content.splitlines():
            if line.startswith("HID_ID="):
                _bus, vid, pid = line[len("HID_ID="):].split(":")
                if int(vid, 16) == VENDOR_ID and int(pid, 16) == PRODUCT_ID:
                    return "/dev/" + uevent_path.split("/")[4]
    raise HelperError("Touchscreen controller (0eef:c003) not found")


def _pkt(*leading_bytes: int) -> bytes:
    buf = bytearray(64)
    buf[: len(leading_bytes)] = bytes(leading_bytes)
    return bytes(buf)


def query_packet() -> bytes:
    return _pkt(0x03, 0x04, 0x3F, 0x65, 0x00, 0x00)


def set_sequence(target: int) -> list[bytes]:
    """The full sequence captured from eGalaxDr.Touch.exe on Windows."""
    return [
        _pkt(0x03, 0x01, 0x45, 0x00),
        _pkt(0x03, 0x01, 0x46, 0x00),
        _pkt(0x03, 0x01, 0x45, 0x00),
        _pkt(0x03, 0x01, 0x44, 0x00),
        _pkt(0x03, 0x02, 0x36, 0x14),
        _pkt(0x03, 0x04, 0x3F, 0x65, 0x02, 0x01),  # bracket open
        _pkt(0x03, 0x04, 0x3F, 0x65, 0x01, target),  # mode select
        query_packet(),  # bracket close (echoes the new mode)
    ]


def transact(fd: int, buf: bytes) -> bytes:
    """Write one packet and wait for its matching response, skipping any
    ordinary touch input reports that arrive in between."""
    os.write(fd, buf)
    while True:
        ready, _, _ = select.select([fd], [], [], TIMEOUT)
        if not ready:
            raise HelperError("Timed out waiting for touchscreen response")
        resp = os.read(fd, 64)
        if len(resp) > 2 and resp[0] == buf[0] and resp[2] == buf[2]:
            return resp


def run(packets: list[bytes]) -> tuple[int, str]:
    dev_path = find_device()
    try:
        fd = os.open(dev_path, os.O_RDWR)
    except PermissionError:
        raise HelperError(f"Permission denied opening {dev_path}")
    try:
        # Serialise against other helper invocations (e.g. poll vs. set).
        fcntl.flock(fd, fcntl.LOCK_EX)
        resp = b""
        for buf in packets:
            resp = transact(fd, buf)
    finally:
        os.close(fd)
    if resp[3] != 0x65:
        raise HelperError(f"Unexpected response: {resp[:8].hex(' ')}")
    return resp[5], dev_path


def main() -> dict:
    args = sys.argv[1:]
    if args == ["get"]:
        value, dev_path = run([query_packet()])
    elif len(args) == 2 and args[0] == "set" and args[1] in VALUES:
        target = VALUES[args[1]]
        value, dev_path = run(set_sequence(target))
        if value != target:
            raise HelperError(
                f"Device reported mode {value:#x} after setting {target:#x}"
            )
    else:
        raise HelperError("usage: touchmode_helper.py get | set {finger|glove|water}")
    if value not in MODES:
        raise HelperError(f"Device reported unknown mode {value:#x}")
    return {"ok": True, "mode": MODES[value], "value": value, "device": dev_path}


if __name__ == "__main__":
    try:
        result = main()
    except (HelperError, OSError) as e:
        result = {"ok": False, "error": str(e)}
    print(json.dumps(result))
    sys.exit(0 if result["ok"] else 1)
