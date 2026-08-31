![Docker](../figures/tutorial-t1-docker-banner.jpeg)

# Tutorial T1: Docker startup (Windows, macOS, Linux)

Every lab in this book that is not pure firmware runs as Docker containers: Mosquitto, Redis, Node-RED, FastAPI, Streamlit, and every broker or API in between. Get Docker working once here, and Labs 1, 3, 4, and 5 all just work.

**Time:** 10 to 15 minutes. **You need:** a laptop with 8 GB or more RAM and an admin or sudo account.

## What "Docker" actually means for these labs

Two things, both required.

- **Docker Engine.** Runs containers.
- **Compose v2.** Reads a `docker-compose.yml` and brings up several containers together as one unit. Every lab command in this book is `docker compose ...`, with a space, not a hyphen. That is the modern Compose v2 CLI plugin, not the old standalone `docker-compose` Python tool. If `docker compose version` fails but `docker-compose --version` works, you have the old tool only. Follow the install steps below to get the plugin.

## Windows 10/11

Docker Desktop on Windows uses a Linux VM under the hood, through **WSL2** (Windows Subsystem for Linux). Setting up WSL2 first makes everything else, Docker included, faster and more reliable. It also gives you a proper `bash` shell for running this book's shell-script labs, described in the callout at the end of this tutorial.

1. **Enable WSL2.** Open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
   This enables the Windows features WSL2 needs, installs a Linux kernel, and installs Ubuntu as the default distribution. Reboot when prompted.
2. **Install Docker Desktop.** Download the installer from docker.com and run it. During setup, keep "Use WSL 2 instead of Hyper-V" checked. This is the default on Windows 11 and on modern Windows 10.

   [FIGURE T1-01: Docker Desktop installer, "Use WSL 2 instead of Hyper-V" checked]
   Type: screenshot
   Source: TODO, capture during setup

3. **Start Docker Desktop** from the Start menu. Wait for the whale icon in the system tray to stop animating. That means the engine is up.

   [FIGURE T1-02: Docker Desktop system tray icon, engine running]
   Type: screenshot
   Source: TODO, capture during setup

4. **Give it your WSL distro.** Open Docker Desktop, go to Settings, then Resources, then WSL Integration, and enable integration with your Ubuntu distro. This is what lets `docker` commands work from inside the WSL2 terminal.

   [FIGURE T1-03: Docker Desktop Settings, WSL Integration tab, Ubuntu toggled on]
   Type: screenshot
   Source: TODO, capture during setup

5. **Verify from the WSL2 terminal.** Search "Ubuntu" in the Start menu, or type `wsl` in PowerShell:
   ```sh
   docker --version
   docker compose version
   docker run hello-world
   ```

If `wsl --install` refuses to run, virtualization is likely disabled in the BIOS or UEFI. Reboot into firmware setup and enable Intel VT-x or AMD-V. The exact name varies by motherboard.

## macOS (Intel and Apple Silicon)

1. Download Docker Desktop for Mac from docker.com. The installer page detects Apple Silicon (M-series) versus Intel automatically, or you can pick manually.
2. Or, with Homebrew:
   ```sh
   brew install --cask docker
   ```
3. Open Docker from Applications. macOS asks for your password once, to install a privileged helper.

   [FIGURE T1-04: Docker Desktop first launch on macOS, whale icon in the menu bar]
   Type: screenshot
   Source: TODO, capture during setup

4. Wait for the menu bar whale icon to show "Docker Desktop is running," then verify in Terminal:
   ```sh
   docker --version
   docker compose version
   docker run hello-world
   ```

No `dialout` group, no WSL. Docker Desktop on macOS just works once it is running. Apple Silicon Macs run every image in this book fine. Docker transparently emulates `linux/amd64` images that do not ship an `arm64` build. This is slower, but none of these labs are performance-critical at the container level.

## Linux (Ubuntu/Debian shown, notes for Fedora/Arch below)

Skip Docker Desktop entirely and install Docker Engine and the Compose plugin directly. This is what Docker Desktop wraps on the other two platforms anyway.

```sh
# Remove old or conflicting packages if present
sudo apt-get remove docker docker-engine docker.io containerd runc

# Add Docker's official apt repository
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine and the Compose v2 plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

For Debian, substitute `debian` for `ubuntu` in the two URLs above. For Fedora, use `sudo dnf install docker-ce docker-ce-cli containerd.io docker-compose-plugin` against Docker's Fedora repo. For Arch, `sudo pacman -S docker docker-compose` already provides the `docker compose` subcommand.

**Run Docker without `sudo` on every command.** This is recommended, and the labs' scripts assume it.

```sh
sudo groupadd docker              # harmless if it already exists
sudo usermod -aG docker $USER
newgrp docker                     # or just log out and back in
```

**Start the daemon and verify:**

```sh
sudo systemctl enable --now docker
docker --version
docker compose version
docker run hello-world
```

[FIGURE T1-05: `docker run hello-world` output on a fresh Linux install]
Type: screenshot
Source: TODO, capture during setup

## Give Docker enough RAM

Every lab in this book runs fine with the defaults. If your laptop has 8 GB total, or if you are running two labs' stacks close together (do not, see the callout below), raise Docker's memory limit. Open Docker Desktop, go to Settings, then Resources, then Memory. Use 4 GB as a minimum, 6 to 8 GB is more comfortable. Linux Docker Engine has no separate limit. It uses whatever the host has free.

[FIGURE T1-06: Docker Desktop Resources, Memory slider]
Type: screenshot
Source: TODO, capture during setup

## Troubleshooting

| Symptom | Cause | Fix |
| :---- | :---- | :---- |
| `docker: command not found` | Docker Desktop or Engine not installed, or the shell was not restarted after install | Reopen the terminal. On Linux, confirm `docker --version` works outside `sudo` after the `usermod -aG docker` step and a fresh login. |
| `docker compose version` fails but `docker` works | Only the legacy standalone `docker-compose` is installed | Install the `docker-compose-plugin` package (Linux) or update Docker Desktop (Windows/macOS). See the install steps above. |
| `permission denied while trying to connect to the Docker daemon socket` (Linux) | User not in the `docker` group, or the group change has not taken effect in this shell | Run `sudo usermod -aG docker $USER`, then log out and back in, or run `newgrp docker`. |
| Docker Desktop stuck "Starting..." (Windows) | WSL2 not installed or updated | Run `wsl --update` in PowerShell, then restart Docker Desktop. |
| `docker run hello-world` times out pulling the image | No internet access, or a corporate proxy is blocking Docker Hub | Check connectivity. Configure Docker Desktop's proxy settings if behind a corporate firewall. |
| A lab's `docker compose up` fails, port already in use | Another lab's stack, or a previous run of this one, is still up | Run `docker compose down` in that other lab's folder first. Several labs reuse the same ports (`1883`, `1880`), so stop one before starting another. |
| Everything is slow on Apple Silicon | An image only ships `linux/amd64`, so it runs under emulation | Expected for a few images in this book. None of the labs are timing-sensitive at the container level. |

## A note for Windows readers: which shell to run the labs in

Every lab's commands in this repository are POSIX shell (`cd`, `chmod +x`, `./script.sh`), written for macOS and Linux. On Windows, run them from the WSL2 Ubuntu terminal you just set up, not PowerShell or `cmd.exe`. With WSL integration enabled in Docker Desktop, step 4 above, `docker compose` commands issued from WSL2 talk directly to the same engine. The shell scripts each lab ships, `tests/smoke.sh`, `pki/*.sh`, and others, run natively with no translation needed.

## Next

Docker is running. Go back to the [labs README](../README.md) and start with Lab 1, or jump to whichever lab you need.
