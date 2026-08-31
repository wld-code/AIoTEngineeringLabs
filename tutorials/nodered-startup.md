![Node-RED](../figures/tutorial-t6-nodered-banner.jpeg)

# Tutorial T6: Node-RED startup (Windows, macOS, Linux)

Node-RED shows up in this book two different ways, and knowing which one a given lab uses saves you from debugging the wrong thing. In Labs 1 and 5, Node-RED runs inside Docker alongside the rest of that lab's stack, you never install anything for it directly, `docker compose up` brings it up and you just open a browser. In Lab 6, Node-RED runs natively on the host, installed with `npm`, because that lab needs direct access to a USB serial port, and Docker on macOS and on OrbStack does not reliably pass a host serial device through to a Linux container. This tutorial covers both paths, plus the concepts that apply to either one: what a flow actually is, what Deploy does, and the one real bug this book's own labs ran into that is worth knowing about before you hit it yourself.

**Time:** 15 to 20 minutes. **You need:** Tutorial T1 (Docker) for the container path, or Node.js 18 or newer for the native path.

## What Node-RED actually is

Node-RED is flow-based programming for wiring together hardware, APIs, and online services, running on Node.js. You do not write a program top to bottom, you drag **nodes** onto a canvas and connect them with wires. Each node does one small thing, read from a serial port, parse JSON, insert a database row, publish to MQTT, and a message flows left to right through the wires between them. A collection of connected nodes is a **flow**, shown on one tab in the editor, and a Node-RED instance can hold several flows on several tabs at once, all running concurrently.

This is a genuinely different way to structure logic than writing a Python or C script, and it earns its place in this book for one specific reason: it is very fast to build and change a pipeline that mostly moves data between systems, a serial port to a database, an MQTT topic to a dashboard, without writing much code at all. It is a poor fit for anything computationally heavy or algorithmically dense, which is exactly why Lab 7's FFT and Butterworth filtering stays in a plain Python script instead of a Node-RED flow.

## Path A: Node-RED inside Docker (Labs 1 and 5)

Nothing to install here beyond Docker itself, Tutorial T1. Each lab's `docker-compose.yml` already pulls or builds a Node-RED image, and its flow is either baked into the image or bind-mounted from the lab's own folder, so `docker compose up -d` brings up a fully configured instance.

```sh
cd ch01-mosquitto-nodered   # or ch05-edge-device-twin
docker compose up -d
```

Open `http://localhost:1880`. You land in the editor with that lab's flow already loaded, imported and deployed for you. Follow the lab's own README from here, it tells you exactly what to click.

[FIGURE T6-01: Node-RED editor open in a browser, a lab's flow already loaded on the canvas]
Type: screenshot
Source: TODO, capture during setup

## Path B: Node-RED on the host (Lab 6, and any lab needing real hardware)

Install this way only when a lab's README specifically says so, currently Lab 6, because it needs to open a USB serial port directly.

### Windows 10/11

Run everything below from the WSL2 Ubuntu terminal set up in Tutorial T1, not PowerShell. One real caveat specific to Node-RED on hardware labs: WSL2 does not expose Windows USB devices to its Linux environment by default. If a lab needs the board's serial port from inside WSL2, install `usbipd-win` on the Windows side first and attach the device with `usbipd attach --wsl`, or simpler for a single lab session, run Node-RED directly from a native Windows Node.js install instead of WSL2 for that one lab.

1. Install Node.js 18 or newer from nodejs.org, or with `winget install OpenJS.NodeJS.LTS`.
2. Verify:
   ```powershell
   node --version
   npm --version
   ```

### macOS (Intel and Apple Silicon)

```sh
brew install node
node --version
npm --version
```

Node 18 or newer is what Node-RED 5 expects. If you already have an older Node installed for something else, use `nvm` to keep versions separate rather than fighting a system-wide upgrade.

### Linux (Ubuntu/Debian shown)

```sh
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
npm --version
```

For Fedora, use the equivalent NodeSource RPM script. For Arch, `sudo pacman -S nodejs npm` already gives you a current version.

### Installing Node-RED, scoped to one lab, not global

Every lab in this book that runs Node-RED natively installs it as a **local, per-project dependency**, not a global `npm install -g node-red`. This keeps each lab's exact Node-RED version and node set self-contained and reproducible, instead of depending on whatever happens to be installed globally on your machine. A lab's own `nodered/` folder already ships a `package.json` naming the exact versions it needs.

```sh
cd ch06-imu-streaming/nodered
npm install
./node_modules/.bin/node-red -s ./settings.js
```

`settings.js` points Node-RED's `userDir`, where it keeps its flow file, credentials, and installed nodes, at this same folder, so this instance never touches or gets confused with any other Node-RED you run elsewhere on the same machine.

[FIGURE T6-02: npm install output for a lab's nodered/ folder, then node-red starting and printing its "Server now running" banner]
Type: screenshot
Source: TODO, capture during setup

## The editor, in the four pieces that matter

Open `http://localhost:1880` for either path above.

- **The palette**, on the left, is every node type currently installed, grouped by category. Drag one onto the canvas to use it.
- **The canvas**, in the middle, is where flows live. Each tab across the top is a separate flow, running independently.
- **The sidebar**, on the right, includes the **Debug** tab, where any node wired to a `debug` node prints what passed through it, invaluable for seeing what a message actually contains without guessing.
- **Deploy**, top right, is the button that matters most. Nothing you do on the canvas takes effect on the running system until you click it.

[FIGURE T6-03: annotated Node-RED editor, palette, canvas, debug sidebar, and the Deploy button all visible]
Type: screenshot
Source: TODO, capture during setup

## Nodes, config nodes, and what Deploy actually does

A node on the canvas is either a **regular node**, sitting on one flow tab, wired into a pipeline, or a **config node**, a shared resource like a broker connection or a database credential that several regular nodes can reference without each one holding its own copy. You edit a config node once, by double-clicking any node that uses it, and every other node sharing it picks up the change.

Clicking **Deploy** does three things: it saves your canvas changes to the flow file on disk, it stops whichever nodes actually changed, and it restarts them with the new configuration, in that order. A small dropdown next to Deploy lets you choose **Full** (everything restarts), **Modified Flows** (only tabs you touched restart, the default), or **Modified Nodes** (an even narrower restart), useful when you have several independent flows running and do not want an unrelated one to blip.

The flow itself, every node's configuration and every wire between them, is stored as one JSON file, `flows.json`, in the instance's `userDir`. This is the same file the labs' automated tests deploy directly through Node-RED's own Admin API, `curl -X POST http://localhost:1880/flows` with the flow JSON as the body, exactly what a manual Import-then-Deploy in the browser does, just without the browser. Lab 1's `tests/smoke.sh` does exactly this to bring up a fresh clone's flow non-interactively.

## The real bug worth knowing about before you build your own flow

If you ever hand-write or hand-edit a `flows.json` instead of using the editor, one thing will bite you and is genuinely hard to diagnose from the symptom alone: a flow **tab**'s `id` field that happens to look like a plain integer, `"6310001"` for example, silently breaks Node-RED's ability to resolve **every config node** referenced by any node on that tab. Not an error naming the tab, not a warning, every `serial-port`, database, or dashboard config node on that tab just fails to be found at runtime, as if it were never configured at all. This actually happened during this book's own Lab 6 development. The fix is to give tabs (and really any hand-written node id) a non-numeric-looking string, `"tab-imu-serial"` rather than `"6310001"`. The editor itself never generates a purely numeric id, so this only bites you if you are hand-authoring or scripting a `flows.json` directly, which most readers of this book will not need to do, but it is worth knowing exists if you ever go looking.

## The Node-RED Dashboard

Several labs display live data through **Node-RED Dashboard**, a separate set of UI nodes, `ui-chart`, `ui-text`, `ui-gauge` and others, that render a real webpage at `/dashboard` built from nodes wired into your flow exactly like any other output. Lab 6 uses `@flowfuse/node-red-dashboard`, Dashboard 2.0, the actively maintained successor to the original `node-red-dashboard` package, which is deprecated. Both install the same way, as an entry in a lab's `package.json`, or through the palette manager described next for a flow you are extending yourself.

[FIGURE T6-04: a Node-RED Dashboard page open in a browser, live chart and text widgets updating]
Type: screenshot
Source: TODO, capture during setup

## Installing additional node types

A lab's own `package.json` already lists every node type it needs, `npm install` in that folder is normally all you need. To add a node type to a flow you are building yourself, open the menu in the top right of the editor, **Manage palette**, then **Install**, and search by name, this installs into the current `userDir` the same way `npm install` would, without leaving the browser.

## Troubleshooting

| Symptom | Cause | Fix |
| :---- | :---- | :---- |
| `node-red: command not found` | Installed locally in a lab folder, not globally, which is intentional | Run it through the path, `./node_modules/.bin/node-red`, or from that folder specifically |
| A serial-in node's status never turns green | The port field still holds the lab's placeholder, or another process already has the port open | Edit the `serial-port` config node with your actual port from `arduino-cli board list` or `ls /dev/tty.*`, and confirm no other program, including a previous Node-RED instance, already holds it |
| Config nodes silently fail to resolve, every one on a tab at once | A hand-edited flow tab has a purely numeric `id` | Give the tab a non-numeric id, see the section above |
| Editor loads but a flow you exported elsewhere fails to import | Missing node types, the target instance never had them installed | Check the Node-RED startup log for `Missing node types` and install each one before retrying the import |
| Dashboard page is blank at `/dashboard` | The dashboard package is not installed, or no `ui-base` config node exists yet | Confirm `@flowfuse/node-red-dashboard` (or `node-red-dashboard`) is in the lab's `package.json` and that `npm install` completed without errors |
| Two browser tabs open the same lab, only one ever shows live data | An MQTT or database config node using a fixed, non-unique client id, an old session keeps kicking the new one off | This is a code bug in whatever flow or app you are running, not a Node-RED setup problem, give each session's client a unique id |

## Next

Node-RED is running. Go back to the [labs README](../README.md) and start with whichever lab sent you here, Lab 1, Lab 5, or Lab 6.
