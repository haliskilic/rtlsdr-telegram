#!/usr/bin/env bash
# Raspberry Pi OS (64-bit recommended) installation. Run with sudo.
# Pi notes: insufficient USB power resets the dongle — use a good power supply
# and a short, good USB cable. Pi 4/5 recommended.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Debian based, so the main flow is debian-linux.sh.
# Keep the transcription model small (model: tiny/base).
bash "$SRC_DIR/install/debian-linux.sh"

echo ">>> Raspberry Pi recommendations:"
echo "    - config.yaml: transcription.model: tiny  (low RAM/CPU)"
echo "    - raise spectrum.period_s (sweeps are CPU heavy)"
echo "    - /boot/firmware/config.txt: 'max_usb_current=1' for enough USB current"
echo "    - a heatsink/fan is recommended (satdump and whisper load the CPU)"
