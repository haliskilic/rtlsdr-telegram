# rtlsdr-telegram

**Multi-band radio monitoring with a single RTL-SDR dongle, delivered to one Telegram topic.**
Aircraft, ships, weather balloons, wireless sensors, amateur packet radio, distress beacons,
GSM cell inventory, voice bands (recorded **and transcribed**), Meteor-M satellite images,
ISS passes and a learning spectrum watchdog — 16 targets scheduled fairly on one RTL2832U.

> 🇹🇷 Türkçe README: [README.tr.md](README.tr.md) · Kurulum: [docs/INSTALL.tr.md](docs/INSTALL.tr.md)

[![License](https://img.shields.io/badge/license-source--available-blue)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-informational)
![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Raspberry%20Pi%20%7C%20Proxmox%20LXC%20%7C%20Windows-success)

- [What it does](#what-it-does)
- [Sample messages](#sample-messages)
- [Installation](#installation)
- [Configuration](#configuration)
- [Telegram commands](#telegram-commands)
- [Security model](#security-model)
- [Architecture](#architecture)
- [The 16 targets and the tools behind them](#the-16-targets-and-the-tools-behind-them)
- [Scheduling on one dongle](#scheduling-on-one-dongle)
- [Retention and disk safety](#retention-and-disk-safety)
- [Troubleshooting](#troubleshooting)
- [License, donations, legal](#license-donations-legal)

## What it does

| | |
|---|---|
| 📡 **One dongle, 16 targets** | A fair scheduler time-slices the RTL-SDR between ADS-B, AIS, ACARS/VDL2, radiosondes, ISM sensors, APRS, 406/121.5 MHz distress beacons, GSM cell IDs, four voice bands, Meteor-M, ISS, Inmarsat and a spectrum sweep. FM radio and TV bands are blacklisted. |
| 💬 **One Telegram topic** | Every event lands in a single topic with a structured header (band, exact frequency, local+UTC time, duration, signal, location, summary) and a category emoji. Emergencies jump the queue and ring. |
| 🎙️ **Record + transcribe** | Voice bands are recorded on squelch/VOX, encoded to Opus and transcribed locally with faster-whisper (Turkish, English, auto-detect). Audio and text arrive together. |
| 🛰️ **Satellite passes** | Meteor-M LRPT images via SatDump and ISS voice/SSTV/packet, scheduled from TLE data. |
| 🔭 **Spectrum watchdog** | Learns the normal noise floor of 24–1766 MHz and reports new strong signals with a waterfall image. |
| 🧰 **Operations** | Daily summary with CSV, `/status`, `/scan`, `/mute`, `/priority` commands, persistent offline queue, circular retention, disk guard, log rotation, systemd service. English by default, Turkish built in. |

## Sample messages

Rendered exactly as the bot formats them (English; the Turkish layout is identical).

### ADS-B — slot summary

```
✈️ ADS-B Summary • Aviation
├ Band      : 1090 MHz ADS-B
├ Frequency : 1090.000 MHz
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : 1 min 30 s
├ Signal    : -9.4 dBFS
├ Location  : —
└ Summary   : 23 aircraft seen (4 new), nearest 6.8 km

Total 23 aircraft (4 new), 19 with position
Listening time: 90 s

• THY1KA    38000 ft   6.8 km NE  🆕
• PGT4R     12300 ft  11.2 km E
• SXS88H     3100 ft  14.9 km SE
… and 16 more aircraft
```

### ADS-B — nearby low aircraft

```
✈️ ADS-B Aircraft • Aviation
├ Band      : 1090 MHz ADS-B
├ Frequency : 1090.000 MHz
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : —
├ Signal    : -11.2 dBFS
├ Location  : 40.9600, 29.3500 (7.1 km NE)
└ Summary   : Nearby aircraft THY1KA — 6.8 km

ICAO address: 4BA9C1
Callsign: THY1KA
Altitude: 2900 ft  ⚠️ low altitude
Ground speed: 182 kt
Heading: 54° (NE)
Squawk: 4521
```

### Marine VHF — voice recording + transcript (audio file attached as a reply)

```
🚢 Marine VHF Voice • Maritime
├ Band      : 156.800 MHz · Channel 16 (Distress/Calling)
├ Frequency : 156.800 MHz
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : 14 s
├ Signal    : -18.3 dBFS (peak)
├ Location  : —
└ Summary   : Coast station, coast station, this is motor vessel Blue Marmara, switching to channel six.

Channel: Channel 16 (Distress/Calling)
Peak level: -18.3 dBFS  (avg -24.1)

📝 Transcript (en):
Coast station, coast station, this is motor vessel Blue Marmara, switching to channel six.
```

### Emergency — 406 MHz distress beacon (priority alarm)

```
🚨 EMERGENCY 406 MHz • Emergency
├ Band      : 406 MHz / 121.5 MHz emergency
├ Frequency : 406.028 MHz
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : —
├ Signal    : +21 dB above floor (peak)
├ Location  : —
└ Summary   : ⚠️ EPIRB/ELT/PLB distress beacon (406 MHz) — 406.028 MHz

EPIRB/ELT/PLB distress beacon (406 MHz)
A strong burst was detected in the 406 MHz band, which is reserved exclusively for EPIRB (ship), ELT (aircraft) and PLB (personal) distress beacons. This may be a real emergency — verify and contact the authorities if appropriate.
```

### Spectrum — new signal (waterfall image attached)

```
🔭 Spectrum Anomaly • General Scan
├ Band      : 240–440 MHz sweep
├ Frequency : 433.075 MHz
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : —
├ Signal    : +18 dB above floor
├ Location  : —
└ Summary   : New signal @ 433.075 MHz (+18 dB)

Peak frequency: 433.075 MHz
Bandwidth: ~75 kHz
Power: -12.4 dB (+18 dB)
Noise floor: -30.6 dB
```

### Meteor-M — LRPT pass (images attached)

```
🛰️ Meteor-M Image • Satellite
├ Band      : 137 MHz Meteor-M LRPT
├ Frequency : 137.100 MHz
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : 12 min 22 s
├ Signal    : —
├ Location  : —
└ Summary   : METEOR-M2 4 pass — 3 images (max 69°)

Satellite: METEOR-M2 4
Frequency: 137.100 MHz
Max elevation: 69°
Images: 3 files
```

### ISM — new devices (one summary per slot)

```
📡 ISM New Devices • ISM/Sensors
├ Band      : 433.92 / 868 MHz ISM
├ Frequency : —
├ Time      : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Duration  : —
├ Signal    : —
├ Location  : —
└ Summary   : New devices: 5 items

11 distinct devices heard in this slot.

• Weather station: Bresser-5in1 #112 (21.3 °C)
• Tire sensor (TPMS): Schrader #a3f1c2 (231 kPa)
• Temperature/Humidity sensor: Nexus-TH #45 (18.9 °C)
• Doorbell/Remote: Honeywell-ActivLink #7f3a
• Device: Generic-Remote #0e11
```

A daily summary (event counts per category, unique aircraft/vessels/sensors, top events,
recorded audio time, images, new devices, uptime, errors) is posted every morning with a CSV export.

## Installation

Full step-by-step guides for every platform (for beginners): **[docs/INSTALL.md](docs/INSTALL.md)**
— Ubuntu/Debian · Raspberry Pi · Proxmox LXC (USB passthrough) · Windows.

Short version (Linux):
```bash
git clone https://github.com/haliskilic/rtlsdr-telegram.git && cd rtlsdr-telegram
sudo bash install/debian-linux.sh                 # packages, source builds, venv, systemd unit
python3 tools/telegram_ids.py <BOT_TOKEN>         # find chat_id / thread_id / your user id
sudo nano /opt/rtlsdr-telegram/config.yaml        # token, chat_id, thread_id, admins, lat/lon
/opt/rtlsdr-telegram/venv/bin/python /opt/rtlsdr-telegram/run.py --check -c /opt/rtlsdr-telegram/config.yaml
sudo systemctl enable --now rtlsdr-telegram
```
See also [QUICKSTART.md](QUICKSTART.md).

## Configuration

One file: `config.yaml` (annotated examples: [config.example.yaml](config.example.yaml),
Turkish [config.example.tr.yaml](config.example.tr.yaml)). Everything is configurable without
touching code: language, Telegram token/group/topic/admins, per-target enable/frequencies/
dwell/period/thresholds/priority, transcription engine and language, daily summary time,
blacklist, station location, retention. Minimal `config.yaml`:

```yaml
language: en
telegram:
  token: "123456789:AAF..."
  chat_id: -1001234567890
  thread_id: 123
  admins: [987654321]
station: {name: "My Station", lat: 41.0082, lon: 28.9784}
```

## Telegram commands

Both English and Turkish command names work regardless of the message language.
Only configured admins are served.

| Command | Turkish alias | Description |
|---------|---------------|-------------|
| `/status` | `/durum` | active targets, current band, CPU/temperature, uptime, next satellite pass |
| `/list` | `/liste` | all targets with state and tool availability |
| `/scan 145.500 [s] [am\|fm]` | `/tara` | listen to a frequency now; recordings + transcript are posted |
| `/mute <category>` | `/sustur` | mute a category (emergencies always pass) |
| `/unmute <category>` | `/ac` | unmute |
| `/priority <target>` | `/oncelik` | move a target to the front of the cycle |
| `/summary` | `/ozet` | daily summary now |
| `/recordings [n]` | `/kayitlar` | resend the last n recordings |
| `/passes [hours]` | `/gecisler` | upcoming Meteor-M / ISS passes |
| `/help` | `/yardim` | command list |

## Security model

- The bot **only posts to the configured chat/topic**.
- Commands are accepted **only from user ids in `telegram.admins`**, and only inside the
  configured group (or in a private chat from an admin). An empty admin list refuses everyone.
- Commands from any other group are ignored; **if the bot is added to a foreign group it leaves
  automatically**; strangers who message it privately get **no reply**.
- The token lives only in `config.yaml` (`chmod 600`), never in logs or the repository
  (errors are scrubbed). Recommended: in BotFather set `/setjoingroups` → Disable.
- These rules are covered by unit tests (`tests/test_security.py`).

## Architecture

```
            ┌───────────────────────────────────────────────┐
            │  Application (config, logging, lifecycle)      │
            └──────────────┬────────────────────────────────┘
   ┌──────────┬────────────┼──────────────┬────────────────┐
┌──▼───┐  ┌───▼──────┐  ┌───▼─────────┐ ┌──▼────────┐ ┌─────▼──────┐
│ SDR  │  │Scheduler │  │ 16 Targets  │ │Dispatcher │ │ Commands   │
│lease │◄─┤fair time-├─►│ (one class  ├─►│ queue →   │ │ (admins    │
│probe │  │ slicing  │  │  each)      │ │ Telegram  │ │  only)     │
└──┬───┘  └──────────┘  └──┬──────┬───┘ └─────┬─────┘ └────────────┘
   │ rtl_fm / rtl_power     │      │           │
┌──▼──────────────┐   ┌─────▼──┐ ┌─▼─────────┐ ┌─▼──────────────────┐
│ external tools  │   │Transcr.│ │Satellite  │ │ SQLite: events,    │
│ readsb rtl_433  │   │worker  │ │predictor  │ │ persistent queue,  │
│ AIS-catcher ... │   │whisper │ │(TLE)      │ │ registry, records  │
└─────────────────┘   └────────┘ └───────────┘ └────────────────────┘
```
Every target is a module in `rtlsdr_telegram/targets/`, produces a common `Event`, runs
external decoders as subprocesses and parses their output. A crashing target never affects
the others; the dispatcher keeps unsent messages in SQLite until Telegram is reachable.

## The 16 targets and the tools behind them

| # | Target | Band | Tool | Output |
|---|--------|------|------|--------|
| 1 | Aircraft ADS-B | 1090 MHz | readsb | per-slot summary, nearby/low alerts, squawk 7500/7600/7700 alarm |
| 2 | ACARS / VDL2 | 131 / 136.9 MHz | acarsdec, dumpvdl2 | text messages |
| 3 | Vessels AIS | 161.975/162.025 MHz | AIS-catcher | per-slot summary, nearby alerts, AIS-SART alarm |
| 4 | Radiosondes | 400–406 MHz | rtl_power (+ radiosonde_auto_rx) | carrier candidates; launch/burst/landing with auto_rx |
| 5 | ISM sensors | 433.92 / 868 MHz | rtl_433 | new devices (batched) |
| 6 | APRS | 144.800 MHz | multimon-ng | positions, messages |
| 7 | Distress beacons | 406 / 121.5 MHz | rtl_power / rtl_fm | **priority alarm**, 121.5 recording |
| 8 | GSM inventory | 900/1800 MHz | gr-gsm | cell IDs only (no content) |
| 9–12 | Voice: amateur, airband, marine, CB/PMR | 144/430, 118–137, 156–162, 27/446 MHz | rtl_fm + VOX | recordings + transcripts |
| 13 | Meteor-M | 137 MHz LRPT | SatDump | images per pass |
| 14 | ISS | 145.800/145.825 MHz | rtl_fm / multimon-ng | voice, SSTV, packets |
| 15 | Inmarsat STD-C/AERO | ~1.5 GHz | SatDump / JAERO | text (needs L-band antenna + LNA; off by default) |
| 16 | Spectrum watchdog | 24–1766 MHz | rtl_power | anomalies with waterfall |

Why these tools: readsb is the maintained dump1090 lineage with JSON output; acarsdec/dumpvdl2
emit JSON natively; AIS-catcher decodes both AIS channels from one dongle; rtl_433 knows hundreds
of sensor protocols; multimon-ng is a light pipe-friendly AFSK decoder; gr-gsm's scanner reads
only broadcast cell identities; SatDump is the actively developed Meteor/Inmarsat pipeline;
faster-whisper is fast on CPU and bilingual.

## Scheduling on one dongle

Targets have a class (`pass` for TLE-driven satellites, `waiting` for dwell-hungry decoders,
`opportunistic` for the rest), a `dwell_s`, a `period_s` and a `priority`. Conflicts resolve as
**emergency > satellite pass > user /priority > normal cycle**; the normal cycle is fair:
`score = (lateness / period) / priority`, and a target that never ran goes first. `/status`
shows what is being listened to and what comes next.

## Retention and disk safety

`paths.retention_days` / `retention_months` / `retention_years` define a circular window:
older recordings, events, runs and errors are deleted hourly; the device registry lives three
times longer so "new device" alerts are not repeated. Per-tool logs rotate at 5 MB, the app log
at 5 MB × 5, the journal is capped at 200 MB (installer). Below `min_free_disk_pct` the oldest
recordings are pruned, recording pauses and a warning is posted once a day. SQLite is vacuumed
monthly.

## Troubleshooting

See the table at the end of [docs/INSTALL.md](docs/INSTALL.md#8-troubleshooting).

## License, donations, legal

This is **source-available** software (see [LICENSE](LICENSE)): evaluate freely for 30 days;
**supporters who donate any amount may use and modify it for personal, non-commercial purposes
free of charge, forever**; any commercial use requires a license from the author. External
decoders keep their own open-source licenses ([THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)).
Contact / donations / commercial licenses: **haliskilic90@gmail.com**.

The software only receives. You are responsible for complying with the radio-monitoring and
privacy laws of your country. The GSM target reads broadcast cell identities only and never
decodes traffic. Distress-beacon detections are best-effort indications, not a safety system —
always alert the proper authorities.
