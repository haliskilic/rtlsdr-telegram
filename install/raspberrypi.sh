#!/usr/bin/env bash
# Raspberry Pi OS (64-bit önerilir) kurulumu. sudo ile çalıştırın.
# Pi için notlar: USB güç yetersizliği dongle'ı resetleyebilir — iyi bir güç
# kaynağı ve kısa/kaliteli USB kablo kullanın. Pi 3/4/5 önerilir.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Debian tabanlı olduğundan ana akış debian-linux.sh ile aynıdır.
# Yalnız transkripsiyon modelini küçük tutmanız önerilir (model: tiny/base).
bash "$SRC_DIR/install/debian-linux.sh"

echo ">>> Raspberry Pi önerileri:"
echo "    - config.yaml: transcription.model: tiny  (düşük RAM/CPU)"
echo "    - spectrum.period_s değerini artırın (tarama CPU yoğun)"
echo "    - /boot/firmware/config.txt: yeterli USB akımı için 'max_usb_current=1'"
echo "    - Isınma için soğutucu/fan önerilir (satdump ve whisper CPU yorar)"
