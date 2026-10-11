# Third-Party Notices

rtlsdr-telegram does **not** bundle or link against the external decoders below.
They are installed separately by the user (via the OS package manager or from
source) and are invoked as independent processes. Each remains governed solely
by its own license. The Python libraries are installed via pip/apt and are
likewise not relicensed by this project.

## External tools (invoked as subprocesses)

| Tool | Purpose | License | Source |
|------|---------|---------|--------|
| rtl-sdr (rtl_fm, rtl_power, rtl_sdr, rtl_test) | RTL2832U driver & utilities | GPL-2.0 | https://github.com/osmocom/rtl-sdr |
| readsb | ADS-B decoder | GPL-3.0 | https://github.com/wiedehopf/readsb |
| rtl_433 | ISM sensor decoder | GPL-2.0 | https://github.com/merbanan/rtl_433 |
| AIS-catcher | AIS decoder | GPL-3.0 | https://github.com/jvde-github/AIS-catcher |
| rtl-ais | AIS decoder (fallback) | GPL-2.0 | https://github.com/dgiardini/rtl-ais |
| acarsdec | ACARS decoder | GPL-2.0 | https://github.com/TLeconte/acarsdec |
| dumpvdl2 | VDL Mode 2 decoder | GPL-3.0 | https://github.com/szpajder/dumpvdl2 |
| libacars | ACARS message parsing library | MIT | https://github.com/szpajder/libacars |
| gr-gsm (grgsm_scanner) | GSM cell-ID scanner | GPL-3.0 | https://github.com/ptrkrysik/gr-gsm |
| SatDump | Meteor-M LRPT / Inmarsat decoding | GPL-3.0 | https://github.com/SatDump/SatDump |
| multimon-ng | AFSK1200/APRS decoder | GPL-2.0 | https://github.com/EliasOenal/multimon-ng |
| direwolf | APRS/AX.25 TNC (alternative) | GPL-2.0 | https://github.com/wb2osz/direwolf |
| radiosonde_auto_rx | Radiosonde telemetry (optional) | GPL-3.0 | https://github.com/projecthorus/radiosonde_auto_rx |
| FFmpeg | Audio transcoding (Opus/MP3) | LGPL-2.1 / GPL-2.0 | https://ffmpeg.org |

## Python libraries

| Library | License | Source |
|---------|---------|--------|
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| httpx | BSD-3-Clause | https://github.com/encode/httpx |
| NumPy | BSD-3-Clause | https://numpy.org |
| SciPy | BSD-3-Clause | https://scipy.org |
| Matplotlib | PSF-based (Matplotlib License) | https://matplotlib.org |
| Pillow | HPND / MIT-CMU | https://python-pillow.org |
| Skyfield | MIT | https://github.com/skyfielders/python-skyfield |
| sgp4 | MIT | https://github.com/brandon-rhodes/python-sgp4 |
| aprslib | MIT | https://github.com/rossengeorgiev/aprs-python |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| OpenAI Whisper models | MIT | https://github.com/openai/whisper |

## Data sources

| Source | Terms |
|--------|-------|
| CelesTrak (TLE) | https://celestrak.org — free for non-commercial use, see site terms |
| tle.ivanstanojevic.me (TLE API) | https://tle.ivanstanojevic.me — see site terms |

If you believe a notice is missing or inaccurate, please open an issue.
