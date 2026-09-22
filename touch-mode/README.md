# EETI/eGalax touch mode switching on Linux (Dell Latitude 7220 Rugged Extreme Tablet)

## Problem

The Dell Latitude 7220 Rugged Extreme Tablet ships with an EETI/eGalax
capacitive touchscreen that supports three sensing modes: **Finger**
(normal), **Glove**, and **Water/Rain**. On Windows this is switched via
Dell's bundled `eGalaxDr.Touch.exe` app or the `TouchControl.exe -SetTouchMode`
CLI (installed from `EETI-eGalax-Touch-Panel-Application_*.EXE`, a Dell
Update Package). No such tool, driver, or sysfs knob exists on Linux --
the kernel's generic `hid-multitouch` driver binds the device and handles
ordinary touch input fine, but has no concept of this vendor mode switch.

## Hardware identified

- Device: `eGalax Inc. eGalaxTouch P80H84 0710 vA1_N k47_45`
- USB VID:PID: `0eef:c003` (D-WAV Scientific Co., Ltd / eGalax)
- Chip family: "Orion", controller marked "PCAP8xx" (from the device's own
  self-identification strings, see below)
- Linux driver: `hid-multitouch` (generic, no vendor awareness)
- No dedicated interrupt OUT endpoint -- vendor commands go over the
  **control endpoint** as `SET_REPORT`, not the interrupt pipe

## Method

1. Extracted the Dell driver installer (`EETI-eGalax-Touch-Panel-Application_HTKMY_WIN64_1.0.17.11428_A00.EXE`,
   a self-extracting 7-Zip/Dell Update Package -- `7z x` unpacks it directly, no need to run it).
   Payload includes `eGalaxDr.Touch.exe` (GUI), `TouchControl.exe` (CLI,
   invoked by a scheduled task on boot/wake/lock to reapply the saved mode),
   and `HIDdAPI.dll` (the vendor SDK both link against).

2. Statically disassembled `HIDdAPI.dll` (32-bit PE, `objdump -d -M intel`,
   cross-referenced with `pefile` for imports/exports). Found exported
   functions `FingerGloveMode()` and `EnhanceWaterproofMode()`, and traced
   them down to the packet they build and send via `WriteFile`/`ReadFile`
   on the HID device handle. This gave the **packet shape** (64 bytes,
   report ID 3, `cmd=0x04`, `len=0x3F`, a subcommand byte, then a mode
   byte) but **not the correct semantics** -- static analysis alone
   pointed at the wrong byte as "the mode selector" (see Pitfalls below).

3. Confirmed and corrected the protocol by capturing real USB traffic:
   ran `eGalaxDr.Touch.exe` on Windows (booted on the same physical
   tablet) under Wireshark + USBPcap, clicked through Water / Stylus /
   Glove / Stylus, and diffed the captured `SET_REPORT` packets against
   what changed on each click. This is what actually nailed the protocol
   down -- see `touchapp.pcapng`-derived findings below.

4. Replayed the exact captured byte sequence from Linux via a raw
   `write()`/`read()` on `/dev/hidrawN` (hidraw's `write()` transparently
   falls back to a control-transfer `SET_REPORT` when there's no
   interrupt OUT endpoint, so this "just works" without any ioctl).
   Verified physically on the real hardware: finger/glove/stylus touch
   behavior changed exactly as expected for each mode, and the setting
   **survived a full reboot and OS switch** (Linux -> Windows -> Linux),
   confirming it's stored in the touch controller's own firmware/EEPROM,
   not anywhere host-side.

## Confirmed protocol

All packets are 64 bytes, sent as HID `SET_REPORT` (Output, Report ID 3)
via a USB control transfer (`bmRequestType=0x21, bRequest=0x09,
wValue=0x0203, wIndex=0x0000, wLength=0x0040`). On Linux, writing 64
bytes (first byte = report ID `0x03`) to the device's `/dev/hidrawN`
node with `os.write()` triggers this same transfer.

The full sequence to change mode, exactly as captured from the real
Windows app:

```
03 01 45 00 ...  (query -- device replied "Orion", a family/product ID string)
03 01 46 00 ...  (query -- device replied "PCAP8..." )
03 01 45 00 ...  (repeat of the first query)
03 01 44 00 ...  (query -- device replied "A1_N", matching its USB product string suffix)
03 02 36 14 ...  (a fixed "ping"/status packet, identical on every mode change observed)
03 04 3F 65 02 01 ...  (bracket OPEN -- fixed, identical every time)
03 04 3F 65 01 XX ...  (the actual mode select: XX = target mode)
03 04 3F 65 00 00 ...  (bracket CLOSE -- fixed; its echoed response has the
                         *new current mode* in byte[5], useful as a
                         post-write sanity check)
```

Confirmed mode values (`XX` above), verified against real touch/glove/
stylus behavior on the physical device:

| Value | Mode |
|-------|------|
| `0x00` | Water / Rain |
| `0x01` | Finger / Passive Stylus (normal -- the default/expected state) |
| `0x02` | Glove |

See `set_touch_mode.py` for a ready-to-run implementation (auto-detects
the `/dev/hidrawN` node by VID:PID, replays the sequence, sanity-checks
the echoed value).

## Pitfalls / how the first attempt got it wrong

Worth keeping for anyone extending this: the static disassembly of
`FingerGloveMode()` made it look like **byte[4]** in a simpler 1-packet
`03 04 3F 65 <mode> <param>` write was the mode selector (that's the
argument the exported function takes directly). Testing that hypothesis
live on the hardware -- cycling byte[4] through `0..4` -- produced
*zero* observable change in touch/glove/stylus behavior across all five
values, despite the device cleanly echoing back whatever was sent every
time (echoes only prove the packet was well-formed and accepted, not
that it changed anything).

The real Windows traffic showed why: that simple single-packet write
*is* real traffic the app sends, but it fires with a **fixed, identical
byte[4] sequence (2, then 1, then 0) on every single button click**,
regardless of which button was pressed -- it's a status probe/heartbeat,
not the mode switch. The actual selector is the **last byte of the
middle packet in that 3-packet bracket** (what's labeled `param`/byte[5]
above), which is easy to miss from static analysis alone because the
DLL's `FingerGloveMode(handle, mode, &result)` wrapper reuses that
`result` output parameter's *pre-call* value as the outgoing payload
byte -- i.e. the real "mode" is smuggled in through what looks like a
pure output/status parameter in the decompiled C signature.

**Lesson for future protocol RE on this class of device**: static
disassembly gets you the packet shape and is worth doing first (cheap,
no hardware risk), but treat the exact byte-to-meaning mapping as a
hypothesis to verify against live traffic, not a conclusion -- clean
protocol-level echoes are not evidence of correct *semantics*.

## Unknowns / untested

- **Reading the current mode without changing it**: not found. The
  closing bracket packet's echo happens to report the mode you just
  set, but there's no known query-only path. Worth checking whether
  `GetEETIMutliTouchMode` (a separate `HIDdAPI.dll` export, ordinal 91,
  unexplored) does this.
- **Whether the 4 identify-query packets and the `03 02 36 14` ping are
  functionally required**, or just harmless things the GUI happens to
  do on every click. `set_touch_mode.py` includes them for fidelity to
  the real captured sequence but this hasn't been tested with them
  omitted.
- **`EnhanceWaterproofMode()`** (subcommand `0x6C` instead of `0x65`,
  same packet shape) is a distinct exported function in `HIDdAPI.dll`
  that was never observed in the real Windows capture and, when tried
  directly on this hardware from Linux, got **no response at all**
  (blocking read, no data) -- this firmware doesn't implement it, or it
  needs different preconditions. Not necessary for mode switching (that
  turned out to live entirely in the `0x65` bracket sequence above) but
  flagged in case a different eGalax/EETI device model does use it.
- **Persistence mechanism**: confirmed the mode survives reboots/OS
  switches (stored on-device), so no boot-time reapplication is needed
  on Linux. Not investigated: whether there's a way to reset it back to
  a factory default, or whether power-cycling the tablet (vs. suspend/
  USB re-enumeration) ever resets it.
- Only tested on this one physical unit's firmware
  (`P80H84 0710 vA1_N k47_45`); byte values are unlikely to generalize
  to other EETI/eGalax controller families without re-verification.

## Files here

- `set_touch_mode.py` -- the working implementation. `./set_touch_mode.py {finger|glove|water}`
