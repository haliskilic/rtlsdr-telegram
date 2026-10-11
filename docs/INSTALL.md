# Installation Guide — step by step

> Türkçe sürüm: [INSTALL.tr.md](INSTALL.tr.md)

This guide assumes **no prior experience**. Every section lists exactly what to
type and what you should see. Pick your platform:

- [0. What you need](#0-what-you-need)
- [1. Create the Telegram bot (all platforms)](#1-create-the-telegram-bot-all-platforms)
- [2A. Ubuntu / Debian PC](#2a-ubuntu--debian-pc)
- [2B. Raspberry Pi](#2b-raspberry-pi)
- [2C. Proxmox (LXC container)](#2c-proxmox-lxc-container)
- [2D. Windows 10/11](#2d-windows-1011)
- [3. Configure config.yaml](#3-configure-configyaml)
- [4. First run and tests](#4-first-run-and-tests)
- [5. Run as a service](#5-run-as-a-service)
- [6. Check it in Telegram](#6-check-it-in-telegram)
- [7. Updating](#7-updating)
- [8. Troubleshooting](#8-troubleshooting)

---

## 0. What you need

**Hardware**
| Item | Notes |
|------|-------|
| RTL-SDR dongle | RTL2832U + R820T/R860 (e.g. RTL-SDR Blog V3/V4, NESDR). USB 2.0 port directly on the machine (avoid cheap hubs). |
| Antenna | A telescopic/discone antenna is fine to start. Better results: 1090 MHz antenna for ADS-B, a vertical VHF antenna for air/marine/amateur, a QFH/turnstile for 137 MHz satellites. Connect to the dongle's MCX/SMA input. |
| Computer | Ubuntu/Debian PC, Raspberry Pi 4/5 (64-bit OS), a Proxmox host, or Windows 10/11. 2 GB RAM is enough; 4 CPU cores recommended if you enable transcription. |
| Internet | For Telegram, TLE downloads and the first Whisper model download. |

**Accounts**
- A Telegram account and a group where the messages will be posted (Topics enabled).

**Software requirements (installed by the scripts below)**
| Component | Purpose | Linux package / source |
|-----------|---------|------------------------|
| rtl-sdr (rtl_fm, rtl_power, rtl_test) | dongle access | apt `rtl-sdr librtlsdr-dev` |
| readsb | ADS-B | source (Debian's package lacks RTL support) |
| acarsdec, dumpvdl2, libacars | ACARS / VDL2 | source |
| AIS-catcher, rtl-ais | AIS | source |
| rtl_433 | ISM sensors | apt `rtl-433` |
| multimon-ng, direwolf | APRS | apt |
| gr-gsm | GSM cell IDs | apt `gr-gsm` |
| satdump | Meteor-M, Inmarsat | apt `satdump` |
| ffmpeg, sox | audio encoding | apt |
| Python 3.11+ with venv | the application | apt `python3 python3-venv` |
| Python libs | see `requirements.txt` | pip (or apt: python3-numpy/scipy/matplotlib/httpx/yaml/skyfield/psutil/aprslib) |
| faster-whisper (optional) | local transcription | pip |

---

## 1. Create the Telegram bot (all platforms)

1. Open Telegram, search **@BotFather**, send `/newbot`. Choose a name (e.g. *My SDR Monitor*) and a username ending in `bot` (e.g. `mysdrmonitor_bot`).
2. BotFather replies with a **token** like `123456789:AAF...`. Keep it secret — it is the bot's password.
3. In BotFather: `/mybots` → your bot → **Bot Settings** → **Group Privacy** → **Turn off**. (So the bot can see commands in your group.)
4. Create (or open) the Telegram **group** that will receive the messages. In group settings enable **Topics**. Create a topic, e.g. *RTL-SDR*.
5. Add the bot to the group and make it an **administrator** (needed to post in topics).
6. Find the IDs. On the machine where you will install (after step 2x), run:
   ```bash
   python3 tools/telegram_ids.py <BOT_TOKEN>
   ```
   While it waits, write `/start@<botname>` **inside the topic**. The script prints:
   ```
   chat_id   : -1001234567890
   thread_id : 123
   admin id  : 987654321
   ```
   Write these down — they go into `config.yaml` (step 3).

> Security: the bot only accepts commands from the admin ids you configure and only
> inside your group (or in a private chat from an admin). If someone adds the bot to
> another group it leaves automatically. Strangers who message it get no reply.

---

## 2A. Ubuntu / Debian PC

Tested on Ubuntu 22.04/24.04 and Debian 12/13.

**Step 1 — plug in the dongle and open a terminal.**

**Step 2 — download the project**
```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/haliskilic/rtlsdr-telegram.git
cd rtlsdr-telegram
```

**Step 3 — run the installer (takes 5–15 minutes; it compiles a few tools)**
```bash
sudo bash install/debian-linux.sh
```
What it does: installs apt packages, builds readsb/acarsdec/dumpvdl2/AIS-catcher/rtl-ais
from source into `/usr/local/bin`, blacklists the kernel DVB driver (which would
otherwise grab the dongle), writes a udev rule, copies the app to
`/opt/rtlsdr-telegram`, creates a Python venv and installs the systemd service.
At the end you should see `>>> DONE`.

**Step 4 — verify the dongle**
```bash
rtl_test -t
```
You should see `Found 1 device(s)` and the tuner name. Press Ctrl+C to stop.
If you see `No supported devices found`, unplug/replug the dongle and try another USB port.

**Step 5 — optional: local transcription**
```bash
sudo /opt/rtlsdr-telegram/venv/bin/pip install faster-whisper
```
(The `base` model is downloaded automatically on first use, ~150 MB.)

Continue with [3. Configure config.yaml](#3-configure-configyaml).

---

## 2B. Raspberry Pi

Use **Raspberry Pi OS (64-bit, Bookworm)** on a Pi 4 or Pi 5 with a good power supply.

**Step 1 — prepare the Pi**
- Flash Raspberry Pi OS 64-bit with Raspberry Pi Imager, enable SSH in the imager settings, boot.
- Log in (`ssh pi@raspberrypi.local`) and update:
  ```bash
  sudo apt update && sudo apt full-upgrade -y && sudo reboot
  ```

**Step 2 — plug the dongle into a USB port** (blue USB 3.0 ports are fine). Prefer a short, good quality antenna cable.

**Step 3 — download and install**
```bash
sudo apt install -y git
git clone https://github.com/haliskilic/rtlsdr-telegram.git
cd rtlsdr-telegram
sudo bash install/raspberrypi.sh
```
The Pi compiles a few tools; this can take **15–30 minutes**. Get a coffee.

**Step 4 — verify the dongle**: `rtl_test -t` → `Found 1 device(s)`.

**Step 5 — Pi-specific settings** (edit later in `config.yaml`):
- `transcription.model: tiny` (or `engine: none` on a Pi 3) — Whisper is CPU heavy.
- `targets.spectrum.period_s: 1200` — sweeps are CPU heavy.
- Cooling: a heatsink/fan is recommended; `satdump` and Whisper load the CPU.
- Power: add `max_usb_current=1` to `/boot/firmware/config.txt` if the dongle resets.

Continue with [3. Configure config.yaml](#3-configure-configyaml).

---

## 2C. Proxmox (LXC container)

The dongle is plugged into the **Proxmox host** and passed through to an
unprivileged Debian container. Do steps 1–3 on the **host** shell (SSH as root),
steps 4–6 inside the container.

**Step 1 — host: stop the kernel from grabbing the dongle**
```bash
cat > /etc/modprobe.d/blacklist-rtlsdr.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist rtl2832_sdr
blacklist dvb_usb_v2
EOF
for m in rtl2832_sdr dvb_usb_rtl28xxu rtl2832 dvb_usb_v2; do rmmod $m 2>/dev/null; done
cat > /etc/udev/rules.d/20-rtlsdr.rules <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
EOF
udevadm control --reload-rules && udevadm trigger
lsusb | grep -i 0bda      # must show "Realtek ... RTL2838"
```
If `lsusb` shows nothing, the dongle is not detected electrically: try another USB port
(rear ports), remove hubs/extensions, re-seat the dongle.

**Step 2 — host: create the container** (adjust storage/template names to yours;
list templates with `pveam available --section system` and download with `pveam download local <name>`)
```bash
pct create 102 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname rtlsdr-telegram --cores 4 --memory 2048 --swap 1024 \
  --rootfs local-lvm:16 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1 --password 'ChangeMe123'
```

**Step 3 — host: USB passthrough**
```bash
cat >> /etc/pve/lxc/102.conf <<'EOF'
lxc.cgroup2.devices.allow: c 189:* rwm
lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir
EOF
pct start 102
pct exec 102 -- bash -c "apt update && apt install -y git usbutils rtl-sdr && rtl_test -t"
```
The last command must print `Found 1 device(s)`. (`onboot: 1` makes the container
start with the host; the service inside starts with the container.)

**Step 4 — container: install the project**
```bash
pct exec 102 -- bash
# now inside the container:
git clone https://github.com/haliskilic/rtlsdr-telegram.git /opt/rtlsdr-telegram-src
cd /opt/rtlsdr-telegram-src
bash install/debian-linux.sh
```

**Step 5 — container: optional transcription**
```bash
/opt/rtlsdr-telegram/venv/bin/pip install faster-whisper
```

**Step 6 — container: keep logs bounded** (the installer already does this; shown for reference)
```bash
cat /etc/systemd/journald.conf.d/rtlsdr-telegram.conf
# SystemMaxUse=200M, MaxRetentionSec=1month
```

Continue with [3. Configure config.yaml](#3-configure-configyaml) (file lives at
`/opt/rtlsdr-telegram/config.yaml` inside the container).

---

## 2D. Windows 10/11

Windows works for most targets. ACARS/VDL2, gr-gsm and radiosonde_auto_rx are hard
to build on Windows — disable those targets or run the Linux version in WSL2.

**Step 1 — Python**: install Python 3.11+ from https://www.python.org/downloads/ and
tick **"Add Python to PATH"**.

**Step 2 — dongle driver (Zadig)**
1. Plug in the dongle. Download **Zadig** from https://zadig.akeo.ie/ and run it.
2. *Options → List All Devices*. Select **"Bulk-In, Interface (Interface 0)"** (or "RTL2838UHIDIR").
3. Choose **WinUSB** as the driver and click **Replace Driver**.

**Step 3 — SDR tools**: download and unzip, then add each `bin` folder to your PATH
(*Settings → System → About → Advanced system settings → Environment Variables*):
- rtl-sdr (rtl_fm, rtl_power, rtl_test): https://github.com/osmocom/rtl-sdr/releases or https://www.rtl-sdr.com/ (Windows build)
- rtl_433: https://github.com/merbanan/rtl_433/releases
- AIS-catcher: https://github.com/jvde-github/AIS-catcher/releases
- readsb/dump1090 for Windows: https://github.com/MalcolmRobb/dump1090 (set `targets.adsb.tool: dump1090`)
- multimon-ng: https://github.com/EliasOenal/multimon-ng/releases
- SatDump: https://www.satdump.org/download/
- ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (the `bin` folder)

Open a new *Command Prompt* and check: `rtl_test -t` → `Found 1 device(s)`.

**Step 4 — the project**
```powershell
git clone https://github.com/haliskilic/rtlsdr-telegram.git
cd rtlsdr-telegram
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pip install faster-whisper      # optional
copy config.example.yaml config.yaml
notepad config.yaml                          # see step 3; set platform: windows
venv\Scripts\python run.py --check -c config.yaml
venv\Scripts\python run.py -c config.yaml
```

**Step 5 — run at boot (optional)** with NSSM (https://nssm.cc/):
```powershell
nssm install rtlsdr-telegram "C:\path\to\venv\Scripts\python.exe" "C:\path\to\run.py -c C:\path\to\config.yaml"
nssm start rtlsdr-telegram
```

---

## 3. Configure config.yaml

Open the file (Linux: `sudo nano /opt/rtlsdr-telegram/config.yaml`). Only these
keys are mandatory:

```yaml
language: en                 # en | tr  (Telegram message language)
telegram:
  token: "123456789:AAF..."  # from BotFather
  chat_id: -1001234567890    # from tools/telegram_ids.py
  thread_id: 123             # the topic id (0 = General topic)
  admins: [987654321]        # your own Telegram user id
station:
  name: "My Station"
  lat: 41.0082               # your location (satellite passes, distances)
  lon: 28.9784
```

Useful optional settings:
```yaml
paths:
  retention_months: 6        # delete recordings/events older than 6 months (or retention_years)
transcription:
  engine: faster_whisper     # none to disable
  model: base                # tiny on a Raspberry Pi
targets:
  adsb: {report_mode: summary}    # one summary per slot (busy airspace)
  ais:  {report_mode: summary}
  gsm:  {enabled: false}          # disable what you do not need
```
Every target has `enabled`, `priority`, `dwell_s`, `period_s`; see `config.example.yaml`
for all options with comments. Protect the file: `chmod 600 config.yaml`.

---

## 4. First run and tests

```bash
VENV=/opt/rtlsdr-telegram/venv/bin/python
CFG=/opt/rtlsdr-telegram/config.yaml
$VENV /opt/rtlsdr-telegram/run.py --check -c $CFG
```
Expected: `Dongle: PRESENT — ...`, a list of 16 targets with ✓, `Satellite prediction: on`.
A ✗ means the tool for that target is missing (the target is skipped, nothing else breaks).

```bash
$VENV /opt/rtlsdr-telegram/run.py --test-telegram -c $CFG
```
Expected: `Message sent: [...]` and a test message in your topic.

Run in the foreground once to watch the logs (Ctrl+C stops it):
```bash
$VENV /opt/rtlsdr-telegram/run.py -c $CFG
```

---

## 5. Run as a service

Linux (installed by the script):
```bash
sudo systemctl enable --now rtlsdr-telegram
systemctl status rtlsdr-telegram
journalctl -u rtlsdr-telegram -f          # live log
```
The service restarts automatically on failure and starts at boot. Logs are rotated
(application logs in `logs/`, per-tool logs capped at 5 MB, journal capped at 200 MB).

---

## 6. Check it in Telegram

In your topic write `/status` (or `/durum`). You should get the system status.
Try `/list`, `/passes`, `/scan 145.500` and `/help`. A 🟢 "system started" message is
posted on every start and a daily summary at 09:00 (configurable).

---

## 7. Updating

```bash
cd rtlsdr-telegram && git pull
sudo cp -r rtlsdr_telegram tools run.py requirements.txt /opt/rtlsdr-telegram/
sudo /opt/rtlsdr-telegram/venv/bin/pip install -r requirements.txt
sudo systemctl restart rtlsdr-telegram
```
Your `config.yaml`, database and recordings are not touched.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `No supported devices found` | Dongle not detected. Another port, no hub, re-seat. On Linux check the DVB blacklist (`lsmod | grep dvb_usb_rtl28xxu` must be empty). |
| `usb_claim_interface error -6` | Another program holds the dongle (SDR#, another rtl_* process). Close it. |
| Telegram test fails with 401 | Wrong token. |
| Test sends but nothing appears in the topic | Wrong `chat_id`/`thread_id`, or the bot is not an admin of the group. |
| `/status` gets "Not authorized" | Add your user id (shown in the reply) to `telegram.admins`, restart. |
| Only static is recorded on voice bands | Weak antenna. Raise `min_dynamics_db`/`threshold_dbfs`, or mute the category. |
| High CPU on a Pi | `transcription.model: tiny` or `engine: none`; increase `spectrum.period_s`. |
| No satellite passes | TLE download failed; check internet. `/passes` shows the schedule once it works. |
| Disk filling | `paths.retention_months` smaller; the disk guard prunes recordings below 10% free. |

Logs: `logs/rtlsdr-telegram.log`, `logs/errors.log`, one log per tool (`logs/adsb.log` ...).
