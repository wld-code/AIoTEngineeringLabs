![FreeRTOS](../figures/tutorial-t3-freertos-banner.jpeg)

# Tutorial T3: FreeRTOS for ESP32-S3 startup (Windows, macOS, Linux)

Complete [Tutorial T2: ESP32-S3 startup](./esp32-s3-startup.md) first. You need a board the host can already detect and flash before this tutorial is useful.

FreeRTOS is the real-time kernel that ships bundled inside ESP-IDF, Espressif's official framework. It provides pre-emptive task scheduling, queues, mutexes, and software timers. It is what Part 2 and Part 3 of [Lab 2](../ch02-rtos-latency/README.md) measure. You get FreeRTOS two ways.

- **The easy way, recommended for most readers.** PlatformIO's `framework = espidf`, which Tutorial T2 already set up, downloads and manages ESP-IDF for you, invisibly, per project. If Tutorial T2's `pio run -t upload -t monitor` worked, you already have FreeRTOS running on your board and can skip straight to [Lab 2](../ch02-rtos-latency/README.md).
- **The direct way, covered in this tutorial.** Install ESP-IDF yourself and drive it with `idf.py`. Do this if you want to understand the toolchain PlatformIO is hiding from you, need `idf.py openocd` or `idf.py gdb` for JTAG debugging, or just prefer working close to the metal.

**Time:** 20 to 30 minutes, mostly unattended download and build time.

## What FreeRTOS gives you, in one paragraph

A task is a small function with its own stack that the scheduler can pause and resume. Tasks have priorities. A higher-priority task pre-empts a lower one the instant it becomes ready to run, for example when a queue it is waiting on receives data. Queues pass data between tasks safely. Critical sections (`portMUX_TYPE`, `taskENTER_CRITICAL`) protect data shared between tasks or between a task and an interrupt. Lab 2 builds the exact same workload three ways: a polling loop, correctly prioritized FreeRTOS tasks, and incorrectly prioritized ones, so you measure what each of these concepts actually buys you, instead of taking it on faith.

## Windows

1. Download the ESP-IDF Windows Installer from Espressif's [get-started page](https://dl.espressif.com/dl/esp-idf/). It is a single offline installer that bundles Python, Git, and the full toolchain, with no separate installs required.
2. Run it. When asked which ESP-IDF version, pick the latest v5.x release. When asked which targets to install, make sure ESP32-S3 is checked. It usually is, by default, along with the others.

   [FIGURE T3-01: ESP-IDF Windows Installer, target selection screen with ESP32-S3 checked]
   Type: screenshot
   Source: TODO, capture during setup

3. The installer creates Start Menu shortcuts, "ESP-IDF 5.x CMD" and "ESP-IDF 5.x PowerShell." Use either one. It is a normal shell with the ESP-IDF environment already sourced, equivalent to running `export.sh` on macOS/Linux, described below.
4. Open the ESP-IDF PowerShell shortcut and verify:
   ```powershell
   idf.py --version
   ```

## macOS

```sh
brew install cmake ninja dfu-util
mkdir -p ~/esp
cd ~/esp
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32s3
```

`install.sh esp32s3` downloads only the ESP32-S3 toolchain, skipping the other chip targets, for a faster install and less disk use. Then, in every new shell where you want to use `idf.py`:

```sh
. ~/esp/esp-idf/export.sh
idf.py --version
```

Add an alias to your shell rc file (`~/.zshrc`) so you do not retype the path:

```sh
alias get_idf='. $HOME/esp/esp-idf/export.sh'
```

## Linux (Ubuntu/Debian shown, other distros need the equivalent packages)

```sh
sudo apt-get update
sudo apt-get install -y git wget flex bison gperf python3 python3-pip python3-venv \
  cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0

mkdir -p ~/esp
cd ~/esp
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32s3
```

Then, in every new shell:

```sh
. ~/esp/esp-idf/export.sh
idf.py --version
```

The same `alias get_idf='. $HOME/esp/esp-idf/export.sh'` trick works here too.

## Verify: build and flash Lab 2's FreeRTOS firmware

With `export.sh` sourced in your shell, or the ESP-IDF shortcut open on Windows:

```sh
cd ch02-rtos-latency/freertos      # the FreeRTOS-tasks build, not superloop/
idf.py set-target esp32s3               # one time per project
idf.py build                            # about 30 s after the first, slower build
idf.py -p <PORT> flash monitor          # COM5 (Windows), /dev/ttyACM0 (Linux), /dev/cu.usbmodem1101 (macOS)
```

Expected output:

```
REPORT  events=9  worst_latency=30 us (0.030 ms)  cpu_idle=99.2%
```

[FIGURE T3-02: `idf.py flash monitor` output for Lab 2's freertos build, showing worst_latency and cpu_idle]
Type: screenshot
Source: TODO, capture during setup

That single `REPORT` line is FreeRTOS's pre-emptive scheduling in action. Worst-case alarm latency lands in the tens of microseconds, not milliseconds. Compare it against the same workload's polling-loop number in [Lab 2 Part 1](../ch02-rtos-latency/README.md). Press `Ctrl-]` to exit the monitor.

## PlatformIO and raw ESP-IDF side by side

Both toolchains produce working firmware for the same chip. PlatformIO's `framework = espidf` downloads and drives ESP-IDF for you, inside `~/.platformio/packages/`, so the two installs coexist without conflicting. Lab 2's own README documents both command sets. Use whichever this tutorial set up for you.

| | PlatformIO (Tutorial T2) | Raw ESP-IDF (this tutorial) |
| :---- | :---- | :---- |
| One-time setup | `pip install platformio` | Clone `esp-idf`, run `install.sh esp32s3` |
| Per-shell setup | none | `. export.sh`, or the ESP-IDF Windows shortcut |
| Build, flash, and monitor | `pio run -t upload -t monitor` | `idf.py flash monitor` |
| Set target | automatic from `platformio.ini` | `idf.py set-target esp32s3`, once per project |

## Troubleshooting

| Symptom | Cause | Fix |
| :---- | :---- | :---- |
| `idf.py: command not found` | `export.sh` not sourced in this shell (macOS/Linux), or not using the ESP-IDF shortcut (Windows) | Run `. ~/esp/esp-idf/export.sh` once per new shell |
| `install.sh` fails partway through a download | Flaky network mid-download | Re-run `./install.sh esp32s3`. It resumes rather than restarting from scratch. |
| `idf.py build` errors on a missing Python package | `install.sh` was interrupted before it finished | Re-run `./install.sh esp32s3` to completion |
| `idf.py -p <PORT> flash` cannot open the port | Same serial-permission issue as Tutorial T2 | Re-check the `dialout` group (Linux) or the COM port number (Windows) from Tutorial T2, section 2 |
| Flash succeeds but firmware never boots correctly | Wrong target set, or a stale build from a different chip | Run `idf.py set-target esp32s3` then `idf.py fullclean build flash` |
| Windows: "ESP-IDF x.x CMD" shortcut missing after install | Installer did not finish, or a different ESP-IDF version was selected | Re-run the installer from the Start Menu search ("ESP-IDF Tools") to add or repair a version |

## Going further

- `idf.py openocd` and `idf.py gdb` give you live JTAG debugging over the same USB cable that flashes the chip. No extra hardware.
- Read the source of `ch02-rtos-latency/freertos/main/main.c` before reflashing anything. Lab 2's README is explicit that the point is understanding why the scheduler behaves this way, not just watching the numbers change.
- The [ESP32-S3 flashing guide](./esp32-s3-flashing-guide.md), in this same folder, has more low-level detail (per-lab toolchain status, reading serial without a monitor tool, JTAG pinout) for readers going deeper on this chip.

## Next

Go run the full [Lab 2: Super-loop vs FreeRTOS Scheduling](../ch02-rtos-latency/README.md). You now have both the easy and the direct toolchain available for it.
