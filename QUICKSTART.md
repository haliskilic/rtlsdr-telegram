# Quick Start

> Türkçe: [QUICKSTART.tr.md](QUICKSTART.tr.md) · Full guide per platform: [docs/INSTALL.md](docs/INSTALL.md)

The shortest path to a running system on Linux (Ubuntu/Debian, Raspberry Pi, Proxmox LXC).

## 1. Telegram (5 minutes)
1. **@BotFather** → `/newbot` → copy the **token**.
2. BotFather → `/mybots` → your bot → *Bot Settings* → *Group Privacy* → **Turn off**.
3. Create a group with **Topics**, open the topic for the bot, add the bot and make it **admin**.
4. Get the ids:
   ```bash
   python3 tools/telegram_ids.py <BOT_TOKEN>      # then write /start@<botname> inside the topic
   ```
   It prints `chat_id`, `thread_id` and your `admin id`.

## 2. Install
```bash
git clone https://github.com/haliskilic/rtlsdr-telegram.git && cd rtlsdr-telegram
sudo bash install/debian-linux.sh        # Raspberry Pi: sudo bash install/raspberrypi.sh
```

## 3. Configure
```bash
sudo nano /opt/rtlsdr-telegram/config.yaml
```
```yaml
language: en                 # or tr
telegram:
  token: "123456:ABC..."
  chat_id: -1001234567890
  thread_id: 7
  admins: [123456789]
station:
  lat: 41.0082               # your location (satellite passes, distances)
  lon: 28.9784
```

## 4. Test and start
```bash
VENV=/opt/rtlsdr-telegram/venv/bin/python
CFG=/opt/rtlsdr-telegram/config.yaml
$VENV /opt/rtlsdr-telegram/run.py --check -c $CFG          # tools + dongle
$VENV /opt/rtlsdr-telegram/run.py --test-telegram -c $CFG  # Telegram
sudo systemctl enable --now rtlsdr-telegram                # run as a service
journalctl -u rtlsdr-telegram -f                           # live log
```

## 5. Try it in Telegram
In the topic: `/status` · `/list` · `/passes` · `/scan 145.500` · `/help`

> No dongle yet? The system starts anyway, says "dongle not found" and resumes
> automatically when you plug it in. In busy areas ADS-B/AIS post one summary per
> slot by default (`report_mode: each` for every single target).
