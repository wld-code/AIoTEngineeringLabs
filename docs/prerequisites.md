![An Arduino Nano 33 BLE Sense and a Seeed Studio XIAO ESP32-S3, two of the boards these labs run on](../figures/banner.jpeg)

# Prerequisites

What to install before starting a lab, and what hardware each one needs. Come back to this page whenever a lab's README points you here.

## Software, at a glance

| Requirement | Needed for | Install |
| :---- | :---- | :---- |
| **Docker** with **Compose v2** | Labs 1, 3, 4, 5 (and most of Labs 6 to 16) | [Tutorial T1: Docker startup](../tutorials/docker-startup.md) |
| **Python 3** | Lab 1 (device simulator), Lab 3 (test runner, no extra packages needed) | Bundled with the Docker tutorial's OS steps, or install separately |
| **Node.js 18+** | Lab 6 (Node-RED runs natively on the host there, not in Docker) | [Tutorial T6: Node-RED startup](../tutorials/nodered-startup.md) |
| **OpenSSL** and **`mosquitto-clients`** | Lab 4 | `brew install mosquitto` (macOS). `apt install mosquitto-clients` (Debian/Ubuntu). See Lab 4's own README for Windows. |
| **ESP32-S3 board** and **PlatformIO** | Lab 2 (and Labs 4, 11, 12, 15, 16 later) | [Tutorial T2: ESP32-S3 startup](../tutorials/esp32-s3-startup.md) |
| **FreeRTOS / ESP-IDF** (optional, direct path) | Lab 2's raw `idf.py` alternative | [Tutorial T3: FreeRTOS for ESP32-S3 startup](../tutorials/freertos-esp32-s3-startup.md) |
| **Raspberry Pi** | Not required for Labs 1 to 5. Needed later (Lab 16). | [Tutorial T4: Raspberry Pi startup](../tutorials/raspberrypi-startup.md) |
| **Arduino Nano 33 BLE Sense** | Not required for Labs 1 to 5. Needed later (Labs 6 to 9, 11 to 15). | [Tutorial T5: Arduino Nano 33 BLE startup](../tutorials/arduino-nano33ble-startup.md) |
| **Jetson Nano** (optional) | Not required by any numbered lab. One of Chapter 2's four core platforms, for GPU-accelerated vision work you extend yourself. | [Tutorial T7: Jetson Nano startup](../tutorials/jetson-nano-startup.md) |

No lab in Part I requires more than a laptop plus Docker, and for Lab 2 only, one ESP32-S3 board.

## Hardware and software per lab

| Lab | Hardware / software required | OS required |
| :---- | :---- | :---- |
| 1 | Docker, Compose v2, Python 3 | Windows (via WSL2), macOS, Linux |
| 2 | ESP32-S3 board, USB-C cable, PlatformIO (or ESP-IDF) | Windows, macOS, Linux |
| 3 | Docker, Compose v2 | Windows (via WSL2), macOS, Linux |
| 4 | Docker, Compose v2, OpenSSL, `mosquitto-clients` | Windows (via WSL2), macOS, Linux |
| 5 | Docker, Compose v2 | Windows (via WSL2), macOS, Linux |
| 6 | Docker, Compose v2, Node.js 18+, Arduino Nano 33 BLE Sense (required, streamed over USB serial) | Windows (via WSL2), macOS, Linux |
| 7, 8 | Docker, Compose v2, Python 3, Arduino Nano 33 BLE Sense (optional, a simulator covers the labs without it) | Windows (via WSL2), macOS, Linux |
| 9, 11 to 13 | Python 3, TensorFlow / TensorFlow Lite Micro, Arduino Nano 33 BLE Sense and/or ESP32-S3 | Windows, macOS, Linux |
| 10 | Python 3 | Windows, macOS, Linux |
| 14 | Python 3, OV7670 camera, Arduino Nano 33 BLE Sense | Windows, macOS, Linux |
| 15 | Node.js 18+, Arduino Nano 33 BLE Sense, Ollama | Windows (via WSL2), macOS, Linux |
| 16 | Docker, Compose v2, Raspberry Pi 4, ESP32-S3 | Windows (via WSL2), macOS, Linux |

All software used across the labs is open source. Every Dockerfile, `requirements.txt`, and `platformio.ini` ships in this repository.

## A note for Windows readers

Every lab's commands are POSIX shell (`cd`, `chmod +x`, `./script.sh`). Run them from WSL2's Ubuntu terminal, not PowerShell or `cmd.exe`. Tutorial T1 sets up WSL2 as part of installing Docker Desktop. With WSL integration enabled, `docker compose` from inside WSL2 talks to the same engine with no translation needed.

## Running more than one lab's stack at once

Do not. Labs 1, 3, 4, and 5 each bring up their own Mosquitto broker, and several reuse the same host ports (`1883`, `1880`). Before switching labs, stop the one you were just in:

```sh
docker compose down
```

Each lab's own troubleshooting table repeats this for the specific ports it binds, in case you hit a conflict.

## What you actually need to know

A working command line and Docker for every compose-based lab, plus, for the four firmware labs across the 16, a board and PlatformIO (or raw ESP-IDF). Knowledge of Python is useful for reading the simulator and test-runner scripts, and knowledge of C is useful for reading the firmware, but neither is required to run a lab end to end and read its output. A basic understanding of MQTT publish and subscribe, of what a Docker container is, and of what a certificate does helps, but the chapter each lab pairs with builds that understanding first.
