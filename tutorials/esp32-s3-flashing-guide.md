# ESP32-S3 Flashing Guide for the AIoT Book Labs

This guide covers everything you need to take an ESP32-S3-DevKitC-1 from "in the
box" to "running the book's lab firmware" on Linux. Tested on Debian 13 with the
canonical board (ESP32-S3 with 8 MB embedded PSRAM, native USB-Serial/JTAG).

## 1. What you should see when the board is plugged in

Connect the DevKitC's **USB** port (not the UART port, use the one labelled
`USB`) to the host. Then:

```sh
lsusb | grep -i espressif
# Bus 002 Device 005: ID 303a:1001 Espressif USB JTAG/serial debug unit

ls /dev/ttyACM*
# /dev/ttyACM3   ← yours may be ACM0, ACM1… depending on what else is plugged in
```

The native USB-Serial/JTAG enumerates as `/dev/ttyACMn`. **No CP210x or FTDI
driver is needed** on this board because the chip has the USB peripheral on-die.
If your host shows `/dev/ttyUSB0` instead, you have an older DevKitC variant
with a CP210x bridge. The rest of this guide applies the same way, just
substitute the port.

Confirm the chip identity with esptool:

```sh
esptool.py --port /dev/ttyACM3 --before default_reset --after no_reset chip_id
```

Expected:

```
Detecting chip type... ESP32-S3
Chip type:          ESP32-S3 (QFN56) (revision v0.2)
Features:           Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz, Embedded PSRAM 8MB
Crystal frequency:  40MHz
USB mode:           USB-Serial/JTAG
MAC:                1c:db:d4:75:87:dc
```

If you see `Detecting chip type... ESP32-S3` and a MAC, the chip is healthy and
the host can talk to it. You're done with hardware checks.

## 2. Permissions, get into `dialout` once

By default `/dev/ttyACM*` is owned by `root:dialout` and your user can't open it.
Add yourself to `dialout` once:

```sh
sudo usermod -aG dialout $USER
# log out and back in (or reboot) for the group to take effect
groups | tr ' ' '\n' | grep dialout
```

If the port is permission-denied even after you're in `dialout`, another process
(Arduino IDE, an old `idf.py monitor`, a Python script) is holding the port.
`fuser /dev/ttyACM3` will tell you which PID. Kill it.

## 3. Two toolchains, one chip

The book's firmware sits in two camps. Both target the same hardware.

| Toolchain     | Used by                          | Install                          |
|---------------|----------------------------------|----------------------------------|
| **ESP-IDF**   | Lab 2, Lab 4                      | `~/esp/esp-idf` + `source export.sh` |
| **PlatformIO**| Lab 13 firmware-esp32s3, Lab 14 firmware-esp32s3-espnn | `pip3 install --user --break-system-packages platformio` |

PlatformIO's `framework = espidf` builds *also* download and use ESP-IDF
internally, it just lives in `~/.platformio/packages/`. The two installs don't
fight each other, but if you want to save disk you can build everything with
the native ESP-IDF (export.sh sourced) plus a small CMakeLists.txt rewrite.

### ESP-IDF setup

The user already has ESP-IDF v5.3.1 at `~/esp/esp-idf`. To use it in any shell:

```sh
source ~/esp/esp-idf/export.sh
# Done! You can now compile ESP-IDF projects.
```

Run `idf.py --version` to confirm. The export sets `IDF_PATH` and prepends the
toolchain to your `PATH`.

### PlatformIO setup

```sh
pip3 install --user --break-system-packages platformio
~/.local/bin/pio --version          # should print PlatformIO 6.1+
```

Add `~/.local/bin` to your `PATH` if it's not there already. PlatformIO will
download whatever toolchain a project needs on the first `pio run`.

## 4. The flashing workflow, tested end to end

### A. ESP-IDF project (Lab 2 example)

```sh
source ~/esp/esp-idf/export.sh
cd ch02-rtos-latency/superloop        # or freertos/

idf.py set-target esp32s3                  # one-time per project
idf.py build                                # ~30 s after the first slow build
idf.py -p /dev/ttyACM3 flash                # ~3 s for a small app
idf.py -p /dev/ttyACM3 monitor              # Ctrl-] to exit
```

Or as one shot: `idf.py -p /dev/ttyACM3 flash monitor`.

### B. PlatformIO project (Lab 13 / Lab 14 example)

```sh
cd ch11-tflm-deployment/firmware-esp32s3

pio run                                     # build
pio run -t upload --upload-port /dev/ttyACM3
pio device monitor -p /dev/ttyACM3 -b 115200
```

Or as one shot: `pio run -t upload -t monitor`.

## 5. Per-lab status table (verified on 2026-05-09)

| Lab | Path                                         | Toolchain  | Builds | Flashes | Notes |
|-----|----------------------------------------------|------------|:------:|:-------:|-------|
| 2.1 (polling super-loop) | `ch02-rtos-latency/superloop/`      | ESP-IDF    | ✓      | ✓       | Busy-polling `app_main` `while(1)`, no `vTaskDelay`. Prints a `REPORT` line every 5 s, and `cpu_idle` stays at 0.0 % by design. |
| 2.1 (FreeRTOS)   | `ch02-rtos-latency/freertos/`             | ESP-IDF    | ✓      | ✓       | Same workload split across four tasks. Prints a `REPORT` line every 5 s, and `cpu_idle` runs near 99 % with correct priorities. Use `pio run -t upload -t monitor` in one step, see the lab README for why. |
| 4.1 (PKI / mTLS) | `ch04-pki-security/`                      | n/a        | n/a    | n/a      | No firmware, no board. A Root CA, an Intermediate CA, and a Mosquitto broker in Docker, plus a Python publisher that simulates the device. Nothing in this row to flash. |
| 11.1 (ESP32-S3)  | `ch11-tflm-deployment/firmware-esp32s3/`  | PlatformIO | ⚠      | n/a      | `src/main.cpp` includes `gesture_model.h` which is produced by the host-side `make convert` step from the trained Keras model. Run the conversion in `ch11-tflm-deployment/` first, the header lands in `firmware-esp32s3/include/`. |
| 12.1 (ESP32-S3 + ESP-NN) | `ch12-runtime-benchmark/firmware-esp32s3-espnn/` | PlatformIO | ⚠ | n/a  | Same `gesture_model.h` requirement as Lab 11. Once that header exists, `pio run -t upload -t monitor` is the full flow, and the firmware writes a CSV row per inference to serial. |

### What "Builds ✓ Flashes ✓" means

I built the firmware with `idf.py build`, flashed it to a real ESP32-S3-DevKitC-1
(8 MB PSRAM variant, MAC `1C:DB:D4:75:87:DC`) over `/dev/ttyACM3`, opened a
serial monitor, and verified the expected output appeared. Reproducible from
this guide alone.

### What "⚠" means

Either an artefact is missing from the repo (gitignored or generated host-side)
or flashing has irreversible consequences (secure boot fuses). The lab
procedure tells you how to bridge the gap, and this guide refuses to flash
blind.

## 6. Bootloader entry, when auto-reset doesn't work

The DevKitC's USB-Serial/JTAG implements the standard "auto-reset into bootloader"
sequence (DTR/RTS pulse). If your firmware crashes in a way that disables that
peripheral, or your host's USB stack mangles the reset pulse, you can force the
chip into bootloader manually:

1. Hold `BOOT` (the button labelled `BOOT` or `IO0` on older boards).
2. Tap `RESET` (or `EN`).
3. Release `BOOT`.

The chip is now waiting for an esptool flash. After flash, tap `RESET` again to
boot the new firmware.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Permission denied: '/dev/ttyACM3'` | User not in `dialout` | `sudo usermod -aG dialout $USER` then re-login |
| `A serial exception error occurred: could not open port`  | Another process holds the port (Arduino IDE, stale `idf.py monitor`) | `fuser /dev/ttyACM*` to find it, then kill it |
| `Detecting chip type... unknown` | Bootloader not entered | Use the manual BOOT+RESET sequence (§6) |
| `error: failed to read ELF`, `gesture_model.h: No such file or directory` | Lab 13 / Lab 14 model header missing | Run the lab's host-side `make convert` step first |
| Garbled serial at 115200 bps | Wrong baud, or the wrong USB port (UART instead of USB on the DevKitC) | Set baud 115200 explicitly, and switch to the USB port (closer to the antenna) |
| `Brownout detector was triggered` and reboot loop | USB cable too long / underpowered hub | Try a different cable, or plug into a powered hub or directly into the host |
| `idf.py: command not found` | `export.sh` not sourced in this shell | `source ~/esp/esp-idf/export.sh` once per shell |
| `pio: command not found` | `~/.local/bin` not in PATH | `export PATH="$HOME/.local/bin:$PATH"` in your shell rc |
| Flash works but firmware never boots | Wrong target, `idf.py set-target esp32s3` was skipped | Run `idf.py set-target esp32s3` then `idf.py fullclean build flash` |

## 8. Reading serial without the IDF / pio monitor

For scripts and CI, a 50-line Python snippet is plenty:

```python
import serial, time, sys
with serial.Serial('/dev/ttyACM3', 115200, timeout=10) as s:
    s.dtr=False; s.rts=True; time.sleep(0.05); s.dtr=True; s.rts=False  # reset pulse
    s.reset_input_buffer()
    end = time.time() + 5
    while time.time() < end:
        line = s.readline()
        if line:
            sys.stdout.buffer.write(line); sys.stdout.flush()
```

`idf.py monitor` and `pio device monitor` are nicer for interactive use, but the
above is what `tests/smoke.sh` could call without pulling in a 200 MB framework.

## 9. Going further

- **Power profiling**: pair this hardware path with a Nordic PPK2 across the
  DevKitC's `5V`/`GND` pins (use the IDC connector on the side of the board
  labelled `J3`). Lab 2's FreeRTOS vs. polling-super-loop comparison uses
  `cpu_idle` as a proxy for power, and a current-vs-time trace is what
  actually confirms the difference in draw.
- **JTAG debug**: the same USB cable that flashes the chip also exposes the
  JTAG interface. `idf.py openocd` opens the OpenOCD server, and `idf.py gdb`
  attaches GDB. No extra hardware needed.
- **The other DevKitC variants**: ESP32-S3-DevKitC-1**N8** has 8 MB flash and
  no PSRAM. **N8R8** is what the book targets (8 MB flash plus 8 MB PSRAM).
  The cheap clones often ship as N8R2 (2 MB PSRAM), which means Lab 17's
  vision buffers won't fit. Read the chip identity printed by
  `esptool chip_id`, the `Embedded PSRAM 8MB` line tells you which variant
  you have.

## 10. What this guide proves about your bench

If you completed §1, §3, §4-A on the user's bench, you have:

- An ESP32-S3-DevKitC-1 (8 MB PSRAM) detected at `/dev/ttyACM3`
- ESP-IDF v5.3.1 sourced and working
- A successfully flashed Lab 2 firmware running on the board
- Serial output flowing back at 115200 baud

Everything in Parts I and II of the book that requires this chip works the
same way from here. The Part IV labs (13, 14) layer model conversion on top
of the same flash pipeline, and once you have your `gesture_model.h`, the
workflow is identical.
